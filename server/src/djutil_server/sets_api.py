"""Sets and transitions API (user cookie)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .auth import require_user
from .deps import get_engine
from .live_api import publish_live_state
from .schemas import (
    ImportAllResult,
    ImportResult,
    SetDetail,
    SetEntryOut,
    SetOut,
    SetPatch,
    SetStartRequest,
    TrackSummary,
    TransitionOut,
    TransitionPatch,
)
from .services import sets as sets_svc

router = APIRouter(prefix="/api", tags=["sets"], dependencies=[Depends(require_user)])


def _set_name(now: datetime, tz_name: str) -> str:
    from zoneinfo import ZoneInfo

    try:
        local = now.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = now
    return f"Set {local.strftime('%Y-%m-%d %H:%M')}"


def _summary(conn: Any, tid: str | None) -> TrackSummary | None:
    if not tid:
        return None
    row = conn.execute(
        text(
            "SELECT id, title, mix, artist, bpm, camelot, artwork_hash"
            " FROM tracks WHERE id = :id"
        ),
        {"id": tid},
    ).mappings().first()
    return TrackSummary(**dict(row)) if row else None


def _set_row_to_out(row: dict[str, Any]) -> SetOut:
    return SetOut.model_validate(row)


@router.get("/sets", response_model=list[SetOut])
def list_sets(engine: Engine = Depends(get_engine)) -> list[SetOut]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT s.id, s.name, s.source, s.auto, s.started_at, s.ended_at,"
                " s.rb_history_id,"
                " (SELECT COUNT(*) FROM set_entries e WHERE e.set_id = s.id)"
                " AS entry_count,"
                " (SELECT MAX(offset_seconds) FROM set_entries e"
                "  WHERE e.set_id = s.id) AS duration_s,"
                " (SELECT COUNT(*) FROM transitions t WHERE t.set_id = s.id"
                "  AND t.favorite) AS fav_count"
                " FROM sets s ORDER BY s.started_at DESC, s.id DESC"
            )
        ).mappings().all()
    return [_set_row_to_out(dict(r)) for r in rows]


@router.post("/sets/start", response_model=SetOut, status_code=201)
async def start_set(
    body: SetStartRequest, request: Request, engine: Engine = Depends(get_engine)
) -> SetOut:
    settings = request.app.state.settings
    with engine.begin() as conn:
        active = conn.execute(
            text("SELECT id FROM sets WHERE ended_at IS NULL")
        ).scalar()
        if active:
            raise HTTPException(status_code=409, detail="A set is already active")
        now = datetime.now(UTC)
        name = body.name or _set_name(now, getattr(settings, "tz", "UTC"))
        res = conn.execute(
            text(
                "INSERT INTO sets (name, started_at, source, auto)"
                " VALUES (:n, :s, 'live', 0)"
            ),
            {"n": name, "s": now},
        )
        sid = int(res.lastrowid)
    out = get_set(sid, engine)
    await publish_live_state(request.app)
    return out


@router.post("/sets/{set_id}/stop", response_model=SetOut)
async def stop_set(
    set_id: int, request: Request, engine: Engine = Depends(get_engine)
) -> SetOut:
    with engine.begin() as conn:
        s = conn.execute(
            text("SELECT id, ended_at FROM sets WHERE id = :id"), {"id": set_id}
        ).mappings().first()
        if not s:
            raise HTTPException(404, "Set not found")
        if s["ended_at"] is None:
            conn.execute(
                text("UPDATE sets SET ended_at = :e WHERE id = :id"),
                {"e": datetime.now(UTC), "id": set_id},
            )
    out = get_set(set_id, engine)
    await publish_live_state(request.app)
    return out


@router.get("/sets/{set_id}", response_model=SetDetail)
def get_set(set_id: int, engine: Engine = Depends(get_engine)) -> SetDetail:
    with engine.connect() as conn:
        s = conn.execute(
            text("SELECT * FROM sets WHERE id = :id"), {"id": set_id}
        ).mappings().first()
        if not s:
            raise HTTPException(404, "Set not found")
        entries = conn.execute(
            text(
                "SELECT * FROM set_entries WHERE set_id = :id"
                " ORDER BY position"
            ),
            {"id": set_id},
        ).mappings().all()
        transitions = conn.execute(
            text(
                "SELECT * FROM transitions WHERE set_id = :id ORDER BY played_at, id"
            ),
            {"id": set_id},
        ).mappings().all()
        counts = conn.execute(
            text(
                "SELECT MAX(offset_seconds) FROM set_entries WHERE set_id = :id"
            ),
            {"id": set_id},
        ).scalar()
        fav = conn.execute(
            text(
                "SELECT COUNT(*) FROM transitions WHERE set_id = :id AND favorite"
            ),
            {"id": set_id},
        ).scalar()
        entry_out = [
            SetEntryOut(
                **{k: e.get(k) for k in (  # type: ignore[arg-type]
                    "id", "position", "track_id", "played_at",
                    "offset_seconds", "rb_history_entry_id"
                )},
                track=_summary(conn, e["track_id"]),
            )
            for e in entries
        ]
        transition_out = [
            TransitionOut(
                **{k: t.get(k) for k in (  # type: ignore[arg-type]
                    "id", "from_track_id", "to_track_id", "from_entry_id",
                    "to_entry_id", "played_at", "favorite", "rating", "comment"
                )},
                from_track=_summary(conn, t["from_track_id"]),
                to_track=_summary(conn, t["to_track_id"]),
            )
            for t in transitions
        ]

    return SetDetail(
        **{k: s.get(k) for k in (  # type: ignore[arg-type]
            "id", "name", "source", "auto", "started_at", "ended_at",
            "rb_history_id", "notes"
        )},
        entry_count=len(entries),
        duration_s=counts,
        fav_count=int(fav or 0),
        entries=entry_out,
        transitions=transition_out,
    )


@router.patch("/sets/{set_id}", response_model=SetDetail)
def patch_set(
    set_id: int, body: SetPatch, engine: Engine = Depends(get_engine)
) -> SetDetail:
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM sets WHERE id = :id"), {"id": set_id}
        ).scalar()
        if not exists:
            raise HTTPException(404, "Set not found")
        if body.name is not None:
            conn.execute(
                text("UPDATE sets SET name = :v WHERE id = :id"),
                {"v": body.name, "id": set_id},
            )
        if body.notes is not None:
            conn.execute(
                text("UPDATE sets SET notes = :v WHERE id = :id"),
                {"v": body.notes, "id": set_id},
            )
    return get_set(set_id, engine)


@router.delete("/sets/{set_id}", status_code=204)
def delete_set(set_id: int, engine: Engine = Depends(get_engine)) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM transitions WHERE set_id = :id"), {"id": set_id}
        )
        res = conn.execute(
            text("DELETE FROM sets WHERE id = :id"), {"id": set_id}
        )
        if res.rowcount == 0:
            raise HTTPException(404, "Set not found")


@router.delete("/sets/{set_id}/entries/{entry_id}", status_code=204)
def delete_entry(
    set_id: int, entry_id: int, engine: Engine = Depends(get_engine)
) -> None:
    with engine.begin() as conn:
        if not sets_svc.delete_set_entry(conn, set_id, entry_id):
            raise HTTPException(404, "Entry not found")


@router.patch("/transitions/{transition_id}", response_model=TransitionOut)
def patch_transition(
    transition_id: int, body: TransitionPatch, engine: Engine = Depends(get_engine)
) -> TransitionOut:
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(422, "rating must be 1-5 or null")
    with engine.begin() as conn:
        t = conn.execute(
            text("SELECT * FROM transitions WHERE id = :id"),
            {"id": transition_id},
        ).mappings().first()
        if not t:
            raise HTTPException(404, "Transition not found")
        # apply only explicitly-set fields
        data = body.model_dump(exclude_unset=True)
        for col, v in data.items():
            conn.execute(
                text(f"UPDATE transitions SET {col} = :v WHERE id = :id"),
                {"v": v, "id": transition_id},
            )
        row = conn.execute(
            text("SELECT * FROM transitions WHERE id = :id"),
            {"id": transition_id},
        ).mappings().first()
    assert row is not None
    return TransitionOut.model_validate(dict(row))


@router.post("/sets/import-rb/{history_id}", response_model=ImportResult)
def import_rb(
    history_id: str, engine: Engine = Depends(get_engine)
) -> ImportResult:
    with engine.begin() as conn:
        r = sets_svc.import_rb_history(conn, history_id)
    if r.get("reason") == "already_recorded_live":
        raise HTTPException(409, "already_recorded_live")
    return ImportResult(**r)


@router.post("/sets/import-rb", response_model=ImportAllResult)
def import_rb_all(engine: Engine = Depends(get_engine)) -> ImportAllResult:
    with engine.begin() as conn:
        r = sets_svc.import_all_rb_histories(conn)
    return ImportAllResult(**r)
