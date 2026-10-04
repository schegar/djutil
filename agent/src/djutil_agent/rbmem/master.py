"""Discover the master-deck index chain interactively.

Two modes:
- shaped: filter module slots by the 7.2.2 master-index chain
  (``X 20 278 124`` -> u8 in 0..3) while the user presses MASTER on decks
  1 and 2 alternately.
- fallback: if the shape finds nothing, a shape-free differential scan of
  the module image - keep byte offsets that flip 0/1/0/1 in sync with the
  prompts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .offsets import (
    BASE_722_INFO,
    load_offsets,
    master_index_pointer,
    save_offsets,
)
from .pointer import Pointer, read_u8
from .process import MemoryReader, MemoryReadError
from .scan import CHUNK, DEFAULT_WINDOW, _Scanner

DEFAULT_STEPS: tuple[tuple[str, int], ...] = (
    ("Press MASTER on deck 1, then Enter", 0),
    ("Press MASTER on deck 2, then Enter", 1),
    ("Press MASTER on deck 1 again, then Enter", 0),
    ("Press MASTER on deck 2 again, then Enter", 1),
)

def _master_candidates(
    reader: MemoryReader,
    *,
    window: int,
    chunk: int,
    ref: int,
) -> list[int]:
    """Slots where the 7.2.2 master-index chain reads a u8 in 0..3."""
    sc = _Scanner(reader, {}, window, chunk)
    out: list[int] = []
    for slot, _v in sc._each_slot_value(ref):
        try:
            val = read_u8(reader, master_index_pointer(slot))
        except MemoryReadError:
            continue
        if val < 4:
            out.append(slot)
    return out


def _module_bytes(reader: MemoryReader, chunk: int) -> bytes:
    """Best-effort byte image of the module (unreadable gaps -> zeros)."""
    buf = bytearray()
    pos = 0
    size = reader.module_size
    while pos < size:
        n = min(chunk, size - pos)
        try:
            buf += reader.read(reader.module_base + pos, n)
        except MemoryReadError:
            buf += bytes(n)
        pos += n
    return bytes(buf)


def differential_scan(
    reader: MemoryReader,
    *,
    steps: tuple[tuple[str, int], ...] = DEFAULT_STEPS,
    prompt: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    chunk: int = CHUNK,
) -> list[int]:
    """Shape-free: keep module byte offsets whose value matches 0/1/0/1."""
    import numpy as np

    echo("  snapshotting module image ...")
    img = _module_bytes(reader, chunk)
    positions = np.arange(len(img), dtype=np.int64)
    for label, expected in steps:
        prompt(label + " ")
        img = _module_bytes(reader, chunk)
        cur = np.frombuffer(img, dtype=np.uint8)
        positions = positions[cur[positions] == expected]
        echo(f"  -> {len(positions)} survivors (expected {expected})")
        if len(positions) == 0:
            break
        if len(positions) == 1:
            break
    return [int(p) for p in positions[:20]]


def master_scan(
    reader: MemoryReader,
    *,
    steps: tuple[tuple[str, int], ...] = DEFAULT_STEPS,
    prompt: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    window: int = DEFAULT_WINDOW,
    chunk: int = CHUNK,
    ref: int = BASE_722_INFO,
) -> tuple[int | None, list[int]]:
    """Returns (chosen module slot, fallback survivors).

    ``chosen`` is the module-relative offset for ``master_index_pointer``;
    ``fallback`` holds direct byte offsets when the shape failed.
    """
    cands = _master_candidates(reader, window=window, chunk=chunk, ref=ref)
    echo(f"  {len(cands)} slots where `X 20 278 124` reads a deck index (0..3)")
    if not cands:
        echo(
            "  7.2.2 shape not found; inner offsets moved - "
            "falling back to differential scan of the module"
        )
        return None, differential_scan(
            reader, steps=steps, prompt=prompt, echo=echo, chunk=chunk
        )

    for label, expected in steps:
        prompt(label + " ")
        keep: list[int] = []
        for slot in cands:
            try:
                if read_u8(reader, master_index_pointer(slot)) == expected:
                    keep.append(slot)
            except MemoryReadError:
                pass
        cands = keep
        echo(f"  -> {len(cands)} survivors (expected {expected})")
        if not cands:
            echo("  7.2.2 shape eliminated all candidates; inner offsets moved")
            return None, differential_scan(
                reader, steps=steps, prompt=prompt, echo=echo, chunk=chunk
            )
        if len(cands) == 1:
            break

    if not cands:
        return None, []
    chosen = min(cands, key=lambda s: abs(s - ref))
    return chosen, []


def save_master_index(
    version: str,
    slot: int | None,
    module_off: int | None,
    path: Path | None = None,
    echo: Callable[[str], None] = print,
) -> bool:
    """Merge a discovered master-index chain into the saved offsets file.

    ``slot`` is a shaped-scan result (module offset of the chain's first
    pointer); ``module_off`` a differential result (direct static, chain
    ``X 0``).  Keeps all other fields of the existing entry.
    """
    off = slot if slot is not None else module_off
    if off is None:
        return False
    existing = load_offsets(version, path)
    if existing is None or existing.anlz_path is None:
        echo(
            f"  no saved offsets for {version} - run `decks scan` first, "
            "then re-run `decks master-scan`"
        )
        return False
    existing.master_index = (
        master_index_pointer(off) if slot is not None else Pointer((off,), 0)
    )
    save_offsets(version, existing, path)
    return True


# -- now-playing decision (shared by `decks watch`) ------------------------------


@dataclass
class DeckSnap:
    playing: bool
    playing_since: float | None  # monotonic ts of continuous-play start
    content_id: str | None
    title: str


def pick_now_playing(
    decks: list[DeckSnap],
    master_index: int | None,
    now: float,
    *,
    min_play_s: float = 10.0,
) -> int | None:
    """Deck index that counts as now-playing, or None.

    With a master index: the master deck iff it is playing.  Without one:
    the most recently started deck that has been playing continuously for
    at least ``min_play_s`` seconds.
    """
    if master_index is not None:
        if (
            0 <= master_index < len(decks)
            and decks[master_index].playing
            and decks[master_index].content_id is not None
        ):
            return master_index
        return None
    best: int | None = None
    best_since = -1.0
    for i, d in enumerate(decks):
        if (
            d.playing
            and d.content_id is not None
            and d.playing_since is not None
            and now - d.playing_since >= min_play_s
            and d.playing_since > best_since
        ):
            best = i
            best_since = d.playing_since
    return best
