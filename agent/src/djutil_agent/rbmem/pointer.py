"""Pointer chains into Rekordbox process memory.

Chain semantics (same as rkbx_link): start at the module base, then for each
offset in ``offsets`` dereference ``u64`` at ``addr + off``; finally add
``final`` without dereferencing and read the value there.

Text format: space-separated hex, all but the last number are dereference
offsets, the last is the final addend.  E.g. ``057696B8 8 3F0 0`` resolves as
``u64(u64(u64(base + 0x057696B8) + 0x8) + 0x3F0) + 0``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .process import MemoryReader


@dataclass(frozen=True)
class Pointer:
    offsets: tuple[int, ...]
    final: int = 0

    @classmethod
    def parse(cls, text: str) -> Pointer:
        parts = text.split()
        if len(parts) < 2:
            raise ValueError(f"need at least one offset and a final: {text!r}")
        try:
            vals = [int(p, 16) for p in parts]
        except ValueError as exc:
            raise ValueError(f"bad pointer line {text!r}: {exc}") from exc
        return cls(tuple(vals[:-1]), vals[-1])

    def format(self) -> str:
        return " ".join(f"{v:X}" for v in (*self.offsets, self.final))

    def resolve(self, reader: MemoryReader) -> int:
        """Walk the chain; returns the address the value lives at."""
        addr = reader.module_base
        for off in self.offsets:
            addr = read_u64(reader, addr + off)
        return addr + self.final


def read_u64(reader: MemoryReader, addr: int) -> int:
    return int.from_bytes(reader.read(addr, 8), "little")


def read_u8(reader: MemoryReader, ptr: Pointer) -> int:
    return reader.read(ptr.resolve(reader), 1)[0]


def read_f32(reader: MemoryReader, ptr: Pointer) -> float:
    v: float = struct.unpack("<f", reader.read(ptr.resolve(reader), 4))[0]
    return v


def read_f64(reader: MemoryReader, ptr: Pointer) -> float:
    v: float = struct.unpack("<d", reader.read(ptr.resolve(reader), 8))[0]
    return v


def read_i64(reader: MemoryReader, ptr: Pointer) -> int:
    return int.from_bytes(reader.read(ptr.resolve(reader), 8), "little",
                          signed=True)


def read_cstr(reader: MemoryReader, ptr: Pointer, maxlen: int) -> str:
    data = reader.read(ptr.resolve(reader), maxlen)
    nul = data.find(b"\x00")
    if nul >= 0:
        data = data[:nul]
    return data.decode("utf-8", errors="replace")
