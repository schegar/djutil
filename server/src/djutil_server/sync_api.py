"""Sync endpoints (agent token required) + artwork storage."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine

from djutil_shared import (
    ENTITIES,
    ENTITY_MODELS,
    BatchResult,
    Entity,
    IdSet,
    IdSetResult,
    SyncBatch,
    SyncStateResponse,
)

from .auth import require_agent, require_user
from .config import Settings
from .deps import get_engine

router = APIRouter(prefix="/api", tags=["sync"])

ENTITY_TABLES: dict[Entity, str] = {
    "tracks": "tracks",
    "cues": "cues",
    "my_tags": "my_tags",
    "track_my_tags": "track_my_tags",
    "playlists": "playlists",
    "playlist_entries": "playlist_entries",
    "history_sessions": "rb_history_sessions",
    "history_entries": "rb_history_entries",
}

# Columns each entity table accepts from an upsert payload.
ENTITY_COLUMNS: dict[Entity, list[str]] = {
    "tracks": [
        "id", "title", "mix", "artist_id", "artist", "original_artist_id",
        "original_artist", "remixer_id", "remixer", "composer_id", "composer",
        "album_id", "album", "genre_id", "genre", "label_id", "label",
        "key_id", "key_name", "camelot", "bpm", "length_s", "rating", "color",
        "comment", "dj_play_count", "file_path", "file_name", "file_type",
        "bitrate", "sample_rate", "release_year", "release_date", "date_added",
        "artwork_path", "artwork_hash", "rb_local_usn", "updated_at",
        "deleted",
    ],
    "cues": ["id", "content_id", "kind", "in_ms", "out_ms", "color", "comment",
             "rb_local_usn"],
    "my_tags": ["id", "name", "parent_id", "rb_local_usn"],
    "track_my_tags": ["id", "my_tag_id", "content_id", "track_no",
                      "rb_local_usn"],
    "playlists": ["id", "name", "parent_id", "is_folder", "is_smart", "seq",
                  "rb_local_usn"],
    "playlist_entries": ["id", "playlist_id", "content_id", "track_no",
                         "rb_local_usn"],
    "history_sessions": ["id", "name", "date_created", "parent_id",
                         "is_folder", "rb_local_usn"],
    "history_entries": ["id", "history_id", "content_id", "track_no",
                        "created_at", "rb_local_usn"],
}

MAX_ARTWORK_BYTES = 5 * 1024 * 1024


def _get_state(engine: Engine) -> dict[Entity, int | None]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT entity, last_usn FROM sync_state")
        ).all()
    state: dict[Entity, int | None] = {e: None for e in ENTITIES}
    state.update({r[0]: r[1] for r in rows})
    return state


@router.get("/sync/state", response_model=SyncStateResponse)
def sync_state(
    engine: Engine = Depends(get_engine), _: bool = Depends(require_agent)
) -> SyncStateResponse:
    return SyncStateResponse(entities=_get_state(engine))


@router.post("/sync/batch", response_model=BatchResult)
def sync_batch(
    batch: SyncBatch,
    engine: Engine = Depends(get_engine),
    _: bool = Depends(require_agent),
) -> BatchResult:
    entity = batch.entity
    table = ENTITY_TABLES[entity]
    columns = ENTITY_COLUMNS[entity]
    model = ENTITY_MODELS[entity]

    rows = []
    for raw in batch.upserts:
        data = model.model_validate(raw).model_dump(mode="json")
        rows.append({c: data.get(c) for c in columns})

    now = datetime.now(UTC)
    upserted = deleted = 0
    with engine.begin() as conn:
        if rows:
            extra_cols = ["synced_at"] if entity == "tracks" else []
            all_cols = columns + extra_cols
            col_list = ", ".join(all_cols)
            updates = ", ".join(
                f"{c} = excluded.{c}" for c in all_cols if c != "id"
            )
            stmt = text(
                f"INSERT INTO {table} ({col_list}) "
                f"VALUES ({', '.join(':' + c for c in all_cols)}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}"
            )
            for row in rows:
                if entity == "tracks":
                    row["synced_at"] = now
                    # Soft-delete flag from the model is authoritative.
                conn.execute(stmt, row)
                upserted += 1

        if batch.deletes:
            if entity == "tracks":
                stmt = text("UPDATE tracks SET deleted = 1 WHERE id = :id")
            else:
                stmt = text(f"DELETE FROM {table} WHERE id = :id")
            for row_id in batch.deletes:
                conn.execute(stmt, {"id": row_id})
                deleted += 1

        if batch.max_usn is not None:
            conn.execute(
                text(
                    "INSERT INTO sync_state (entity, last_usn, updated_at) "
                    "VALUES (:e, :usn, :t) ON CONFLICT(entity) DO UPDATE SET "
                    "last_usn = MAX(sync_state.last_usn, excluded.last_usn), "
                    "updated_at = excluded.updated_at"
                ),
                {"e": entity, "usn": batch.max_usn, "t": now},
            )
    return BatchResult(entity=entity, upserted=upserted, deleted=deleted)


@router.post("/sync/ids", response_model=IdSetResult)
def sync_ids(
    idset: IdSet,
    engine: Engine = Depends(get_engine),
    _: bool = Depends(require_agent),
) -> IdSetResult:
    table = ENTITY_TABLES[idset.entity]
    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text(f"SELECT id FROM {table}"))}
        missing = existing - set(idset.ids)
        deleted = 0
        if idset.entity == "tracks":
            stmt = text("UPDATE tracks SET deleted = 1 WHERE id = :id")
        else:
            stmt = text(f"DELETE FROM {table} WHERE id = :id")
        for row_id in missing:
            conn.execute(stmt, {"id": row_id})
            deleted += 1
    return IdSetResult(entity=idset.entity, deleted=deleted)


# -- artwork ---------------------------------------------------------------


def _artwork_path(settings: Settings, sha256: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise HTTPException(status_code=400, detail="Invalid sha256")
    return str(Path(settings.artwork_dir) / sha256.lower())


@router.head("/artwork/{sha256}")
def artwork_head(
    sha256: str,
    request: Request,
    _: bool = Depends(require_agent),
) -> Response:
    path = _artwork_path(request.app.state.settings, sha256)
    if Path(path).exists():
        return Response(status_code=200)
    raise HTTPException(status_code=404)


@router.put("/artwork/{sha256}")
async def artwork_put(
    sha256: str,
    request: Request,
    _: bool = Depends(require_agent),
) -> Response:
    body = await request.body()
    if len(body) > MAX_ARTWORK_BYTES:
        raise HTTPException(status_code=413, detail="Artwork too large")
    digest = hashlib.sha256(body).hexdigest()
    if digest != sha256.lower():
        raise HTTPException(status_code=400, detail="Hash mismatch")
    path = _artwork_path(request.app.state.settings, sha256)
    Path(path).write_bytes(body)
    return Response(status_code=201)


@router.get("/artwork/{sha256}")
def artwork_get(
    sha256: str,
    request: Request,
    _: bool = Depends(require_user),
) -> FileResponse:
    path = _artwork_path(request.app.state.settings, sha256)
    if not Path(path).exists():
        raise HTTPException(status_code=404)
    return FileResponse(
        path, headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )
