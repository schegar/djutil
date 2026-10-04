"""Diagnostic probe: locate ANLZ deck paths in Rekordbox memory and walk
the pointer graph back to module-static roots.

Used when ``decks scan`` finds nothing — it answers whether the paths exist
in memory at all, and if so what the real pointer chains look like.
numpy is imported lazily inside the search functions.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .pointer import Pointer
from .process import MemoryReadError
from .scan import DbTrack, is_absolute_path, norm_anlz_path

if TYPE_CHECKING:
    from .process import MemoryReader

CHUNK = 16 << 20          # 16 MB read chunks
MAX_REGION = 1 << 30      # skip regions larger than 1 GB
RANGE = 0x1000            # struct base may sit this far below the field
DEPTH = 4                 # BFS levels back towards a module static
FRONTIER_CAP = 2000       # per level
MAX_STRINGS = 50          # step-2 targets
MAX_CHAINS = 40

_PAT8 = re.compile(
    rb"PIONEER[\\/]USBANLZ[\\/][0-9a-zA-Z\-\\/]{1,80}?ANLZ0000\.(?:DAT|EXT|2EX)",
    re.IGNORECASE,
)
_PAT16 = re.compile(
    r"PIONEER[\\/]USBANLZ[\\/][0-9a-zA-Z\-\\/]{1,80}?ANLZ0000\.(?:DAT|EXT|2EX)",
    re.IGNORECASE,
)
_NEEDLE16 = "PIONEER".encode("utf-16-le")

_EXT_TO_DAT = re.compile(r"\.(EXT|2EX)$")


def _norm_for_db(path: str) -> str | None:
    norm = norm_anlz_path(path)
    if norm is None:
        return None
    return _EXT_TO_DAT.sub(".DAT", norm)


def iter_memory(
    reader: MemoryReader,
    *,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
) -> Iterator[tuple[int, bytes]]:
    """(base_addr, data) over all readable committed regions (<=1 GB)."""
    for base, size in sorted(reader.readable_regions()):
        if size <= 0 or size > max_region:
            continue
        pos = 0
        while pos < size:
            n = min(chunk, size - pos)
            with contextlib.suppress(MemoryReadError):
                yield base + pos, reader.read(base + pos, n)
            pos += n


# -- step 1: find ANLZ path strings -------------------------------------------


@dataclass
class Hit:
    addr: int
    text: str
    enc: str  # "utf-8" | "utf-16le"
    track: DbTrack | None


def _utf8_hits(base: int, data: bytes, max_back: int) -> Iterator[Hit]:
    for m in _PAT8.finditer(data):
        lo = max(0, m.start() - max_back)
        start = data.rfind(b"\x00", lo, m.start()) + 1
        end = data.find(b"\x00", m.end())
        if end < 0:
            end = len(data)
        text = data[start:end].decode("utf-8", errors="replace")
        yield Hit(base + start, text, "utf-8", None)


def _utf16_hits(base: int, data: bytes, max_back: int) -> Iterator[Hit]:
    j = 0
    while True:
        i = data.find(_NEEDLE16, j)
        if i < 0:
            return
        j = i + 2
        # ensure we're inside a plausible region
        dec_end = min(len(data), i + 800)
        text = data[i:dec_end].decode("utf-16-le", errors="ignore")
        if not _PAT16.match(text):
            continue
        # string start: previous aligned double-NUL
        lo = max(0, i - max_back * 2)
        start = i
        while start - 2 >= lo and data[start - 2 : start] != b"\x00\x00":
            start -= 2
        # terminator: aligned double-NUL (same parity as the string start)
        end = dec_end
        e = data.find(b"\x00\x00", i + 2)
        while e >= 0 and e % 2 != i % 2:
            e = data.find(b"\x00\x00", e + 1)
        if 0 <= e < end:
            end = e
        full = data[start:end].decode("utf-16-le", errors="replace")
        yield Hit(base + start, full, "utf-16le", None)


def find_anlz_strings(
    reader: MemoryReader,
    db: dict[str, DbTrack],
    *,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
    max_back: int = 400,
) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[int] = set()
    for base, data in iter_memory(reader, chunk=chunk, max_region=max_region):
        for hit in (*_utf8_hits(base, data, max_back),
                    *_utf16_hits(base, data, max_back)):
            if hit.addr in seen:
                continue
            seen.add(hit.addr)
            norm = _norm_for_db(hit.text)
            hit.track = db.get(norm) if norm else None
            hits.append(hit)
    return hits


# -- step 2: direct pointers to the strings -------------------------------------


def _u8_view(base: int, data: bytes) -> tuple[int, Any]:
    """Aligned little-endian u64 view of ``data`` + its first address."""
    import numpy as np

    pad = (-base) % 8
    n = (len(data) - pad) // 8
    if n <= 0:
        return base, np.empty(0, dtype="<u8")
    arr = np.frombuffer(
        memoryview(data)[pad : pad + n * 8], dtype="<u8"
    )
    return base + pad, arr


def find_value_holders(
    reader: MemoryReader,
    targets: set[int],
    *,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
) -> dict[int, list[int]]:
    """Locations whose aligned qword equals one of ``targets``."""
    import numpy as np

    wanted = np.fromiter(targets, dtype="<u8", count=len(targets))
    out: dict[int, list[int]] = {t: [] for t in targets}
    for base, data in iter_memory(reader, chunk=chunk, max_region=max_region):
        start, arr = _u8_view(base, data)
        if not arr.size:
            continue
        mask = np.isin(arr, wanted)
        for pos in np.nonzero(mask)[0]:
            out[int(arr[pos])].append(start + int(pos) * 8)
    return out


# -- step 3: BFS reverse walk ----------------------------------------------------


@dataclass
class Chain:
    """module_offset + inner offsets (outermost first) + track context."""
    module_off: int
    inners: list[int]
    content_id: str
    title: str

    def text(self) -> str:
        return " ".join(
            [f"{self.module_off:X}", *(f"{i:X}" for i in self.inners), "0"]
        )


def reverse_walk(
    reader: MemoryReader,
    holders: dict[int, tuple[DbTrack | None, list[int]]],
    *,
    depth: int = DEPTH,
    cap: int = FRONTIER_CAP,
    rng: int = RANGE,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
    echo: Callable[[str], None] = print,
) -> list[Chain]:
    """BFS: holder address -> parent qword whose value is a struct base.

    ``holders`` maps a found field address to (track, accumulated inner
    offsets).  Each level finds locations whose value V satisfies
    ``holder - rng <= V <= holder``; the inner offset is ``holder - V``.
    Parents inside the module complete a chain.
    """
    import numpy as np

    mod_lo = reader.module_base
    mod_hi = reader.module_base + reader.module_size
    found: dict[int, Chain] = {}
    frontier = dict(holders)  # addr -> (track, chain-so-far)

    for level in range(1, depth + 1):
        if not frontier:
            break
        t0 = time.monotonic()
        hs = np.array(sorted(frontier), dtype="<u8")
        hs64 = hs.astype(np.int64)
        # collected: (inner, addr, track, chain)
        cand: list[tuple[int, int, DbTrack | None, list[int]]] = []
        for base, data in iter_memory(reader, chunk=chunk,
                                      max_region=max_region):
            start, arr = _u8_view(base, data)
            if not arr.size:
                continue
            vals = arr.astype(np.int64)
            idx = np.searchsorted(hs64, vals, side="left")
            in_range = idx < len(hs64)
            # candidate holder = smallest H >= V
            near = np.minimum(idx, len(hs64) - 1)
            inner = hs64[near] - vals
            mask = in_range & (inner >= 0) & (inner <= rng)
            for pos in np.nonzero(mask)[0]:
                addr = start + int(pos) * 8
                v = int(vals[pos])
                j = int(idx[pos])
                # every holder within [V, V+rng] is a match at this addr
                while j < len(hs64):
                    h = int(hs64[j])
                    d = h - v
                    if d > rng:
                        break
                    track, chain = frontier[h]
                    cand.append((d, addr, track, [d, *chain]))
                    j += 1
        # cap: smallest inner offsets first, dedupe by address
        cand.sort(key=lambda c: (c[0], c[1]))
        new_frontier: dict[int, tuple[DbTrack | None, list[int]]] = {}
        for _inner, addr, track, chain in cand:
            if addr in new_frontier:
                continue
            new_frontier[addr] = (track, chain)
            if mod_lo <= addr < mod_hi:
                off = addr - mod_lo
                if off not in found or len(chain) < len(found[off].inners):
                    found[off] = Chain(
                        module_off=off,
                        inners=chain,
                        content_id=track.content_id if track else "?",
                        title=track.title if track else "?",
                    )
            if len(new_frontier) >= cap:
                break
        frontier = new_frontier
        echo(
            f"  level {level}: {len(hs)} holders -> {len(cand)} parents, "
            f"frontier {len(frontier)}, module hits {len(found)}, "
            f"{time.monotonic() - t0:.1f}s"
        )
    chains = sorted(found.values(), key=lambda c: (len(c.inners), c.module_off))
    return chains[:MAX_CHAINS]


# -- orchestrated report ---------------------------------------------------------

_MAX_SEEDS = 200
_VARIANTS = (-24, -16, -8, 8, 16, 24)


def select_seeds(
    hits: list[Hit],
    *,
    absolute_only: bool = False,
    track_filters: tuple[str, ...] = (),
    cap: int = _MAX_SEEDS,
) -> list[Hit]:
    """Filter DB-matched hits for the step-2 seed set."""
    seeds: list[Hit] = []
    filters = [f.casefold() for f in track_filters]
    for h in hits:
        if h.track is None:
            continue
        if absolute_only and not is_absolute_path(h.text):
            continue
        if filters and not any(
            f == h.track.content_id.casefold()
            or f in h.track.title.casefold()
            for f in filters
        ):
            continue
        seeds.append(h)
        if len(seeds) >= cap:
            break
    return seeds


def _resolve_str(reader: MemoryReader, ptr: Pointer, maxlen: int = 500) -> str | None:
    try:
        data = reader.read(ptr.resolve(reader), maxlen)
    except MemoryReadError:
        return None
    nul = data.find(b"\x00")
    if nul >= 0:
        data = data[:nul]
    try:
        return data.decode("utf-8") or None
    except UnicodeDecodeError:
        return None


def validate_chains(
    reader: MemoryReader,
    db: dict[str, DbTrack],
    chains: list[Chain],
    *,
    echo: Callable[[str], None] = print,
    variants: tuple[int, ...] = _VARIANTS,
) -> None:
    """Resolve each chain + every per-level offset variant that resolves to
    a different DB-matched ANLZ path (how per-deck indices are spotted)."""
    for c in chains:
        base_offsets = [c.module_off, *c.inners]
        text = _resolve_str(reader, Pointer(tuple(base_offsets), 0))
        norm = _norm_for_db(text) if text else None
        live = db.get(norm) if norm else None
        echo(
            f"    {c.text()} resolves to "
            f"{text!r} -> {live.title if live else '?'}"
        )
        for i in range(len(base_offsets)):
            for delta in variants:
                off = base_offsets[i] + delta
                if off < 0:
                    continue
                v = list(base_offsets)
                v[i] = off
                t2 = _resolve_str(reader, Pointer(tuple(v), 0))
                if not t2 or t2 == text:
                    continue
                n2 = _norm_for_db(t2)
                if n2 and n2 != norm and n2 in db:
                    echo(
                        f"      level {i} {base_offsets[i]:#x}{delta:+#x} "
                        f"-> {t2!r} ({db[n2].title} [{db[n2].content_id}])"
                    )


def snapshot(
    reader: MemoryReader,
    *,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
) -> dict[int, tuple[str, str | None]]:
    """addr -> (normalized path or raw text, raw text) for all ANLZ strings."""
    out: dict[int, tuple[str, str | None]] = {}
    for base, data in iter_memory(reader, chunk=chunk, max_region=max_region):
        for hit in (
            *_utf8_hits(base, data, 400),
            *_utf16_hits(base, data, 400),
        ):
            out[hit.addr] = (_norm_for_db(hit.text) or hit.text, hit.text)
    return out


def _continue_probe(
    reader: MemoryReader,
    db: dict[str, DbTrack],
    seeds: list[Hit],
    *,
    echo: Callable[[str], None],
    chunk: int,
    max_region: int,
    depth: int,
    cap: int,
    t0: float,
) -> None:
    mod_lo = reader.module_base

    echo("== step 2: direct pointers to the strings ==")
    targets = {h.addr for h in seeds}
    holders = find_value_holders(
        reader, targets, chunk=chunk, max_region=max_region
    )
    total_refs = sum(len(v) for v in holders.values())
    echo(f"  {total_refs} pointer(s) to {len(targets)} seed string(s)")
    holder_map: dict[int, tuple[DbTrack | None, list[int]]] = {}
    s_to_hit = {h.addr: h for h in seeds}
    for s, addrs in holders.items():
        hit = s_to_hit.get(s)
        for a in addrs:
            loc = (
                f"module+{a - mod_lo:#x}"
                if mod_lo <= a < mod_lo + reader.module_size
                else f"{a:#x}"
            )
            if hit is not None and hit.track is not None:
                echo(f"    {loc} -> {hit.text!r} ({hit.track.title})")
            holder_map[a] = (hit.track if hit else None, [])
    if not holder_map:
        echo("  nobody points at the strings - cannot walk back.")
        echo(f"  total elapsed {time.monotonic() - t0:.1f}s")
        return

    echo("== step 3: reverse walk to module statics ==")
    chains = reverse_walk(
        reader, holder_map, depth=depth, cap=cap, chunk=chunk,
        max_region=max_region, echo=echo,
    )
    if not chains:
        echo("  no module-rooted chains found")
    for c in chains:
        shape = (
            "7.2.2-shape"
            if len(c.inners) == 2
            and c.inners[0] in {8 * (d + 1) for d in range(4)}
            and c.inners[1] == 0x3F0
            else f"{len(c.inners)}-level"
        )
        shift = c.module_off - 0x057696B8
        echo(
            f"    {c.text()}  [{shape}] "
            f"({c.title} / {c.content_id}) "
            f"vs 7.2.2 base 0x57696B8: {shift:+#x}"
        )
    echo("== chain validation ==")
    validate_chains(reader, db, chains, echo=echo)
    echo(f"  total elapsed {time.monotonic() - t0:.1f}s")


def run(
    reader: MemoryReader,
    db: dict[str, DbTrack],
    *,
    echo: Callable[[str], None] = print,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
    depth: int = DEPTH,
    cap: int = FRONTIER_CAP,
    absolute_only: bool = False,
    track_filters: tuple[str, ...] = (),
    diff: bool = False,
    prompt: Callable[[str], str] = input,
) -> None:
    """Full probe: strings -> direct refs -> reverse walk. Prints as it goes."""
    t0 = time.monotonic()

    if diff:
        echo("== diff mode: snapshot 1 ==")
        snap1 = snapshot(reader, chunk=chunk, max_region=max_region)
        echo(f"  {len(snap1)} ANLZ strings in memory")
        prompt("Load a DIFFERENT track on deck 1 now, then press Enter ")
        snap2 = snapshot(reader, chunk=chunk, max_region=max_region)
        prev_norms = {n for n, _ in snap1.values()}
        seeds: list[Hit] = []
        for addr, (norm, text) in snap2.items():
            if norm in prev_norms and addr not in snap1:
                continue
            if norm in prev_norms and snap1[addr][1] == text:
                continue
            trk = db.get(norm)
            seeds.append(Hit(addr, text or "", "?", trk))
        echo(f"  {len(snap2)} strings now; {len(seeds)} new/changed seeds:")
        for h in seeds[:20]:
            tag = f" ({h.track.title})" if h.track else ""
            echo(f"    @{h.addr:#x} {h.text!r}{tag}")
        if not seeds:
            echo("  nothing changed - stopping.")
            return
        _continue_probe(
            reader, db, seeds, echo=echo, chunk=chunk,
            max_region=max_region, depth=depth, cap=cap, t0=t0,
        )
        return

    echo("== step 1: ANLZ path strings ==")
    hits = find_anlz_strings(reader, db, chunk=chunk, max_region=max_region)
    matched = [h for h in hits if h.track is not None]
    encs = sorted({h.enc for h in hits})
    echo(
        f"  {len(hits)} ANLZ string hits "
        f"(encodings: {', '.join(encs) or 'none'}), "
        f"{len(matched)} matched to library tracks"
    )
    for h in hits[:10]:
        tag = f" -> {h.track.title} [{h.track.content_id}]" if h.track else ""
        echo(f"    @{h.addr:#x} ({h.enc}) {h.text!r}{tag}")
    abs_matched = [h for h in matched if is_absolute_path(h.text)]
    echo(f"  {len(abs_matched)} matched ABSOLUTE strings:")
    for h in abs_matched[:100]:
        echo(
            f"    @{h.addr:#x} {h.text!r}"
            f" -> {h.track.title} [{h.track.content_id}]"  # type: ignore[union-attr]
        )
    if len(abs_matched) > 100:
        echo(f"    ... and {len(abs_matched) - 100} more")
    seeds = select_seeds(
        hits, absolute_only=absolute_only, track_filters=track_filters
    )
    echo(f"  seeds selected: {len(seeds)}")
    if not seeds:
        echo("  no seeds after filtering - stopping.")
        echo(f"  total elapsed {time.monotonic() - t0:.1f}s")
        return
    _continue_probe(
        reader, db, seeds, echo=echo, chunk=chunk,
        max_region=max_region, depth=depth, cap=cap, t0=t0,
    )
