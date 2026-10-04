"""Pydantic models mirroring the Rekordbox master.db djmd* tables."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Artist(_Model):
    id: str
    name: str | None = None


class Album(_Model):
    id: str
    name: str | None = None
    artist_id: str | None = None


class Genre(_Model):
    id: str
    name: str | None = None


class Label(_Model):
    id: str
    name: str | None = None


class Key(_Model):
    id: str
    name: str | None = None
    camelot: str | None = None


class Track(_Model):
    id: str
    title: str | None = None
    mix: str | None = None  # djmdContent.Subtitle
    artist_id: str | None = None
    artist: str | None = None
    original_artist_id: str | None = None
    original_artist: str | None = None
    remixer_id: str | None = None
    remixer: str | None = None
    composer_id: str | None = None
    composer: str | None = None
    album_id: str | None = None
    album: str | None = None
    genre_id: str | None = None
    genre: str | None = None
    label_id: str | None = None
    label: str | None = None
    key_id: str | None = None
    key_name: str | None = None
    camelot: str | None = None
    bpm: float | None = None  # djmdContent.BPM is int x100
    length_s: int | None = None
    rating: int | None = None  # 0-5
    color: str | None = None
    comment: str | None = None  # djmdContent.Commnt
    dj_play_count: int | None = None
    file_path: str | None = None  # djmdContent.FolderPath
    file_name: str | None = None
    file_type: int | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    release_year: int | None = None
    release_date: str | None = None
    date_added: str | None = None  # StockDate
    artwork_path: str | None = None  # djmdContent.ImagePath
    artwork_hash: str | None = None  # sha256 of the artwork file, set on upload
    rb_local_usn: int | None = None
    updated_at: datetime | None = None
    deleted: bool = False  # rb_local_deleted


class Cue(_Model):
    id: str
    content_id: str
    # djmdCue.Kind: 0 = memory cue; >0 = hot cue / other types
    # (pyrekordbox docs list Load=3, Loop=4)
    kind: int | None = None
    in_ms: int | None = None
    out_ms: int | None = None
    color: int | None = None
    comment: str | None = None
    rb_local_usn: int | None = None


class MyTag(_Model):
    id: str
    name: str | None = None
    parent_id: str | None = None
    rb_local_usn: int | None = None


class TrackMyTag(_Model):
    id: str
    my_tag_id: str
    content_id: str
    track_no: int | None = None
    rb_local_usn: int | None = None


class Playlist(_Model):
    id: str
    name: str | None = None
    parent_id: str | None = None
    is_folder: bool = False  # Attribute == 1
    is_smart: bool = False  # Attribute == 4
    seq: int | None = None
    rb_local_usn: int | None = None


class PlaylistEntry(_Model):
    id: str
    playlist_id: str
    content_id: str
    track_no: int | None = None
    rb_local_usn: int | None = None


class HistorySession(_Model):
    id: str
    name: str | None = None
    date_created: str | None = None
    parent_id: str | None = None
    is_folder: bool = False  # Attribute == 1
    rb_local_usn: int | None = None


class HistoryEntry(_Model):
    id: str
    history_id: str
    content_id: str
    track_no: int | None = None
    created_at: datetime | None = None
    rb_local_usn: int | None = None


class LibrarySnapshot(_Model):
    exported_at: datetime
    rekordbox_version: str | None = None
    db_path: str
    artists: list[Artist] = []
    albums: list[Album] = []
    genres: list[Genre] = []
    labels: list[Label] = []
    keys: list[Key] = []
    tracks: list[Track] = []
    cues: list[Cue] = []
    my_tags: list[MyTag] = []
    track_my_tags: list[TrackMyTag] = []
    playlists: list[Playlist] = []
    playlist_entries: list[PlaylistEntry] = []
    history_sessions: list[HistorySession] = []
    history_entries: list[HistoryEntry] = []


class PlayEvent(_Model):
    history_entry_id: str
    history_id: str
    content_id: str
    played_at: datetime | None = None  # djmdSongHistory.created_at
    detected_at: datetime
    track: Track | None = None
