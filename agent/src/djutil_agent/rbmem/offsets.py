"""Known and discovered pointer-chain offsets per Rekordbox version.

Built-in table holds the Windows 7.2.2 chains.  `decks scan` discovers the
module-relative base offsets for the running version (inner offsets are
hypothesized to be stable) and saves them to
``<agent_data_dir>/rbmem_offsets.json``, keyed by Rekordbox version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..platform.paths import agent_data_dir
from .pointer import Pointer

NUM_DECKS = 4

# -- chain shapes (inner offsets stable across versions, by hypothesis) ------

# 7.2.2 Windows module-relative bases.
BASE_722_ANLZ = 0x057696B8
BASE_722_DECKS = 0x0564B038  # bpm + position
BASE_722_INFO = 0x05737C48  # track info + master index


def anlz_pointer(base: int, deck: int) -> Pointer:
    return Pointer((base, 8 * (deck + 1), 0x3F0), 0)


def bpm_pointer(base: int, deck: int) -> Pointer:
    return Pointer((base, 8 * deck, 0x2B0), 0x1A0)


def position_pointer(base: int, deck: int) -> Pointer:
    return Pointer((base, 8 * deck, 0x2B0), 0x130)


def track_info_pointer(base: int, deck: int) -> Pointer:
    return Pointer((base, 0x20, 0x410, 80 + 8 * deck, 0x168, 0xF0), 0)


def master_index_pointer(base: int) -> Pointer:
    return Pointer((base, 0x20, 0x278), 0x124)


@dataclass
class DeckOffsets:
    """Pointer chains for one Rekordbox version.

    Per-deck fields are lists of length ``NUM_DECKS`` (None when that stage
    failed to locate a base); ``master_index`` shares the track-info base.
    """

    anlz_path: list[Pointer] | None = None
    track_info: list[Pointer] | None = None
    bpm: list[Pointer] | None = None
    position: list[Pointer] | None = None
    master_index: Pointer | None = None

    @classmethod
    def from_bases(
        cls,
        *,
        anlz_base: int | None = None,
        info_base: int | None = None,
        decks_base: int | None = None,
        master_ok: bool = True,
    ) -> DeckOffsets:
        """Build chains for a version from discovered bases + 7.2.2 inners."""
        return cls(
            anlz_path=(
                [anlz_pointer(anlz_base, d) for d in range(NUM_DECKS)]
                if anlz_base is not None
                else None
            ),
            track_info=(
                [track_info_pointer(info_base, d) for d in range(NUM_DECKS)]
                if info_base is not None
                else None
            ),
            bpm=(
                [bpm_pointer(decks_base, d) for d in range(NUM_DECKS)]
                if decks_base is not None
                else None
            ),
            position=(
                [position_pointer(decks_base, d) for d in range(NUM_DECKS)]
                if decks_base is not None
                else None
            ),
            master_index=(
                master_index_pointer(info_base)
                if info_base is not None and master_ok
                else None
            ),
        )

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for name in ("anlz_path", "track_info", "bpm", "position"):
            ptrs = getattr(self, name)
            out[name] = [p.format() for p in ptrs] if ptrs else None
        out["master_index"] = (
            self.master_index.format() if self.master_index else None
        )
        return out

    @classmethod
    def from_json(cls, data: dict[str, object]) -> DeckOffsets:
        def lst(key: str) -> list[Pointer] | None:
            raw = data.get(key)
            if not isinstance(raw, list):
                return None
            return [Pointer.parse(str(p)) for p in raw]

        mi = data.get("master_index")
        return cls(
            anlz_path=lst("anlz_path"),
            track_info=lst("track_info"),
            bpm=lst("bpm"),
            position=lst("position"),
            master_index=Pointer.parse(str(mi)) if mi else None,
        )


BUILTIN: dict[str, DeckOffsets] = {
    "7.2.2": DeckOffsets.from_bases(
        anlz_base=BASE_722_ANLZ,
        info_base=BASE_722_INFO,
        decks_base=BASE_722_DECKS,
    ),
}

BUILTIN_BASES = {
    "anlz": BASE_722_ANLZ,
    "info": BASE_722_INFO,
    "decks": BASE_722_DECKS,
}


def offsets_file(path: Path | None = None) -> Path:
    return path or agent_data_dir() / "rbmem_offsets.json"


def load_offsets(
    version: str, path: Path | None = None
) -> DeckOffsets | None:
    """Saved offsets for ``version``; falls back to the built-in table."""
    f = offsets_file(path)
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        entry = data.get(version)
        if isinstance(entry, dict):
            return DeckOffsets.from_json(entry)
    return BUILTIN.get(version)


def save_offsets(
    version: str, offsets: DeckOffsets, path: Path | None = None
) -> Path:
    f = offsets_file(path)
    data: dict[str, object] = {}
    if f.exists():
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            pass
    data[version] = offsets.to_json()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f
