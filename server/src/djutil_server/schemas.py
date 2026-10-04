"""API-specific response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from djutil_shared import Cue, MyTag, Playlist


class LoginRequest(BaseModel):
    password: str


class MeResponse(BaseModel):
    authenticated: bool


class TrackOut(BaseModel):
    id: str
    title: str | None = None
    mix: str | None = None
    artist: str | None = None
    original_artist: str | None = None
    remixer: str | None = None
    composer: str | None = None
    album: str | None = None
    genre: str | None = None
    label: str | None = None
    key_name: str | None = None
    camelot: str | None = None
    bpm: float | None = None
    length_s: int | None = None
    rating: int | None = None
    color: str | None = None
    comment: str | None = None
    play_count: int | None = None  # == dj_play_count for now
    file_path: str | None = None
    file_name: str | None = None
    file_type: int | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    release_year: int | None = None
    release_date: str | None = None
    date_added: str | None = None
    artwork_hash: str | None = None
    source: str = "local"
    app_play_count: int = 0
    updated_at: datetime | None = None


class TrackListResponse(BaseModel):
    items: list[TrackOut]
    total: int


class HistoryEntryOut(BaseModel):
    id: str
    history_id: str
    history_name: str | None = None
    history_date: str | None = None
    content_id: str
    track_no: int | None = None
    created_at: datetime | None = None
    track: TrackOut | None = None


class PlaylistRef(BaseModel):
    id: str
    name: str | None = None
    parent_id: str | None = None
    track_no: int | None = None


class TrackDetail(TrackOut):
    cues: list[Cue] = []
    my_tags: list[MyTag] = []
    playlists: list[PlaylistRef] = []
    history: list[HistoryEntryOut] = []
    transitions_out: list[TransitionStatOut] = []
    transitions_in: list[TransitionStatOut] = []
    sets: list[SetRef] = []


class FacetItem(BaseModel):
    id: str | None = None
    name: str | None = None
    count: int


class TagNode(BaseModel):
    id: str
    name: str | None = None
    children: list[TagNode] = []


class PlaylistNode(BaseModel):
    id: str
    name: str | None = None
    is_folder: bool = False
    is_smart: bool = False
    children: list[PlaylistNode] = []


class Facets(BaseModel):
    genres: list[FacetItem]
    camelots: list[FacetItem]
    sources: list[FacetItem] = []
    my_tags: list[TagNode]
    playlists: list[PlaylistNode]
    bpm_min: float | None = None
    bpm_max: float | None = None


class SessionOut(BaseModel):
    id: str
    name: str | None = None
    date_created: str | None = None
    entry_count: int


class SessionDetail(SessionOut):
    entries: list[HistoryEntryOut]


class SyncedPlaylist(Playlist):
    pass


# ---- live / sets / suggestions -------------------------------------------


class TrackSummary(BaseModel):
    id: str
    title: str | None = None
    mix: str | None = None
    artist: str | None = None
    bpm: float | None = None
    camelot: str | None = None
    artwork_hash: str | None = None


class Reason(BaseModel):
    kind: str
    label: str
    value: float | None = None


class Suggestion(BaseModel):
    track: TrackSummary
    score: float
    reasons: list[Reason]


class AgentStatus(BaseModel):
    connected: bool
    hostname: str | None = None
    rb_version: str | None = None
    last_seen: datetime | None = None


class SessionItem(BaseModel):
    track: TrackSummary | None
    played_at: datetime | None = None


class ActiveSet(BaseModel):
    id: int
    name: str | None = None
    started_at: datetime | None = None
    source: str | None = None
    auto: bool = False


class LiveState(BaseModel):
    agent: AgentStatus
    now_playing: TrackSummary | None = None
    now_playing_at: datetime | None = None
    session: list[SessionItem] = []
    active_set: ActiveSet | None = None
    auto_record: bool = True
    suggestions: list[Suggestion] = []


class SetOut(BaseModel):
    id: int
    name: str | None = None
    source: str | None = None
    rb_history_id: str | None = None
    auto: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    entry_count: int = 0
    duration_s: int | None = None
    fav_count: int = 0


class SetEntryOut(BaseModel):
    id: int
    position: int
    track_id: str | None = None
    played_at: datetime | None = None
    offset_seconds: int | None = None
    rb_history_entry_id: str | None = None
    track: TrackSummary | None = None


class TransitionOut(BaseModel):
    id: int
    from_track_id: str | None = None
    to_track_id: str | None = None
    from_entry_id: int | None = None
    to_entry_id: int | None = None
    played_at: datetime | None = None
    favorite: bool = False
    rating: int | None = None
    comment: str | None = None
    from_track: TrackSummary | None = None
    to_track: TrackSummary | None = None


class SetDetail(SetOut):
    rb_history_id: str | None = None
    notes: str | None = None
    entries: list[SetEntryOut] = []
    transitions: list[TransitionOut] = []


class SetStartRequest(BaseModel):
    name: str | None = None


class SetPatch(BaseModel):
    name: str | None = None
    notes: str | None = None


class TransitionPatch(BaseModel):
    favorite: bool | None = None
    rating: int | None = None
    comment: str | None = None


class AutoRecordOut(BaseModel):
    auto_record: bool


class ImportResult(BaseModel):
    set_id: int | None = None
    already_imported: bool = False
    skipped: bool = False
    reason: str | None = None
    history_id: str | None = None


class ImportAllResult(BaseModel):
    imported: int
    skipped_already_imported: int
    skipped_already_live: int
    results: list[ImportResult]


class TransitionStatOut(BaseModel):
    other_track: TrackSummary | None
    count: int
    fav_count: int
    avg_rating: float | None = None
    last_comment: str | None = None


class SetRef(BaseModel):
    id: int
    name: str | None = None
    started_at: datetime | None = None


TrackDetail.model_rebuild()
