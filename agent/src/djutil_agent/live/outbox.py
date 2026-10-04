"""SQLite outbox for unacked play events."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from djutil_shared import PlayEvent


class Outbox:
    """Persists play events until the server acks them."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Constructed on the caller thread but used from the forwarder's
        # asyncio thread; access is serialized through that single loop.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS outbox ("
            " id TEXT PRIMARY KEY, payload TEXT NOT NULL,"
            " created_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def put(self, event: PlayEvent) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO outbox (id, payload, created_at)"
            " VALUES (?, ?, ?)",
            (
                event.history_entry_id,
                event.model_dump_json(),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()

    def pending(self) -> list[PlayEvent]:
        rows = self._conn.execute(
            "SELECT payload FROM outbox ORDER BY created_at, id"
        ).fetchall()
        return [PlayEvent.model_validate(json.loads(r[0])) for r in rows]

    def ack(self, history_entry_id: str) -> None:
        self._conn.execute(
            "DELETE FROM outbox WHERE id = ?", (history_entry_id,)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
