"""Deck-state polling for the live pipeline.

``read_deck`` samples one deck (shared with `decks watch`);
``DeckWatcher`` wraps it with process management, offsets loading and a
:class:`NowPlayingTracker`, yielding :class:`PlayEvent`s (source="deck").
"""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from djutil_shared import PlayEvent

from .fader import read_fader
from .nowplaying import DeckSample, NowPlayingTracker, is_playing
from .offsets import DeckOffsets, load_offsets
from .pointer import read_cstr, read_f32, read_i64
from .process import (
    MemoryReader,
    MemoryReadError,
    ProcessNotFoundError,
    UnsupportedPlatform,
    WindowsProcess,
)
from .scan import DbTrack, norm_anlz_path

logger = logging.getLogger(__name__)

REOPEN_S = 5.0
DB_REFRESH_S = 30.0


@dataclass
class DeckRead:
    """One deck's state at a single sample."""

    key: str | None      # track identity (cid or normalized path)
    cid: str | None
    title: str
    bpm: float | None
    pos: int | None      # i64 samples
    fader: float | None
    unknown_path: bool   # ANLZ path read but not in the DB map


def read_deck(
    proc: MemoryReader,
    offs: DeckOffsets,
    db: dict[str, DbTrack],
    d: int,
) -> DeckRead | None:
    """Sample deck ``d``; None when the ANLZ chain can't be read."""
    assert offs.anlz_path is not None
    try:
        raw = read_cstr(proc, offs.anlz_path[d], 500)
    except MemoryReadError:
        return None
    norm = norm_anlz_path(raw)
    track = db.get(norm) if norm else None
    title = None
    if offs.track_info:
        with contextlib.suppress(MemoryReadError):
            info = read_cstr(proc, offs.track_info[d], 200)
            title = info.split("\n")[0].strip() or None
    title = title or (track.title if track else "?")
    bpm = pos = None
    if offs.bpm:
        with contextlib.suppress(MemoryReadError):
            bpm = read_f32(proc, offs.bpm[d])
    if offs.position:
        with contextlib.suppress(MemoryReadError):
            pos = read_i64(proc, offs.position[d])
    fader = None
    if offs.fader and d < len(offs.fader) and offs.fader[d] is not None:
        fader = read_fader(proc, offs.fader[d])  # type: ignore[arg-type]
    cid = track.content_id if track else None
    return DeckRead(
        key=cid or norm,
        cid=cid,
        title=title,
        bpm=bpm,
        pos=pos,
        fader=fader,
        unknown_path=norm is not None and track is None,
    )


class DeckWatcher:
    """Polls deck state; emits a deck-sourced PlayEvent per mix-in."""

    def __init__(
        self,
        db_map: Callable[[], dict[str, DbTrack]],
        *,
        proc_factory: Callable[[], MemoryReader] = WindowsProcess,
        version_fn: Callable[[], str | None] | None = None,
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        min_audible_s: float = 5.0,
    ) -> None:
        self._db_fn = db_map
        self._proc_factory = proc_factory
        self._version_fn = version_fn
        self._mono = mono
        self._wall = wall
        self._db: dict[str, DbTrack] | None = None
        self._proc: MemoryReader | None = None
        self._offs: DeckOffsets | None = None
        self._tracker = NowPlayingTracker(min_audible_s=min_audible_s)
        self._prev: dict[int, tuple[str | None, int | None]] = {}
        self._next_open = 0.0
        self._last_db_refresh = 0.0
        self._logged: set[str] = set()
        self.state = "off"

    def _log_once(self, key: str, msg: str, *args: object) -> None:
        if key not in self._logged:
            self._logged.add(key)
            logger.info(msg, *args)

    def _open(self, now: float) -> None:
        if now < self._next_open:
            return
        try:
            proc = self._proc_factory()
        except ProcessNotFoundError:
            self.state = "not running"
            self._next_open = now + REOPEN_S
            return
        except UnsupportedPlatform:
            self.state = "off"
            self._log_once(
                "unsupported", "deck reader: unsupported platform, disabled"
            )
            self._next_open = now + 3600
            return
        self._proc = proc
        version = proc.version
        if version is None and self._version_fn is not None:
            version = self._version_fn()
        offs = load_offsets(version or "")
        if offs is None or offs.anlz_path is None:
            self.state = "no offsets"
            self._log_once(
                "nooffs",
                "deck reader: no offsets for Rekordbox %s, "
                "using history only",
                version or "unknown",
            )
            self._offs = None
        else:
            self.state = f"active ({version})"
            self._log_once(
                "active", "deck reader: active (%s)", version or "unknown"
            )
            self._offs = offs

    def _refresh_db(self, now: float) -> bool:
        try:
            self._db = self._db_fn()
        except Exception:
            logger.exception("deck reader: db map refresh failed")
            return False
        self._last_db_refresh = now
        return True

    def poll(self) -> list[PlayEvent]:
        now = self._mono()
        if self._proc is None:
            self._open(now)
            if self._proc is None:
                return []
        offs = self._offs
        proc = self._proc
        if offs is None or offs.anlz_path is None or proc is None:
            return []
        if (
            self._db is None or now - self._last_db_refresh >= DB_REFRESH_S
        ) and not self._refresh_db(now) and self._db is None:
            return []
        assert self._db is not None

        samples: list[DeckSample] = []
        try:
            for d in range(len(offs.anlz_path)):
                r = read_deck(proc, offs, self._db, d)
                if r is None:
                    continue
                if (
                    r.unknown_path
                    and now - self._last_db_refresh >= DB_REFRESH_S
                    and self._refresh_db(now)
                ):
                    # newly imported track: refresh the map (bounded)
                    r = read_deck(proc, offs, self._db, d) or r
                pkey, ppos = self._prev.get(d, (None, None))
                playing = is_playing(pkey, ppos, r.key, r.pos)
                self._prev[d] = (r.key, r.pos)
                samples.append(
                    DeckSample(r.cid or r.key, r.title, playing, r.fader)
                )
        except MemoryReadError:
            # process gone / layout changed: reopen later
            with contextlib.suppress(Exception):
                proc.close()  # type: ignore[attr-defined]
            self._proc = None
            self._offs = None
            self._next_open = now + REOPEN_S
            self.state = "restarting"
            return []

        ev = self._tracker.update(now, self._wall(), samples)
        if ev is None:
            return []
        return [
            PlayEvent(
                history_entry_id="deck:" + uuid.uuid4().hex,
                history_id="deck",
                content_id=ev.cid,
                played_at=datetime.fromtimestamp(ev.wall_since, UTC),
                detected_at=datetime.now(UTC),
                source="deck",
                deck=ev.deck,
            )
        ]
