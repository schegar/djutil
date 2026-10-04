"""Discover pointer-chain base offsets for the running Rekordbox version.

Hypothesis: only the module-relative base offsets move between versions;
the inner offsets stay the same as 7.2.2.  Each stage searches 8-byte-aligned
slots in a window around the 7.2.2 base, clamped to the module bounds, and
validates candidates against master.db contents:

a. ANLZ path   - resolved string must be a known AnalysisDataPath
b. track info  - first line must equal the DB title of the deck's track
   (same base also gives the master-deck-index chain, validated u8 0..3)
c. BPM/position - f32 within +/-10% of the DB BPM (or half/double),
   i64 sample count in [0, 44100*3h)
"""

from __future__ import annotations

import bisect
import math
import time
from dataclasses import dataclass, field

from .offsets import (
    BUILTIN_BASES,
    NUM_DECKS,
    DeckOffsets,
    bpm_pointer,
    master_index_pointer,
    position_pointer,
    track_info_pointer,
)
from .pointer import read_cstr, read_f32, read_i64, read_u8, read_u64
from .process import MemoryReader, MemoryReadError

DEFAULT_WINDOW = 16 * 1024 * 1024  # +/- 16 MB around the 7.2.2 base
CHUNK = 1 << 20


@dataclass(frozen=True)
class DbTrack:
    content_id: str
    title: str
    bpm: float | None


def norm_anlz_path(path: str) -> str | None:
    """Normalize an ANLZ path to the comparable suffix from ``PIONEER`` on.

    Handles ``D:\\...\\PIONEER\\USBANLZ\\x\\u\\ANLZ0000.DAT`` (memory) and
    ``/PIONEER/USBANLZ/x/u/ANLZ0000.DAT`` (djmdContent.AnalysisDataPath).
    Uses the LAST ``PIONEER`` occurrence - the share dir itself lives under
    ``.../Roaming/Pioneer/rekordbox/share/PIONEER/USBANLZ/...``.
    """
    s = path.replace("\\", "/").upper()
    i = s.rfind("PIONEER")
    return s[i:] if i >= 0 else None


def is_absolute_path(text: str) -> bool:
    """True if the path has a drive-letter or root prefix before PIONEER,
    e.g. ``C:/Users/.../share/PIONEER/...`` vs the relative ``/PIONEER/...``."""
    up = text.upper()
    i = up.rfind("PIONEER")
    if i < 0:
        return False
    prefix = text[:i]
    return ":/" in prefix or ":\\" in prefix


def build_db_map(
    rows: list[dict[str, object]],
) -> dict[str, DbTrack]:
    """Map normalized AnalysisDataPath -> DbTrack from reader rows."""
    out: dict[str, DbTrack] = {}
    for r in rows:
        raw = r.get("AnalysisDataPath")
        if not isinstance(raw, str) or not raw:
            continue
        norm = norm_anlz_path(raw)
        if norm is None:
            continue
        bpm_raw = r.get("BPM")
        bpm = (
            int(bpm_raw) / 100
            if isinstance(bpm_raw, (int, float)) and bpm_raw
            else None
        )
        out[norm] = DbTrack(
            content_id=str(r.get("ID") or ""),
            title=str(r.get("Title") or ""),
            bpm=bpm,
        )
    return out


@dataclass
class ScanResult:
    anlz_base: int | None = None
    info_base: int | None = None
    decks_base: int | None = None
    master_ok: bool = False
    deck_content: dict[int, str] = field(default_factory=dict)
    # candidates per stage: slots passing the stage's deck-0 gate
    candidates: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    notes: list[str] = field(default_factory=list)

    def offsets(self) -> DeckOffsets | None:
        if self.anlz_base is None:
            return None
        return DeckOffsets.from_bases(
            anlz_base=self.anlz_base,
            info_base=self.info_base,
            decks_base=self.decks_base,
            master_ok=self.master_ok,
        )


class _Scanner:
    def __init__(
        self,
        reader: MemoryReader,
        db: dict[str, DbTrack],
        window: int,
        chunk: int,
    ) -> None:
        self.reader = reader
        self.db = db
        self.window = window
        self.chunk = chunk
        regions = sorted(reader.readable_regions())
        self._region_bases = [b for b, _ in regions]
        self._regions = regions

    def _readable(self, addr: int) -> bool:
        i = bisect.bisect_right(self._region_bases, addr) - 1
        return i >= 0 and addr < self._regions[i][0] + self._regions[i][1]

    def _each_slot_value(
        self, ref: int
    ) -> list[tuple[int, int]]:
        """(slot module-offset, u64 value) for readable values in the window."""
        lo = max(0, ref - self.window)
        hi = min(max(0, self.reader.module_size - 8), ref + self.window)
        out: list[tuple[int, int]] = []
        pos = lo
        while pos < hi:
            n = min(self.chunk, hi - pos)
            try:
                data = self.reader.read(self.reader.module_base + pos, n)
            except MemoryReadError:
                pos += n
                continue
            # slots are 8-byte aligned relative to pos (lo is a multiple of 8
            # only if ref and window are; force alignment to be safe)
            start = pos + (-pos % 8)
            for off in range(start - pos, n - 7, 8):
                v = int.from_bytes(data[off : off + 8], "little")
                if v and self._readable(v):
                    out.append((pos + off, v))
            pos += n
        return out

    # -- stage a: ANLZ path base ------------------------------------------------

    def _anlz_path(self, first: int, deck: int) -> str | None:
        try:
            addr = read_u64(self.reader, first + 8 * (deck + 1))
            addr = read_u64(self.reader, addr + 0x3F0)
            data = self.reader.read(addr, 500)
        except MemoryReadError:
            return None
        nul = data.find(b"\x00")
        if nul >= 0:
            data = data[:nul]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return norm_anlz_path(text)

    def stage_anlz(self, ref: int) -> tuple[int | None, dict[int, str], int]:
        best: tuple[int, int] | None = None  # (score, |shift|) -> pick min key
        best_map: dict[int, str] = {}
        best_base: int | None = None
        n_valid = 0
        for slot, first in self._each_slot_value(ref):
            norm = self._anlz_path(first, 0)
            if norm is None or norm not in self.db:
                continue
            n_valid += 1
            decks = {0: self.db[norm].content_id}
            for d in range(1, NUM_DECKS):
                n2 = self._anlz_path(first, d)
                if n2 is not None and n2 in self.db:
                    decks[d] = self.db[n2].content_id
            key = (len(decks), -abs(slot - ref))  # most decks, then closest
            if best is None or key > best:
                best = key
                best_base = slot
                best_map = decks
        return best_base, best_map, n_valid

    # -- stage b: track info / master index base --------------------------------

    def _track_title(self, slot: int, deck: int) -> str | None:
        try:
            text = read_cstr(
                self.reader, track_info_pointer(slot, deck), 200
            )
        except MemoryReadError:
            return None
        return text.split("\n")[0].strip() if text else None

    def stage_info(
        self, ref: int, deck_content: dict[int, str], by_content: dict[str, DbTrack]
    ) -> tuple[int | None, bool, int]:
        if not deck_content:
            return None, False, 0
        best: tuple[int, int] | None = None
        best_base: int | None = None
        n_valid = 0
        for slot, _first in self._each_slot_value(ref):
            matches = sum(
                1
                for d, cid in deck_content.items()
                if (t := self._track_title(slot, d)) is not None
                and t.casefold() == by_content[cid].title.strip().casefold()
            )
            if matches < len(deck_content):
                continue  # all resolved decks must match
            n_valid += 1
            key = (matches, -abs(slot - ref))
            if best is None or key > best:
                best = key
                best_base = slot
        master_ok = False
        if best_base is not None:
            try:
                master_ok = (
                    read_u8(self.reader, master_index_pointer(best_base))
                    < NUM_DECKS
                )
            except MemoryReadError:
                master_ok = False
        return best_base, master_ok, n_valid

    # -- stage c: BPM / position base -------------------------------------------

    def _bpm_ok(self, got: float, want: float | None) -> bool:
        if want is None or want <= 0 or not math.isfinite(got):
            return got > 0 and math.isfinite(got)  # no DB bpm: any plausible f32
        return any(
            abs(got - cand) / cand <= 0.10
            for cand in (want, want * 2, want / 2)
        )

    def stage_decks(
        self, ref: int, deck_content: dict[int, str], by_content: dict[str, DbTrack]
    ) -> tuple[int | None, int]:
        if not deck_content:
            return None, 0
        best_base: int | None = None
        best_dist = -1
        n_valid = 0
        for slot, _first in self._each_slot_value(ref):
            ok = True
            for d, cid in deck_content.items():
                try:
                    bpm = read_f32(self.reader, bpm_pointer(slot, d))
                    pos = read_i64(self.reader, position_pointer(slot, d))
                except MemoryReadError:
                    ok = False
                    break
                if not self._bpm_ok(bpm, by_content[cid].bpm):
                    ok = False
                    break
                if not (0 <= pos < 44100 * 3 * 3600):  # samples, < 3 h
                    ok = False
                    break
            if not ok:
                continue
            n_valid += 1
            dist = abs(slot - ref)
            if best_base is None or dist < best_dist:
                best_base = slot
                best_dist = dist
        return best_base, n_valid


def scan(
    reader: MemoryReader,
    db: dict[str, DbTrack],
    *,
    window: int = DEFAULT_WINDOW,
    chunk: int = CHUNK,
    bases: dict[str, int] | None = None,
) -> ScanResult:
    """Run the three-stage base-offset discovery.  ``db`` maps normalized
    ANLZ paths to DbTrack (see ``build_db_map``)."""
    t0 = time.monotonic()
    bases = bases or BUILTIN_BASES
    sc = _Scanner(reader, db, window, chunk)
    res = ScanResult()

    by_content = {t.content_id: t for t in db.values()}

    res.anlz_base, res.deck_content, res.candidates["anlz"] = sc.stage_anlz(
        bases["anlz"]
    )
    if res.anlz_base is None:
        res.notes.append(
            "ANLZ base not found - are decks loaded? window too small?"
        )
    else:
        res.notes.append(
            f"ANLZ base {res.anlz_base:#x}: "
            f"{len(res.deck_content)} deck(s) matched the library"
        )

    if res.deck_content:
        res.info_base, res.master_ok, res.candidates["info"] = sc.stage_info(
            bases["info"], res.deck_content, by_content
        )
        res.decks_base, res.candidates["decks"] = sc.stage_decks(
            bases["decks"], res.deck_content, by_content
        )
    else:
        res.candidates["info"] = 0
        res.candidates["decks"] = 0
        res.notes.append("no decks resolved - skipping info/BPM stages")

    res.elapsed_s = time.monotonic() - t0
    return res
