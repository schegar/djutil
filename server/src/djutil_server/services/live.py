"""Live play ingestion, set recording, and the browser fan-out hub."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from djutil_shared import PlayEvent

# 30 min of silence ends an auto-recorded set / starts a new "session".
GAP = timedelta(minutes=30)
# Same track replayed within 90 s doesn't count as a new set entry.
DUP_WINDOW = timedelta(seconds=90)

# A "shadow" play is a deck event linked onto an already-ingested history
# play of the same track — it records the precise mix-in time/deck, but the
# history row already represents the play for counting/session purposes.
NOT_SHADOW = (
    "NOT (p.source = 'deck' AND p.rb_history_entry_id IS NOT NULL"
    " AND EXISTS (SELECT 1 FROM plays h"
    " WHERE h.history_entry_id = p.rb_history_entry_id))"
)

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class LiveHub:
    """In-process fan-out of LiveState to browser websockets."""

    sockets: set[Any] = field(default_factory=set)
    agent_connected: bool = False
    agent_hostname: str | None = None
    agent_rb_version: str | None = None
    agent_last_seen: datetime | None = None

    async def broadcast(self, payload: dict[str, Any]) -> None:
        msg = json.dumps(payload, default=str)
        for ws in list(self.sockets):
            try:
                # A dead/mid-close socket must not stall the publisher —
                # bound the send and drop the socket on any failure.
                await asyncio.wait_for(ws.send_text(msg), timeout=5)
            except Exception:
                self.sockets.discard(ws)


def _track_summary(track_id: str | None, conn: Connection) -> dict[str, Any] | None:
    if not track_id:
        return None
    row = conn.execute(
        text(
            "SELECT id, title, mix, artist, bpm, camelot, artwork_hash"
            " FROM tracks WHERE id = :id"
        ),
        {"id": track_id},
    ).mappings().first()
    return dict(row) if row else None


def _setting(conn: Connection, key: str, default: str) -> str:
    row = conn.execute(
        text("SELECT value FROM settings WHERE key = :k"), {"k": key}
    ).scalar()
    return row if row is not None else default


def set_setting(conn: Connection, key: str, value: str) -> None:
    conn.execute(
        text(
            "INSERT INTO settings (key, value) VALUES (:k, :v)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"k": key, "v": value},
    )


def auto_record_on(conn: Connection) -> bool:
    return _setting(conn, "auto_record", "1") == "1"


def active_set(conn: Connection) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT id, name, started_at, source, auto FROM sets"
            " WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        )
    ).mappings().first()
    return dict(row) if row else None


def _end_set(conn: Connection, set_id: int, ended_at: datetime) -> None:
    conn.execute(
        text("UPDATE sets SET ended_at = :e WHERE id = :id"),
        {"e": ended_at, "id": set_id},
    )


def _last_set_entry(conn: Connection, set_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT se.id, se.track_id, se.played_at, t.length_s"
            " FROM set_entries se LEFT JOIN tracks t ON t.id = se.track_id"
            " WHERE se.set_id = :id ORDER BY se.position DESC, se.id DESC"
            " LIMIT 1"
        ),
        {"id": set_id},
    ).mappings().first()
    return dict(row) if row else None


def _start_set(
    conn: Connection, name: str, started_at: datetime, auto: bool
) -> int:
    res = conn.execute(
        text(
            "INSERT INTO sets (name, started_at, source, auto)"
            " VALUES (:n, :s, 'live', :a)"
        ),
        {"n": name, "s": started_at, "a": auto},
    )
    return int(res.lastrowid)


def close_stale_set(conn: Connection, now: datetime) -> bool:
    """End an active set whose last entry is older than GAP. Returns changed."""
    s = active_set(conn)
    if not s:
        return False
    last = _last_set_entry(conn, s["id"])
    if not last or not last["played_at"]:
        return False
    played_at = _as_dt(last["played_at"])
    if now - played_at <= GAP:
        return False
    length = last.get("length_s") or 0
    ended = played_at + timedelta(seconds=length)
    _end_set(conn, s["id"], ended)
    return True


def _as_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _add_set_entry(
    conn: Connection,
    set_id: int,
    set_row: dict[str, Any],
    event: PlayEvent,
    play_row_id: int | None,
) -> dict[str, Any]:
    """Append a set entry + transition unless it's a <=90s same-track dup."""
    last = _last_set_entry(conn, set_id)
    played_at = _as_dt(event.played_at or event.detected_at)
    started = _as_dt(set_row["started_at"])
    if (
        last
        and last["track_id"] == event.content_id
        and played_at - _as_dt(last["played_at"]) <= DUP_WINDOW
    ):
        return {"added": False, "duplicate": True}

    pos = conn.execute(
        text("SELECT COALESCE(MAX(position), 0) + 1 FROM set_entries WHERE set_id = :s"),
        {"s": set_id},
    ).scalar()
    res = conn.execute(
        text(
            "INSERT INTO set_entries (set_id, track_id, position, played_at,"
            " offset_seconds, rb_history_entry_id) VALUES"
            " (:s, :t, :p, :pa, :off, :rb)"
        ),
        {
            "s": set_id,
            "t": event.content_id,
            "p": pos,
            "pa": played_at,
            "off": int((played_at - started).total_seconds()),
            "rb": event.history_entry_id,
        },
    )
    entry_id = int(res.lastrowid)
    if play_row_id is not None:
        conn.execute(
            text("UPDATE plays SET set_id = :s WHERE id = :p"),
            {"s": set_id, "p": play_row_id},
        )
    if last:
        conn.execute(
            text(
                "INSERT INTO transitions (from_track_id, to_track_id, set_id,"
                " from_entry_id, to_entry_id, played_at, favorite)"
                " VALUES (:f, :t, :s, :fe, :te, :pa, 0)"
            ),
            {
                "f": last["track_id"],
                "t": event.content_id,
                "s": set_id,
                "fe": last["id"],
                "te": entry_id,
                "pa": played_at,
            },
        )
    return {"added": True, "entry_id": entry_id}


def ingest_play(
    engine: Engine,
    hub: LiveHub,
    event: PlayEvent,
    *,
    clock: Clock = utcnow,
    set_name_fn: Callable[[datetime], str] | None = None,
) -> dict[str, Any]:
    """Record a live play. Idempotent on history_entry_id.

    Steps: upsert track if missing, upsert rb_history_entries, insert into
    plays, run set logic, return what changed for the publisher.
    """
    changed: dict[str, Any] = {"inserted": False, "set_changed": False}
    is_deck = event.source == "deck"
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT id, set_id FROM plays WHERE history_entry_id = :h"),
            {"h": event.history_entry_id},
        ).first()
        if existing:
            return changed
        if not is_deck:
            # a deck play already linked to this Rekordbox history row
            already = conn.execute(
                text(
                    "SELECT id FROM plays WHERE rb_history_entry_id = :h"
                ),
                {"h": event.history_entry_id},
            ).first()
            if already:
                return changed

        played_at = _as_dt(event.played_at or event.detected_at)
        now = clock()

        # Track upsert if missing (sync may lag the live event).
        if event.track is not None:
            t = event.track
            has = conn.execute(
                text("SELECT 1 FROM tracks WHERE id = :id"), {"id": t.id}
            ).scalar()
            if not has:
                cols = [
                    "id", "title", "mix", "artist", "original_artist",
                    "remixer", "composer", "album", "genre", "label",
                    "key_name", "camelot", "bpm", "length_s", "rating",
                    "comment", "dj_play_count", "file_path", "file_name",
                    "artwork_hash", "rb_local_usn", "updated_at", "deleted",
                    "synced_at",
                ]
                data = t.model_dump(mode="json")
                conn.execute(
                    text(
                        f"INSERT INTO tracks ({', '.join(cols)})"
                        f" VALUES ({', '.join(':' + c for c in cols)})"
                    ),
                    {**{c: data.get(c) for c in cols}, "synced_at": now},
                )

        if not is_deck:
            # Mirror the Rekordbox history row.
            conn.execute(
                text(
                    "INSERT INTO rb_history_entries (id, history_id,"
                    " content_id, track_no, created_at) VALUES"
                    " (:id, :h, :c, NULL, :ca) ON CONFLICT(id) DO NOTHING"
                ),
                {
                    "id": event.history_entry_id,
                    "h": event.history_id,
                    "c": event.content_id,
                    "ca": played_at,
                },
            )
            # Link to an unlinked deck play of the same track. Rekordbox
            # writes history rows late, so the deck event usually wins.
            deck_play = conn.execute(
                text(
                    "SELECT id FROM plays WHERE source = 'deck'"
                    " AND track_id = :t AND rb_history_entry_id IS NULL"
                    " AND played_at >= :lo AND played_at <= :hi"
                    " ORDER BY played_at DESC, id DESC LIMIT 1"
                ),
                {
                    "t": event.content_id,
                    "lo": played_at - timedelta(minutes=15),
                    "hi": played_at + timedelta(minutes=2),
                },
            ).first()
            if deck_play:
                conn.execute(
                    text(
                        "UPDATE plays SET rb_history_entry_id = :h"
                        " WHERE id = :p"
                    ),
                    {"h": event.history_entry_id, "p": deck_play.id},
                )
                changed["linked"] = True
                return changed
        else:
            # Link to an unlinked history play of the same track (the
            # deck event arrived after its history row was ingested).
            hp = conn.execute(
                text(
                    "SELECT p.id, p.history_entry_id, p.set_id FROM plays p"
                    " WHERE p.source = 'history' AND p.track_id = :t"
                    " AND p.played_at >= :lo AND p.played_at <= :hi"
                    " AND NOT EXISTS (SELECT 1 FROM plays d"
                    "  WHERE d.rb_history_entry_id = p.history_entry_id)"
                    " ORDER BY p.played_at DESC, p.id DESC LIMIT 1"
                ),
                {
                    "t": event.content_id,
                    "lo": played_at - timedelta(minutes=15),
                    "hi": played_at + timedelta(minutes=15),
                },
            ).first()
            if hp:
                conn.execute(
                    text(
                        "INSERT INTO plays (history_entry_id, track_id,"
                        " history_id, played_at, detected_at, set_id,"
                        " source, deck, rb_history_entry_id) VALUES"
                        " (:h, :t, :hs, :pa, :da, :sid, 'deck', :d, :rb)"
                    ),
                    {
                        "h": event.history_entry_id,
                        "t": event.content_id,
                        "hs": event.history_id,
                        "pa": played_at,
                        "da": _as_dt(event.detected_at),
                        "sid": hp.set_id,
                        "d": event.deck,
                        "rb": hp.history_entry_id,
                    },
                )
                changed["inserted"] = True
                changed["linked"] = True
                return changed

        # Close a stale set before deciding where this play lands. The gap is
        # measured against the play's own timestamp; the background sweeper
        # does the same check against wall-clock time.
        if close_stale_set(conn, played_at):
            changed["set_changed"] = True

        s = active_set(conn)
        if s is None and auto_record_on(conn):
            name_fn = set_name_fn or (
                lambda d: f"Set {d.strftime('%Y-%m-%d %H:%M')}"
            )
            _start_set(conn, name_fn(now), played_at, auto=True)
            s = active_set(conn)
            changed["set_changed"] = True

        res = conn.execute(
            text(
                "INSERT INTO plays (history_entry_id, track_id, history_id,"
                " played_at, detected_at, set_id, source, deck) VALUES"
                " (:h, :t, :hs, :pa, :da, :sid, :src, :d)"
            ),
            {
                "h": event.history_entry_id,
                "t": event.content_id,
                "hs": event.history_id,
                "pa": played_at,
                "da": _as_dt(event.detected_at),
                "sid": s["id"] if s else None,
                "src": event.source,
                "d": event.deck,
            },
        )
        if s:
            _add_set_entry(conn, s["id"], s, event, int(res.lastrowid))
        changed["inserted"] = True
    return changed


def live_state(engine: Engine, hub: LiveHub) -> dict[str, Any]:
    """Full LiveState for browser WS / REST."""
    from ..services.suggest import suggestions_for  # avoid cycle

    with engine.connect() as conn:
        s = active_set(conn)
        if s:
            rows = conn.execute(
                text(
                    "SELECT se.track_id, se.played_at FROM set_entries se"
                    " WHERE se.set_id = :id ORDER BY se.position DESC"
                ),
                {"id": s["id"]},
            ).mappings().all()
        else:
            # plays since the last >30min gap
            rows = conn.execute(
                text(
                    "SELECT track_id, played_at FROM plays p WHERE "
                    + NOT_SHADOW
                    + " ORDER BY played_at DESC, id DESC LIMIT 200"
                )
            ).mappings().all()
            session_rows = []
            prev = None
            for r in rows:
                pa = _as_dt(r["played_at"])
                if prev is not None and prev - pa > GAP:
                    break
                session_rows.append(r)
                prev = pa
            rows = session_rows

        session = [
            {"track": _track_summary(r["track_id"], conn), "played_at": r["played_at"]}
            for r in rows
        ]
        now_playing = session[0] if session else None
        session_track_ids = {
            r["track_id"] for r in rows if r["track_id"]
        }
        suggestions = (
            suggestions_for(
                conn,
                now_playing["track"]["id"],
                limit=20,
                exclude_ids=session_track_ids,
            )
            if now_playing and now_playing["track"]
            else []
        )

        return {
            "agent": {
                "connected": hub.agent_connected,
                "hostname": hub.agent_hostname,
                "rb_version": hub.agent_rb_version,
                "last_seen": hub.agent_last_seen,
            },
            "now_playing": now_playing["track"] if now_playing else None,
            "now_playing_at": now_playing["played_at"] if now_playing else None,
            "session": session,
            "active_set": s,
            "auto_record": auto_record_on(conn),
            "suggestions": suggestions,
        }


def session_gap_seconds() -> float:
    return GAP.total_seconds()
