"""Interactive discovery of a channel-fader chain.

Hypothesis: each channel fader is a normalized float in process-writable
memory - fully up == 1.0, fully down == 0.0.  The user moves the fader
through up/down/half/up/quarter on prompt; each step filters the f32 and
f64 candidate sets independently.  Survivors are reverse-walked to module
statics with the probe machinery.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .offsets import FaderPointer, load_offsets, save_offsets
from .pointer import Pointer, read_f32, read_f64
from .probe import CHUNK, DEPTH, FRONTIER_CAP, MAX_REGION, reverse_walk
from .process import MemoryReader, MemoryReadError

PROMPTS: tuple[tuple[str, str], ...] = (
    ("Move channel {n} fader fully UP, then Enter", "up"),
    ("Move channel {n} fader fully DOWN, then Enter", "down"),
    ("Move channel {n} fader to about HALF, then Enter", "half"),
    ("Move channel {n} fader fully UP, then Enter", "up"),
    ("Move channel {n} fader to about a QUARTER, then Enter", "quarter"),
)

ENCODINGS = ("f32", "f64")

_MAX_SURVIVORS = 20


def _iter_writable(
    reader: MemoryReader,
    chunk: int,
    max_region: int,
) -> Iterator[tuple[int, bytes]]:
    for base, size in sorted(reader.writable_regions()):
        if size <= 0 or size > max_region:
            continue
        pos = 0
        while pos < size:
            n = min(chunk, size - pos)
            with contextlib.suppress(MemoryReadError):
                yield base + pos, reader.read(base + pos, n)
            pos += n


def _float_view(base: int, data: bytes, enc: str) -> tuple[int, Any]:
    """Aligned little-endian float view of ``data`` + its first address."""
    import numpy as np

    align = 4 if enc == "f32" else 8
    pad = (-base) % align
    n = (len(data) - pad) // align
    if n <= 0:
        return base, np.empty(0, dtype=np.float64)
    dt = np.dtype("<f4") if enc == "f32" else np.dtype("<f8")
    arr = np.frombuffer(memoryview(data)[pad : pad + n * align], dtype=dt)
    return base + pad, arr


def _float_candidates(
    reader: MemoryReader,
    enc: str,
    *,
    chunk: int,
    max_region: int,
) -> Any:
    """Addresses whose ``enc`` float currently reads 1.0."""
    import numpy as np

    out: list[Any] = []
    for base, data in _iter_writable(reader, chunk, max_region):
        start, arr = _float_view(base, data, enc)
        if not arr.size:
            continue
        idx = np.nonzero(arr == 1.0)[0]
        align = arr.dtype.itemsize
        out.append(start + idx.astype(np.int64) * align)
    return (
        np.concatenate(out) if out else np.empty(0, dtype=np.int64)
    )


def _filter(
    reader: MemoryReader,
    enc: str,
    cands: Any,
    kind: str,
    half: dict[int, float],
    *,
    chunk: int,
    max_region: int,
) -> Any:
    """Keep candidate addresses whose current float matches ``kind``."""
    import numpy as np

    if not len(cands):
        return cands
    align = 4 if enc == "f32" else 8
    wanted = np.asarray(cands, dtype=np.int64)
    keep: list[Any] = []
    for base, data in _iter_writable(reader, chunk, max_region):
        start, arr = _float_view(base, data, enc)
        if not arr.size:
            continue
        addrs = start + np.arange(arr.size, dtype=np.int64) * align
        mask = np.isin(addrs, wanted)
        idx = np.nonzero(mask)[0]
        if not idx.size:
            continue
        a = addrs[idx]
        v = arr[idx].astype(np.float64)
        if kind == "up":
            ok = v == 1.0
        elif kind == "down":
            ok = v == 0.0
        elif kind == "half":
            ok = (v > 0.15) & (v < 0.85)
        else:  # quarter
            hv = np.array(
                [half.get(int(x), 1.0) for x in a], dtype=np.float64
            )
            ok = (v > 0.02) & (v < hv)
        good = a[ok]
        if kind == "half":
            for x, val in zip(a[ok], v[ok], strict=True):
                half[int(x)] = float(val)
        keep.append(good)
    return np.concatenate(keep) if keep else np.empty(0, dtype=np.int64)


@dataclass
class FaderResult:
    encoding: str | None  # None when the hypothesis failed
    pointer: Pointer | None
    chains: list[str]


def fader_scan(
    reader: MemoryReader,
    channel: int,
    *,
    prompt: Callable[[str], str] = input,
    echo: Callable[[str], None] = print,
    chunk: int = CHUNK,
    max_region: int = MAX_REGION,
    depth: int = DEPTH,
    cap: int = FRONTIER_CAP,
) -> FaderResult:
    """Find the channel ``channel`` (1-based) fader chain interactively."""
    t0 = time.monotonic()
    echo(
        "scanning writable regions for normalized-float fader "
        "candidates ..."
    )
    cands = {
        enc: _float_candidates(
            reader, enc, chunk=chunk, max_region=max_region
        )
        for enc in ENCODINGS
    }
    for enc, c in cands.items():
        echo(f"  {enc}: {len(c)} addresses read 1.0")

    half: dict[int, float] = {}
    done = 0
    for i, (label, kind) in enumerate(PROMPTS):
        prompt(label.format(n=channel) + " ")
        done = i + 1
        for enc in ENCODINGS:
            cands[enc] = _filter(
                reader, enc, cands[enc], kind, half,
                chunk=chunk, max_region=max_region,
            )
        echo(
            "  -> survivors: "
            + ", ".join(f"{enc}={len(c)}" for enc, c in cands.items())
        )
        if all(len(c) == 0 for c in cands.values()):
            echo("  normalized-float hypothesis failed")
            return FaderResult(None, None, [])
        total = sum(len(c) for c in cands.values())
        if total <= 3 and done >= 3:
            break

    survivors: dict[int, str] = {}
    for enc, c in cands.items():
        for a in c[:_MAX_SURVIVORS]:
            survivors[int(a)] = enc
    echo(f"  {len(survivors)} survivor(s) to walk back")

    chains = reverse_walk(
        reader,
        {a: (None, [], None) for a in survivors},
        depth=depth,
        cap=cap,
        chunk=chunk,
        max_region=max_region,
        echo=echo,
    )
    if not chains:
        echo("  no module-rooted chains found")
        return FaderResult(None, None, [])

    # validate: the chain must resolve to a live survivor address and read
    # the value that survivor currently holds
    best: tuple[str, Pointer] | None = None
    texts: list[str] = []
    for c in chains:
        ptr = c.pointer()
        try:
            addr = ptr.resolve(reader)
        except MemoryReadError:
            continue
        senc = survivors.get(addr)
        if senc is None:
            texts.append(c.text())
            echo(
                f"    {c.text()} (module+{c.module_off:#x}) "
                "does not land on a survivor - skipped"
            )
            continue
        try:
            val = (read_f32 if senc == "f32" else read_f64)(reader, ptr)
        except MemoryReadError:
            continue
        texts.append(c.text())
        echo(
            f"    {c.text()} ({senc}) resolves to {val:.3f} "
            f"(module+{c.module_off:#x})"
        )
        if best is None:
            best = (senc, ptr)
    if best is None:
        echo("  no chain validated against the live reading")
        return FaderResult(None, None, texts)
    echo(f"  total elapsed {time.monotonic() - t0:.1f}s")
    return FaderResult(best[0], best[1], texts)


def save_fader(
    version: str,
    channel: int,
    pointer: Pointer,
    encoding: str,
    path: Path | None = None,
    echo: Callable[[str], None] = print,
) -> bool:
    """Merge a discovered fader chain into the saved offsets file."""
    existing = load_offsets(version, path)
    if existing is None or existing.anlz_path is None:
        echo(
            f"  no saved offsets for {version} - run `decks scan` first, "
            "then re-run `decks fader-scan`"
        )
        return False
    fader: list[FaderPointer | None] = list(existing.fader or [None] * 4)
    while len(fader) < channel:
        fader.append(None)
    fader[channel - 1] = FaderPointer(pointer, encoding)
    existing.fader = fader
    save_offsets(version, existing, path)
    return True
