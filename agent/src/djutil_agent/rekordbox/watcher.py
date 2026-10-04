"""Poll djmdSongHistory for newly played tracks."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import sqlalchemy.exc

from djutil_shared import PlayEvent

from .reader import RekordboxReader, parse_rb_datetime

_LOCK_ERRORS = ("database is locked", "database table is locked")


class HistoryWatcher:
    """Emits a :class:`PlayEvent` for every new djmdSongHistory row.

    Tie handling: Rekordbox IDs are not sequential, so rows sharing the
    newest ``created_at`` are remembered by ID instead of relying on a
    ``(created_at, ID)`` ordering.
    """

    def __init__(self, reader: RekordboxReader) -> None:
        self.reader = reader
        self._last_created_at: str | None = None
        self._ids_at_last: set[str] = set()
        self._primed = False

    def prime(self) -> None:
        """Record the newest row without emitting anything."""
        latest = self.reader.latest_history_entry()
        self._ids_at_last = set()
        self._last_created_at = None
        if latest is not None:
            rows = self._history_rows()
            newest_ts = max((str(r["created_at"]) for r in rows), default=None)
            self._last_created_at = newest_ts
            self._ids_at_last = {
                str(r["ID"]) for r in rows if str(r["created_at"]) == newest_ts
            }
        self._primed = True

    def _history_rows(self) -> list[dict[str, object]]:
        with self.reader.engine.connect() as conn:
            from sqlalchemy import text

            sql = (
                "SELECT ID, HistoryID, ContentID, TrackNo, created_at "
                "FROM djmdSongHistory"
            )
            params: dict[str, object] = {}
            if self._last_created_at is not None:
                sql += " WHERE created_at >= :last"
                params["last"] = self._last_created_at
            result = conn.execute(text(sql), params)
            return [dict(r._mapping) for r in result]

    def poll(self) -> list[PlayEvent]:
        """Return events for history rows newer than the last seen one."""
        if not self._primed:
            self.prime()
        try:
            rows = self._history_rows()
        except (sqlite3.OperationalError, sqlalchemy.exc.OperationalError) as exc:
            if any(msg in str(exc) for msg in _LOCK_ERRORS):
                return []  # skip this cycle; retry next poll
            raise

        new: list[dict[str, object]] = []
        for r in rows:
            ts = str(r["created_at"])
            rid = str(r["ID"])
            if (
                self._last_created_at is None
                or ts > self._last_created_at
                or (ts == self._last_created_at and rid not in self._ids_at_last)
            ):
                new.append(r)

        new.sort(key=lambda r: (str(r["created_at"]), str(r["ID"])))
        if not new:
            return []

        detected = datetime.now(UTC)
        newest_ts = str(new[-1]["created_at"])
        if self._last_created_at is None or newest_ts > self._last_created_at:
            self._last_created_at = newest_ts
            self._ids_at_last = {
                str(r["ID"])
                for r in rows
                if str(r["created_at"]) == newest_ts
            }
        else:
            self._ids_at_last |= {str(r["ID"]) for r in new}

        events = []
        for r in new:
            events.append(
                PlayEvent(
                    history_entry_id=str(r["ID"]),
                    history_id=str(r["HistoryID"]),
                    content_id=str(r["ContentID"]),
                    played_at=parse_rb_datetime(r["created_at"]),
                    detected_at=detected,
                    track=self.reader.track(str(r["ContentID"])),
                )
            )
        return events
