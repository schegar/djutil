"""Set management: recording lifecycle and Rekordbox history import."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .live import _as_dt


def _track_summary(conn: Connection, track_id: str | None) -> dict[str, Any] | None:
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


def _insert_transition(
    conn: Connection,
    *,
    from_track: str | None,
    to_track: str | None,
    set_id: int,
    from_entry: int | None,
    to_entry: int,
    played_at: Any,
) -> None:
    conn.execute(
        text(
            "INSERT INTO transitions (from_track_id, to_track_id, set_id,"
            " from_entry_id, to_entry_id, played_at, favorite) VALUES"
            " (:f, :t, :s, :fe, :te, :pa, 0)"
        ),
        {
            "f": from_track,
            "t": to_track,
            "s": set_id,
            "fe": from_entry,
            "te": to_entry,
            "pa": played_at,
        },
    )


def import_rb_history(
    conn: Connection, history_id: str
) -> dict[str, Any]:
    """Import one Rekordbox history session as a set. Idempotent."""
    existing = conn.execute(
        text("SELECT id FROM sets WHERE rb_history_id = :h"),
        {"h": history_id},
    ).scalar()
    if existing:
        return {
            "set_id": existing,
            "already_imported": True,
            "skipped": True,
            "history_id": history_id,
        }

    entries = conn.execute(
        text(
            "SELECT id, content_id, track_no, created_at FROM"
            " rb_history_entries WHERE history_id = :h"
            " ORDER BY track_no, created_at, id"
        ),
        {"h": history_id},
    ).mappings().all()
    if not entries:
        return {"skipped": True, "reason": "empty", "history_id": history_id}

    # Skip sessions already recorded live (entries already in set_entries).
    entry_ids = [e["id"] for e in entries]
    marks = ",".join(f"'{i}'" for i in entry_ids)
    live_dupes = conn.execute(
        text(
            f"SELECT COUNT(*) FROM set_entries WHERE rb_history_entry_id IN ({marks})"
        )
    ).scalar()
    if live_dupes:
        return {
            "skipped": True,
            "reason": "already_recorded_live",
            "history_id": history_id,
        }

    sess = conn.execute(
        text("SELECT name, date_created FROM rb_history_sessions WHERE id = :h"),
        {"h": history_id},
    ).mappings().first()
    name = (sess["name"] if sess else None) or f"RB import {history_id}"
    started = _as_dt(entries[0]["created_at"]) if entries[0]["created_at"] else datetime.now(UTC)
    last = entries[-1]["created_at"]
    ended = _as_dt(last) if last else started

    res = conn.execute(
        text(
            "INSERT INTO sets (name, started_at, ended_at, source,"
            " rb_history_id, auto) VALUES (:n, :s, :e, 'rb_import', :h, 0)"
        ),
        {"n": name, "s": started, "e": ended, "h": history_id},
    )
    set_id = int(res.lastrowid)

    prev_entry_id = None
    prev_track = None
    for pos, e in enumerate(entries, start=1):
        pa = _as_dt(e["created_at"]) if e["created_at"] else started
        r = conn.execute(
            text(
                "INSERT INTO set_entries (set_id, track_id, position,"
                " played_at, offset_seconds, rb_history_entry_id) VALUES"
                " (:s, :t, :p, :pa, :off, :rb)"
            ),
            {
                "s": set_id,
                "t": e["content_id"],
                "p": pos,
                "pa": pa,
                "off": int((pa - started).total_seconds()),
                "rb": e["id"],
            },
        )
        entry_id = int(r.lastrowid)
        if prev_entry_id is not None:
            _insert_transition(
                conn,
                from_track=prev_track,
                to_track=e["content_id"],
                set_id=set_id,
                from_entry=prev_entry_id,
                to_entry=entry_id,
                played_at=pa,
            )
        prev_entry_id, prev_track = entry_id, e["content_id"]

    return {"set_id": set_id, "history_id": history_id, "skipped": False}


def import_all_rb_histories(conn: Connection) -> dict[str, Any]:
    ids = [
        r[0]
        for r in conn.execute(
            text("SELECT id FROM rb_history_sessions WHERE is_folder = 0")
        ).all()
    ]
    results = [import_rb_history(conn, h) for h in ids]
    return {
        "imported": sum(1 for r in results if not r["skipped"]),
        "skipped_already_imported": sum(
            1 for r in results if r.get("already_imported")
        ),
        "skipped_already_live": sum(
            1 for r in results if r.get("reason") == "already_recorded_live"
        ),
        "results": results,
    }


def delete_set_entry(conn: Connection, set_id: int, entry_id: int) -> bool:
    """Delete an entry, drop its two transitions, bridge the neighbours.

    Bridging transition gets no annotations; everything else untouched.
    """
    entry = conn.execute(
        text(
            "SELECT id, position, track_id, played_at FROM set_entries"
            " WHERE id = :e AND set_id = :s"
        ),
        {"e": entry_id, "s": set_id},
    ).mappings().first()
    if not entry:
        return False

    prev = conn.execute(
        text(
            "SELECT id, track_id FROM set_entries WHERE set_id = :s"
            " AND position < :p ORDER BY position DESC LIMIT 1"
        ),
        {"s": set_id, "p": entry["position"]},
    ).mappings().first()
    nxt = conn.execute(
        text(
            "SELECT id, track_id, played_at FROM set_entries WHERE set_id = :s"
            " AND position > :p ORDER BY position LIMIT 1"
        ),
        {"s": set_id, "p": entry["position"]},
    ).mappings().first()

    conn.execute(
        text(
            "DELETE FROM transitions WHERE from_entry_id = :e OR to_entry_id = :e"
        ),
        {"e": entry_id},
    )
    conn.execute(
        text("DELETE FROM set_entries WHERE id = :e"), {"e": entry_id}
    )

    if prev and nxt:
        _insert_transition(
            conn,
            from_track=prev["track_id"],
            to_track=nxt["track_id"],
            set_id=set_id,
            from_entry=prev["id"],
            to_entry=nxt["id"],
            played_at=nxt["played_at"],
        )
    conn.execute(
        text(
            "UPDATE set_entries SET position = position - 1"
            " WHERE set_id = :s AND position > :p"
        ),
        {"s": set_id, "p": entry["position"]},
    )
    return True
