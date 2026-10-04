"""Unit tests for the rbmem deck-state reader (FakeMemory, no real process)."""

from __future__ import annotations

import struct

import pytest

from djutil_agent.rbmem.offsets import (
    BASE_722_ANLZ,
    BASE_722_DECKS,
    BASE_722_INFO,
    BUILTIN,
    DeckOffsets,
    load_offsets,
    save_offsets,
)
from djutil_agent.rbmem.pointer import (
    Pointer,
    read_cstr,
    read_f64,
    read_u8,
    read_u64,
)
from djutil_agent.rbmem.process import MemoryReadError
from djutil_agent.rbmem.scan import DbTrack, build_db_map, norm_anlz_path, scan

MODULE_BASE = 0x140000000
MODULE_SIZE = 0x06000000
HEAP_BASE = 0x200000000
HEAP_SIZE = 0x100000


class FakeMemory:
    """Sparse in-memory address space: regions readable, bytes default 0."""

    def __init__(
        self,
        base: int = MODULE_BASE,
        size: int = MODULE_SIZE,
        version: str = "7.2.10",
    ) -> None:
        self._base = base
        self._size = size
        self._version = version
        self.bytes: dict[int, int] = {}
        self.regions: list[tuple[int, int]] = [(base, size), (HEAP_BASE, HEAP_SIZE)]
        self._heap_next = HEAP_BASE

    @property
    def module_base(self) -> int:
        return self._base

    @property
    def module_size(self) -> int:
        return self._size

    @property
    def version(self) -> str:
        return self._version

    def readable_regions(self) -> list[tuple[int, int]]:
        return sorted(self.regions)

    def _in_region(self, addr: int, size: int) -> bool:
        return any(
            b <= addr and addr + size <= b + n for b, n in self.regions
        )

    def read(self, addr: int, size: int) -> bytes:
        if size < 0 or not self._in_region(addr, size):
            raise MemoryReadError(f"unreadable {size:#x} @ {addr:#x}")
        return bytes(self.bytes.get(addr + i, 0) for i in range(size))

    # -- planting helpers ------------------------------------------------------

    def alloc(self, n: int) -> int:
        addr = self._heap_next
        self._heap_next += n
        return addr

    def write(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.bytes[addr + i] = b

    def write_u64(self, addr: int, value: int) -> None:
        self.write(addr, value.to_bytes(8, "little"))

    def write_u8(self, addr: int, value: int) -> None:
        self.bytes[addr] = value

    def write_f32(self, addr: int, value: float) -> None:
        self.write(addr, struct.pack("<f", value))

    def write_f64(self, addr: int, value: float) -> None:
        self.write(addr, struct.pack("<d", value))

    def write_str(self, addr: int, text: str) -> None:
        self.write(addr, text.encode("utf-8") + b"\x00")

    def plant_chain(self, ptr: Pointer, data: bytes) -> int:
        """Plant a pointer chain so ``ptr`` resolves to a buffer holding
        ``data``.  Returns the value address."""
        addr = self._base
        for off in ptr.offsets:
            nxt = self.alloc(64)
            self.write_u64(addr + off, nxt)
            addr = nxt
        final = addr + ptr.final
        self.write(final, data)
        return final


# -- pointer -------------------------------------------------------------------


def test_pointer_parse_format_roundtrip():
    p = Pointer.parse("057696B8 8 3F0 0")
    assert p.offsets == (0x057696B8, 0x8, 0x3F0)
    assert p.final == 0
    assert p.format() == "57696B8 8 3F0 0"
    assert Pointer.parse(p.format()) == p


def test_pointer_parse_rejects_garbage():
    with pytest.raises(ValueError):
        Pointer.parse("zzzz 8 0")
    with pytest.raises(ValueError):
        Pointer.parse("3F0")  # no final


def test_pointer_resolve_and_reads():
    mem = FakeMemory()
    ptr = Pointer.parse("1000 8 20 4")
    target = mem.plant_chain(ptr, struct.pack("<d", 123.5))
    assert ptr.resolve(mem) == target
    assert read_f64(mem, ptr) == 123.5

    ptr2 = Pointer.parse("1008 0 10 0")
    mem.plant_chain(ptr2, b"hello world\x00junk")
    assert read_cstr(mem, ptr2, 200) == "hello world"

    ptr3 = Pointer.parse("1010 0")
    mem.plant_chain(ptr3, b"\x02")
    assert read_u8(mem, ptr3) == 2


def test_read_u64_out_of_bounds():
    mem = FakeMemory()
    with pytest.raises(MemoryReadError):
        read_u64(mem, MODULE_BASE + MODULE_SIZE + 8)


# -- ANLZ path normalization ----------------------------------------------------


def test_norm_anlz_path():
    mem_path = "D:\\PIONEER\\USBANLZ\\P000\\0123\\ANLZ0000.DAT"
    db_path = "/PIONEER/USBANLZ/P000/0123/ANLZ0000.DAT"
    assert norm_anlz_path(mem_path) == norm_anlz_path(db_path)
    # case-insensitive, deep prefixes stripped
    assert norm_anlz_path("c:\\users\\x\\pioneer\\usbanlz\\a.DAT") == (
        "PIONEER/USBANLZ/A.DAT"
    )
    assert norm_anlz_path("/no/match/here.DAT") is None


def test_build_db_map():
    rows = [
        {
            "ID": "t1",
            "Title": "Song One",
            "BPM": 12800,
            "AnalysisDataPath": "/PIONEER/USBANLZ/x/u/ANLZ0000.DAT",
        },
        {"ID": "t2", "Title": "No path", "BPM": 10000, "AnalysisDataPath": ""},
    ]
    db = build_db_map(rows)
    assert len(db) == 1
    t = db["PIONEER/USBANLZ/X/U/ANLZ0000.DAT"]
    assert t.content_id == "t1" and t.bpm == 128.0


# -- offsets file ----------------------------------------------------------------


def test_offsets_json_roundtrip(tmp_path):
    offs = DeckOffsets.from_bases(
        anlz_base=0x588CB08, info_base=0x5738C48, decks_base=0x564AC38
    )
    path = tmp_path / "rbmem_offsets.json"
    save_offsets("7.2.10", offs, path)
    got = load_offsets("7.2.10", path)
    assert got is not None
    assert got.anlz_path == offs.anlz_path
    assert got.master_index == offs.master_index
    assert got.bpm == offs.bpm


def test_offsets_builtin_fallback(tmp_path):
    missing = tmp_path / "none.json"
    assert load_offsets("9.9.9", missing) is None
    built = load_offsets("7.2.2", missing)
    assert built is not None and built is BUILTIN["7.2.2"]
    # spot-check a built-in chain
    assert built.master_index is not None
    assert built.master_index.offsets == (BASE_722_INFO, 0x20, 0x278)
    assert built.anlz_path is not None
    assert built.anlz_path[0].offsets == (BASE_722_ANLZ, 8, 0x3F0)


# -- scan ------------------------------------------------------------------------


def _db_tracks() -> tuple[dict[str, DbTrack], list[str]]:
    paths = [
        "PIONEER/USBANLZ/A/1/ANLZ0000.DAT",
        "PIONEER/USBANLZ/B/2/ANLZ0000.DAT",
    ]
    db = {
        paths[0]: DbTrack("c1", "Song One", 128.0),
        paths[1]: DbTrack("c2", "Song Two", 122.5),
    }
    return db, paths


def _plant_anlz(mem: FakeMemory, slot: int, deck: int, path_suffix: str,
                first: int | None = None) -> int:
    """Plant one deck's ANLZ entry.  ``first`` is the shared deck-array
    pointer stored at the slot; it is allocated on the first call."""
    if first is None:
        first = mem.alloc(64)
        mem.write_u64(mem.module_base + slot, first)
    second = mem.alloc(64)
    mem.write_u64(first + 8 * (deck + 1), second)
    s = mem.alloc(512)
    mem.write_u64(second + 0x3F0, s)
    mem.write_str(s, f"D:\\rb\\{path_suffix}")
    return first


def _plant_info_and_master(
    mem: FakeMemory, slot: int, deck: int, title: str, master: int = 1,
    chain: tuple[int, int, int] | None = None,
) -> tuple[int, int, int]:
    """Plant one deck's track-info entry (and the shared master-index chain
    on the first call).  Returns the shared (first, a, b) pointers."""
    if chain is None:
        first = mem.alloc(64)
        mem.write_u64(mem.module_base + slot, first)
        a = mem.alloc(0x400)
        mem.write_u64(first + 0x20, a)
        b = mem.alloc(0x500)
        mem.write_u64(a + 0x410, b)
        m = mem.alloc(64)
        mem.write_u64(a + 0x278, m)
        mem.write_u8(m + 0x124, master)
        chain = (first, a, b)
    _, _, b = chain
    c = mem.alloc(0x300)
    mem.write_u64(b + 0x80 + 8 * deck, c)
    d = mem.alloc(0x200)
    mem.write_u64(c + 0x168, d)
    s = mem.alloc(256)
    mem.write_u64(d + 0xF0, s)
    mem.write_str(s, f"{title}\nSome Artist\n")
    return chain


def _plant_bpm_pos(
    mem: FakeMemory, slot: int, deck: int, bpm: float, pos: float,
    first: int | None = None,
) -> int:
    if first is None:
        first = mem.alloc(64)
        mem.write_u64(mem.module_base + slot, first)
    second = mem.alloc(64)
    mem.write_u64(first + 8 * deck, second)
    third = mem.alloc(0x400)
    mem.write_u64(second + 0x2B0, third)
    mem.write_f32(third + 0x1A0, bpm)
    mem.write_f64(third + 0x130, pos)
    return first


def test_scan_finds_shifted_bases():
    mem = FakeMemory()
    db, paths = _db_tracks()
    anlz_base = BASE_722_ANLZ + 0x123450
    info_base = BASE_722_INFO - 0x40000
    decks_base = BASE_722_DECKS + 0x888
    anlz_first = info_chain = decks_first = None
    for d, (suffix, track) in enumerate(
        zip(("PIONEER/USBANLZ/A/1/ANLZ0000.DAT", "PIONEER/USBANLZ/B/2/ANLZ0000.DAT"),
            db.values(), strict=True)
    ):
        anlz_first = _plant_anlz(mem, anlz_base, d, suffix, anlz_first)
        info_chain = _plant_info_and_master(
            mem, info_base, d, track.title, chain=info_chain
        )
        decks_first = _plant_bpm_pos(
            mem, decks_base, d, track.bpm or 0, 1234.5 + d, decks_first
        )

    res = scan(mem, db, window=0x140000, chunk=1 << 16)
    assert res.anlz_base == anlz_base
    assert res.deck_content == {0: "c1", 1: "c2"}
    assert res.info_base == info_base
    assert res.master_ok is True
    assert res.decks_base == decks_base

    offs = res.offsets()
    assert offs is not None
    assert offs.anlz_path is not None and len(offs.anlz_path) == 4


def test_scan_missing_info_stage_leaves_none():
    mem = FakeMemory()
    db, _ = _db_tracks()
    anlz_base = BASE_722_ANLZ - 0x80000
    _plant_anlz(mem, anlz_base, 0, "PIONEER/USBANLZ/A/1/ANLZ0000.DAT")

    res = scan(mem, db, window=0x140000, chunk=1 << 16)
    assert res.anlz_base == anlz_base
    assert res.info_base is None  # not planted -> stage reports failure
    assert res.decks_base is None
    offs = res.offsets()
    assert offs is not None
    assert offs.track_info is None and offs.bpm is None


def test_scan_no_decks_reports():
    mem = FakeMemory()
    db, _ = _db_tracks()
    res = scan(mem, db, window=0x100000, chunk=1 << 16)
    assert res.anlz_base is None
    assert res.offsets() is None
    assert res.candidates["anlz"] == 0


# -- probe -----------------------------------------------------------------------


def _probe_mem() -> FakeMemory:
    """Small fake address space for probe tests."""
    return FakeMemory(base=MODULE_BASE, size=0x40000)


def test_probe_finds_utf8_and_utf16_strings():
    from djutil_agent.rbmem.probe import find_anlz_strings

    mem = _probe_mem()
    db, _ = _db_tracks()
    s1 = mem.alloc(600)
    mem.write(s1, b"title\x00D:\\rb\\PIONEER\\USBANLZ\\A\\1\\ANLZ0000.DAT\x00")
    s2 = mem.alloc(1200)
    mem.write(
        s2,
        b"\x00\x00"
        + "PIONEER/USBANLZ/B/2/ANLZ0000.EXT".encode("utf-16-le")
        + b"\x00\x00",
    )
    # find string starts, not the pattern start: plant the utf8 path offset
    str8 = s1 + len(b"title\x00")
    hits = find_anlz_strings(mem, db)
    by_enc = {h.enc: h for h in hits}
    assert set(by_enc) == {"utf-8", "utf-16le"}
    assert by_enc["utf-8"].addr == str8
    assert by_enc["utf-8"].track is not None
    assert by_enc["utf-8"].track.content_id == "c1"
    # .EXT normalizes to .DAT for matching
    assert by_enc["utf-16le"].track is not None
    assert by_enc["utf-16le"].track.content_id == "c2"


def test_probe_reverse_walk_recovers_chain():
    from djutil_agent.rbmem.probe import (
        find_value_holders,
        reverse_walk,
    )

    mem = _probe_mem()
    db, _ = _db_tracks()
    track = db["PIONEER/USBANLZ/A/1/ANLZ0000.DAT"]
    # non-7.2.2 chain: module+0x2000 -> SA --(+0x40)--> SB --(+0x88)--> string
    sa = mem.alloc(0x100)
    mem.alloc(0x2000)  # gap so sa isn't a parent of the holder itself
    sb = mem.alloc(0x100)
    s = mem.alloc(200)
    mem.write_str(s, "D:\\rb\\PIONEER\\USBANLZ\\A\\1\\ANLZ0000.DAT")
    mem.write_u64(mem.module_base + 0x2000, sa)
    mem.write_u64(sa + 0x40, sb)
    mem.write_u64(sb + 0x88, s)  # holder of S

    holders = find_value_holders(mem, {s})
    assert holders[s] == [sb + 0x88]
    chains = reverse_walk(
        mem,
        {sb + 0x88: (track, [])},
        echo=lambda _m: None,
        chunk=1 << 16,
    )
    assert len(chains) == 1
    c = chains[0]
    assert c.module_off == 0x2000
    assert c.inners == [0x40, 0x88]
    assert c.text() == "2000 40 88 0"
    assert c.content_id == "c1"


def test_probe_seed_selection_absolute_only():
    from djutil_agent.rbmem.probe import Hit, select_seeds
    from djutil_agent.rbmem.scan import DbTrack

    t = DbTrack("c1", "Song One", 128.0)
    hits = [
        Hit(1, "C:/u/share/PIONEER/USBANLZ/A/1/ANLZ0000.DAT", "utf-8", t),
        Hit(2, "/PIONEER/USBANLZ/A/1/ANLZ0000.DAT", "utf-8", t),
        Hit(3, "C:/u/share/PIONEER/USBANLZ/X/9/ANLZ0000.DAT", "utf-8", None),
    ]
    seeds = select_seeds(hits, absolute_only=True)
    assert [h.addr for h in seeds] == [1]  # absolute + DB-matched only
    # no flag -> all DB-matched strings seed
    assert [h.addr for h in select_seeds(hits)] == [1, 2]
    # track filter matches title substring, case-insensitive
    assert [h.addr for h in select_seeds(hits, track_filters=("SONG",))] == [1, 2]
    assert select_seeds(hits, track_filters=("zzz",)) == []


def test_probe_validate_finds_deck_variant():
    from djutil_agent.rbmem.probe import Chain, validate_chains

    mem = _probe_mem()
    db, _ = _db_tracks()
    # deck array: module+0x3000 -> first; first+8 -> deck1; first+0x10 -> deck2
    first = mem.alloc(0x100)
    mem.write_u64(mem.module_base + 0x3000, first)
    strs = {}
    for deck, suffix in (
        (0x8, "PIONEER/USBANLZ/A/1/ANLZ0000.DAT"),
        (0x10, "PIONEER/USBANLZ/B/2/ANLZ0000.DAT"),
    ):
        d = mem.alloc(0x200)
        mem.write_u64(first + deck, d)
        s = mem.alloc(0x100)
        mem.write_u64(d + 0xA0, s)
        strp = mem.alloc(200)
        mem.write_u64(s + 0xDD0, strp)
        mem.write_str(strp, f"D:\\rb\\{suffix}")
        strs[deck] = strp
    c = Chain(module_off=0x3000, inners=[0x8, 0xA0, 0xDD0],
              content_id="c1", title="Song One")
    out: list[str] = []
    validate_chains(mem, db, [c], echo=out.append)
    joined = "\n".join(out)
    assert "Song One" in joined          # the chain resolves
    assert "Song Two" in joined          # +8 on level 1 reveals deck 2
    assert "0x8+0x8" in joined
