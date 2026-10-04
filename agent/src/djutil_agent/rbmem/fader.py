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
    """Addresses whose ``enc`` float currently reads ~1.0 (>= 0.995)."""
    import numpy as np

    out: list[Any] = []
    for base, data in _iter_writable(reader, chunk, max_region):
        start, arr = _float_view(base, data, enc)
        if not arr.size:
            continue
        idx = np.nonzero((arr >= 0.995) & (arr <= 1.0001))[0]
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
    """Keep candidate addresses whose current float matches ``kind``.

    Candidates are a sorted int64 array; for each writable chunk a
    ``searchsorted`` slice selects the candidates inside it and chunks
    without candidates are never read (candidates in an unreadable chunk
    are dropped).
    """
    import numpy as np

    if not len(cands):
        return cands
    align = 4 if enc == "f32" else 8
    dt = np.dtype("<f4") if enc == "f32" else np.dtype("<f8")
    wanted = np.sort(np.asarray(cands, dtype=np.int64))
    keep: list[Any] = []
    for base, size in sorted(reader.writable_regions()):
        if size <= 0 or size > max_region:
            continue
        pos = 0
        while pos < size:
            n = min(chunk, size - pos)
            lo = int(np.searchsorted(wanted, base + pos))
            hi = int(np.searchsorted(wanted, base + pos + n))
            if lo < hi:
                try:
                    data = reader.read(base + pos, n)
                except MemoryReadError:
                    pos += n
                    continue
                pad = (-(base + pos)) % align
                m = (len(data) - pad) // align
                if m > 0:
                    arr = np.frombuffer(
                        memoryview(data)[pad : pad + m * align], dtype=dt
                    )
                    c = wanted[lo:hi]
                    rel = c - (base + pos + pad)
                    idx = rel // align
                    valid = (rel >= 0) & (rel % align == 0) & (idx < m)
                    c, idx = c[valid], idx[valid]
                    if len(c):
                        v = arr[idx]
                        if kind == "up":
                            ok = v >= 0.995
                        elif kind == "down":
                            ok = (v <= 0.005) & (v >= -0.0001)
                        elif kind == "half":
                            ok = (v > 0.15) & (v < 0.85)
                        else:  # quarter
                            hv = np.array(
                                [half.get(int(x), 1.0) for x in c],
                                dtype=np.float64,
                            )
                            ok = (v > 0.02) & (v < hv)
                        good = c[ok]
                        if kind == "half":
                            for x, val in zip(good, v[ok], strict=True):
                                half[int(x)] = float(val)
                        keep.append(good)
            pos += n
    return np.concatenate(keep) if keep else np.empty(0, dtype=np.int64)


@dataclass
class FaderResult:
    encoding: str | None  # None when the hypothesis failed
    pointers: list[Pointer]  # validated chains, shortest first
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
        parts = []
        for enc in ENCODINGS:
            if len(cands[enc]):
                echo(f"  filtering {len(cands[enc])} {enc} candidates ...")
            t = time.monotonic()
            cands[enc] = _filter(
                reader, enc, cands[enc], kind, half,
                chunk=chunk, max_region=max_region,
            )
            parts.append(
                f"{enc}={len(cands[enc])} ({time.monotonic() - t:.1f}s)"
            )
        echo("  -> survivors: " + ", ".join(parts))
        if all(len(c) == 0 for c in cands.values()):
            echo("  normalized-float hypothesis failed")
            return FaderResult(None, [], [])
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
        return FaderResult(None, [], [])

    # validate: the chain must resolve to a live survivor address and read
    # the value that survivor currently holds; keep up to 5 alternatives
    validated: list[tuple[str, Pointer]] = []
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
        validated.append((senc, ptr))
    if not validated:
        echo("  no chain validated against the live reading")
        return FaderResult(None, [], texts)
    enc0 = validated[0][0]
    pointers = [p for e, p in validated if e == enc0][:5]
    echo(
        "  tip: channels are usually an 8-byte stride - "
        "compare with other channels"
    )
    echo(f"  total elapsed {time.monotonic() - t0:.1f}s")
    return FaderResult(enc0, pointers, texts)


def read_fader(reader: MemoryReader, entry: FaderPointer) -> float | None:
    """Consensus fader value over the alternative chains.

    Chains that fail to resolve or read outside [-0.01, 1.01] are
    discarded; the rest are clustered (agreement within 0.01) and the
    mean of the largest cluster wins - a stale chain reading 0.0 can no
    longer poison the result.  Ties go to the cluster containing the
    earliest chain.
    """
    import math
    import struct

    size = 4 if entry.encoding == "f32" else 8
    fmt = "<f" if entry.encoding == "f32" else "<d"
    vals: list[float] = []
    for ptr in entry.chains:
        try:
            data = reader.read(ptr.resolve(reader), size)
        except MemoryReadError:
            continue
        v: float = struct.unpack(fmt, data)[0]
        if math.isfinite(v) and -0.01 <= v <= 1.01:
            vals.append(v)
    return _consensus(vals)


def _consensus(vals: list[float]) -> float | None:
    """Mean of the largest cluster (|v - mean| <= 0.01); earliest chain
    breaks ties."""
    groups: list[list[float]] = []
    for v in vals:
        for g in groups:
            if abs(v - sum(g) / len(g)) <= 0.01:
                g.append(v)
                break
        else:
            groups.append([v])
    if not groups:
        return None
    best = max(range(len(groups)), key=lambda i: (len(groups[i]), -i))
    g = groups[best]
    return sum(g) / len(g)


def save_fader(
    version: str,
    channel: int,
    pointers: list[Pointer],
    encoding: str,
    path: Path | None = None,
    echo: Callable[[str], None] = print,
) -> bool:
    """Merge discovered fader chains into the saved offsets file."""
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
    fader[channel - 1] = FaderPointer(tuple(pointers[:5]), encoding)
    existing.fader = fader
    save_offsets(version, existing, path)
    return True
