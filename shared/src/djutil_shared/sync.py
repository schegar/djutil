"""Sync protocol models shared between the agent and the server."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .models import (
    Cue,
    HistoryEntry,
    HistorySession,
    MyTag,
    Playlist,
    PlaylistEntry,
    Track,
    TrackMyTag,
)

Entity = Literal[
    "tracks",
    "cues",
    "my_tags",
    "track_my_tags",
    "playlists",
    "playlist_entries",
    "history_sessions",
    "history_entries",
]

ENTITIES: tuple[Entity, ...] = (
    "tracks",
    "cues",
    "my_tags",
    "track_my_tags",
    "playlists",
    "playlist_entries",
    "history_sessions",
    "history_entries",
)

ENTITY_MODELS: dict[Entity, type[BaseModel]] = {
    "tracks": Track,
    "cues": Cue,
    "my_tags": MyTag,
    "track_my_tags": TrackMyTag,
    "playlists": Playlist,
    "playlist_entries": PlaylistEntry,
    "history_sessions": HistorySession,
    "history_entries": HistoryEntry,
}


class SyncBatch(BaseModel):
    entity: Entity
    upserts: list[dict[str, Any]] = Field(default_factory=list)
    deletes: list[str] = Field(default_factory=list)
    max_usn: int | None = None

    @model_validator(mode="after")
    def _validate_upserts(self) -> SyncBatch:
        model = ENTITY_MODELS[self.entity]
        self.upserts = [
            model.model_validate(u).model_dump(mode="json") for u in self.upserts
        ]
        return self


class BatchResult(BaseModel):
    entity: Entity
    upserted: int
    deleted: int


class IdSet(BaseModel):
    entity: Entity
    ids: list[str]


class IdSetResult(BaseModel):
    entity: Entity
    deleted: int


class SyncStateResponse(BaseModel):
    entities: dict[Entity, int | None]
