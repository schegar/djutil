"""Read the Rekordbox master.db djmd* tables via raw SQL.

Uses plain ``sqlalchemy.text()`` queries so tests can pass any SQLite engine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from djutil_shared import (
    Album,
    Artist,
    Cue,
    Entity,
    Genre,
    HistoryEntry,
    HistorySession,
    Key,
    Label,
    LibrarySnapshot,
    MyTag,
    Playlist,
    PlaylistEntry,
    Track,
    TrackMyTag,
    to_camelot,
)

_TRACK_SQL = """
SELECT
    c.ID            AS id,
    c.Title         AS title,
    c.Subtitle      AS mix,
    c.ArtistID      AS artist_id,
    a.Name          AS artist,
    c.OrgArtistID   AS original_artist_id,
    oa.Name         AS original_artist,
    c.RemixerID     AS remixer_id,
    r.Name          AS remixer,
    c.ComposerID    AS composer_id,
    co.Name         AS composer,
    c.AlbumID       AS album_id,
    al.Name         AS album,
    c.GenreID       AS genre_id,
    g.Name          AS genre,
    c.LabelID       AS label_id,
    l.Name          AS label,
    c.KeyID         AS key_id,
    k.ScaleName     AS key_name,
    cc.Commnt       AS color,
    c.BPM           AS bpm_raw,
    c.Length        AS length_s,
    c.Rating        AS rating_raw,
    c.Commnt        AS comment,
    c.DJPlayCount   AS dj_play_count_raw,
    c.FolderPath    AS file_path,
    c.FileNameL     AS file_name,
    c.FileType      AS file_type,
    c.BitRate       AS bitrate,
    c.SampleRate    AS sample_rate,
    c.ReleaseYear   AS release_year,
    c.ReleaseDate   AS release_date,
    c.StockDate     AS stock_date,
    c.DateCreated   AS date_created,
    c.ImagePath     AS artwork_path,
    c.rb_local_usn  AS rb_local_usn,
    c.rb_local_deleted AS rb_local_deleted,
    c.updated_at    AS updated_at
FROM djmdContent c
LEFT JOIN djmdArtist a   ON a.ID  = c.ArtistID
LEFT JOIN djmdArtist oa  ON oa.ID = c.OrgArtistID
LEFT JOIN djmdArtist r   ON r.ID  = c.RemixerID
LEFT JOIN djmdArtist co  ON co.ID = c.ComposerID
LEFT JOIN djmdAlbum  al  ON al.ID = c.AlbumID
LEFT JOIN djmdGenre  g   ON g.ID  = c.GenreID
LEFT JOIN djmdLabel  l   ON l.ID  = c.LabelID
LEFT JOIN djmdKey    k   ON k.ID  = c.KeyID
LEFT JOIN djmdColor  cc  ON cc.ID = c.ColorID
"""


def parse_rb_datetime(value: Any) -> datetime | None:
    """Parse Rekordbox timestamps like ``2025-04-12 19:11:29.274 -05:00``."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    # "YYYY-MM-DD HH:MM:SS.SSS +HH:MM" -> "YYYY-MM-DDTHH:MM:SS.SSS+HH:MM"
    s = s.replace(" ", "T", 1).replace(" +", "+").replace(" -", "-")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.fromisoformat(s[:19])
        except ValueError:
            return None


def _norm_rating(value: Any) -> int | None:
    """Rekordbox stores star rating as 0-5; some DBs use the 0-255 scale."""
    if value is None:
        return None
    v = int(value)
    if v > 5:
        v = round(v / 51)
    return max(0, min(5, v))


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RekordboxReader:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._has_usn_cache: dict[Entity, bool] = {}

    def _rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params)
            return [dict(row._mapping) for row in result]

    # -- simple tables ------------------------------------------------------

    def artists(self) -> list[Artist]:
        return [
            Artist(id=r["ID"], name=r["Name"])
            for r in self._rows("SELECT ID, Name FROM djmdArtist ORDER BY Name")
        ]

    def albums(self) -> list[Album]:
        return [
            Album(id=r["ID"], name=r["Name"], artist_id=r["AlbumArtistID"])
            for r in self._rows("SELECT ID, Name, AlbumArtistID FROM djmdAlbum ORDER BY Name")
        ]

    def genres(self) -> list[Genre]:
        return [
            Genre(id=r["ID"], name=r["Name"])
            for r in self._rows("SELECT ID, Name FROM djmdGenre ORDER BY Name")
        ]

    def labels(self) -> list[Label]:
        return [
            Label(id=r["ID"], name=r["Name"])
            for r in self._rows("SELECT ID, Name FROM djmdLabel ORDER BY Name")
        ]

    def keys(self) -> list[Key]:
        return [
            Key(id=r["ID"], name=r["ScaleName"], camelot=to_camelot(r["ScaleName"]))
            for r in self._rows("SELECT ID, ScaleName FROM djmdKey ORDER BY Seq")
        ]

    def cues(self) -> list[Cue]:
        rows = self._rows(
            "SELECT ID, ContentID, Kind, InMsec, OutMsec, Color, Comment,"
            " rb_local_usn FROM djmdCue ORDER BY ContentID, InMsec"
        )
        return [self._cue(r) for r in rows]

    @staticmethod
    def _cue(r: dict[str, Any]) -> Cue:
        return Cue(
            id=r["ID"],
            content_id=r["ContentID"],
            kind=r["Kind"],
            in_ms=r["InMsec"],
            out_ms=r["OutMsec"],
            color=r["Color"],
            comment=r["Comment"],
            rb_local_usn=r.get("rb_local_usn"),
        )

    def my_tags(self) -> list[MyTag]:
        return [
            self._my_tag(r)
            for r in self._rows(
                "SELECT ID, Name, ParentID, rb_local_usn FROM djmdMyTag"
                " ORDER BY Seq"
            )
        ]

    @staticmethod
    def _my_tag(r: dict[str, Any]) -> MyTag:
        return MyTag(
            id=r["ID"],
            name=r["Name"],
            parent_id=r["ParentID"],
            rb_local_usn=r.get("rb_local_usn"),
        )

    def track_my_tags(self) -> list[TrackMyTag]:
        return [
            TrackMyTag(
                id=r["ID"],
                my_tag_id=r["MyTagID"],
                content_id=r["ContentID"],
                track_no=r["TrackNo"],
                rb_local_usn=r.get("rb_local_usn"),
            )
            for r in self._rows(
                "SELECT ID, MyTagID, ContentID, TrackNo, rb_local_usn"
                " FROM djmdSongMyTag"
            )
        ]

    def playlists(self) -> list[Playlist]:
        rows = self._rows(
            "SELECT ID, Name, ParentID, Attribute, Seq, rb_local_usn"
            " FROM djmdPlaylist ORDER BY Seq"
        )
        return [self._playlist(r) for r in rows]

    @staticmethod
    def _playlist(r: dict[str, Any]) -> Playlist:
        return Playlist(
            id=r["ID"],
            name=r["Name"],
            parent_id=r["ParentID"],
            is_folder=r["Attribute"] == 1,
            is_smart=r["Attribute"] == 4,
            seq=r["Seq"],
            rb_local_usn=r.get("rb_local_usn"),
        )

    def playlist_entries(self) -> list[PlaylistEntry]:
        return [
            PlaylistEntry(
                id=r["ID"],
                playlist_id=r["PlaylistID"],
                content_id=r["ContentID"],
                track_no=r["TrackNo"],
                rb_local_usn=r.get("rb_local_usn"),
            )
            for r in self._rows(
                "SELECT ID, PlaylistID, ContentID, TrackNo, rb_local_usn"
                " FROM djmdSongPlaylist ORDER BY PlaylistID, TrackNo"
            )
        ]

    def history_sessions(self) -> list[HistorySession]:
        rows = self._rows(
            "SELECT ID, Name, DateCreated, ParentID, Attribute, rb_local_usn"
            " FROM djmdHistory ORDER BY Seq"
        )
        return [self._history_session(r) for r in rows]

    @staticmethod
    def _history_session(r: dict[str, Any]) -> HistorySession:
        return HistorySession(
            id=r["ID"],
            name=r["Name"],
            date_created=r["DateCreated"],
            parent_id=r["ParentID"],
            is_folder=r["Attribute"] == 1,
            rb_local_usn=r.get("rb_local_usn"),
        )

    # -- tracks -------------------------------------------------------------

    def _track_from_row(self, r: dict[str, Any]) -> Track:
        bpm_raw = r["bpm_raw"]
        return Track(
            id=r["id"],
            title=r["title"],
            mix=r["mix"],
            artist_id=r["artist_id"],
            artist=r["artist"],
            original_artist_id=r["original_artist_id"],
            original_artist=r["original_artist"],
            remixer_id=r["remixer_id"],
            remixer=r["remixer"],
            composer_id=r["composer_id"],
            composer=r["composer"],
            album_id=r["album_id"],
            album=r["album"],
            genre_id=r["genre_id"],
            genre=r["genre"],
            label_id=r["label_id"],
            label=r["label"],
            key_id=r["key_id"],
            key_name=r["key_name"],
            camelot=to_camelot(r["key_name"]),
            bpm=bpm_raw / 100 if bpm_raw is not None else None,
            length_s=r["length_s"],
            rating=_norm_rating(r["rating_raw"]),
            color=r["color"],
            comment=r["comment"],
            dj_play_count=_int_or_none(r["dj_play_count_raw"]),
            file_path=r["file_path"],
            file_name=r["file_name"],
            file_type=r["file_type"],
            bitrate=r["bitrate"],
            sample_rate=r["sample_rate"],
            release_year=r["release_year"],
            release_date=r["release_date"],
            date_added=r["stock_date"] or r["date_created"],
            artwork_path=r["artwork_path"],
            rb_local_usn=r["rb_local_usn"],
            updated_at=parse_rb_datetime(r["updated_at"]),
            deleted=bool(r["rb_local_deleted"]),
        )

    def tracks(self, include_deleted: bool = False) -> list[Track]:
        sql = _TRACK_SQL
        if not include_deleted:
            sql += " WHERE c.rb_local_deleted = 0"
        sql += " ORDER BY c.Title"
        return [self._track_from_row(r) for r in self._rows(sql)]

    def track(self, content_id: str) -> Track | None:
        rows = self._rows(_TRACK_SQL + " WHERE c.ID = :cid", cid=str(content_id))
        return self._track_from_row(rows[0]) if rows else None

    # -- history entries ----------------------------------------------------

    def history_entries(self, since: str | None = None) -> list[HistoryEntry]:
        sql = (
            "SELECT ID, HistoryID, ContentID, TrackNo, created_at "
            "FROM djmdSongHistory"
        )
        params: dict[str, Any] = {}
        if since is not None:
            sql += " WHERE created_at > :since"
            params["since"] = since
        sql += " ORDER BY created_at, ID"
        return [
            HistoryEntry(
                id=r["ID"],
                history_id=r["HistoryID"],
                content_id=r["ContentID"],
                track_no=r["TrackNo"],
                created_at=parse_rb_datetime(r["created_at"]),
            )
            for r in self._rows(sql, **params)
        ]

    def latest_history_entry(self) -> HistoryEntry | None:
        rows = self._rows(
            "SELECT ID, HistoryID, ContentID, TrackNo, created_at "
            "FROM djmdSongHistory ORDER BY created_at DESC, ID DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return HistoryEntry(
            id=r["ID"],
            history_id=r["HistoryID"],
            content_id=r["ContentID"],
            track_no=r["TrackNo"],
            created_at=parse_rb_datetime(r["created_at"]),
        )

    # -- aggregates ----------------------------------------------------------

    def counts(self) -> dict[str, int]:
        def one(sql: str) -> int:
            with self.engine.connect() as conn:
                return int(conn.execute(text(sql)).scalar() or 0)

        return {
            "tracks": one(
                "SELECT COUNT(*) FROM djmdContent WHERE rb_local_deleted = 0"
            ),
            "artists": one("SELECT COUNT(*) FROM djmdArtist"),
            "albums": one("SELECT COUNT(*) FROM djmdAlbum"),
            "genres": one("SELECT COUNT(*) FROM djmdGenre"),
            "labels": one("SELECT COUNT(*) FROM djmdLabel"),
            "keys": one("SELECT COUNT(*) FROM djmdKey"),
            "cues": one("SELECT COUNT(*) FROM djmdCue"),
            "my_tags": one("SELECT COUNT(*) FROM djmdMyTag"),
            "playlists": one("SELECT COUNT(*) FROM djmdPlaylist"),
            "playlist_entries": one("SELECT COUNT(*) FROM djmdSongPlaylist"),
            "history_sessions": one("SELECT COUNT(*) FROM djmdHistory"),
            "history_entries": one("SELECT COUNT(*) FROM djmdSongHistory"),
        }

    def analysis_index(self) -> list[dict[str, Any]]:
        """ContentID, title, raw BPM and AnalysisDataPath for live tracks.

        Used by `decks scan`/`watch` to identify tracks loaded in Rekordbox
        decks by their in-memory ANLZ path.
        """
        return self._rows(
            "SELECT ID, Title, BPM, AnalysisDataPath FROM djmdContent"
            " WHERE rb_local_deleted = 0"
            " AND AnalysisDataPath IS NOT NULL AND AnalysisDataPath != ''"
        )

    # -- delta sync ----------------------------------------------------------

    @staticmethod
    def _alias(entity: Entity) -> str:
        return "c." if entity == "tracks" else ""

    _ENTITY_TABLE: dict[Entity, str] = {
        "tracks": "djmdContent",
        "cues": "djmdCue",
        "my_tags": "djmdMyTag",
        "track_my_tags": "djmdSongMyTag",
        "playlists": "djmdPlaylist",
        "playlist_entries": "djmdSongPlaylist",
        "history_sessions": "djmdHistory",
        "history_entries": "djmdSongHistory",
    }

    def ids(self, entity: Entity) -> list[str]:
        """IDs of all live (non-deleted) rows for ``entity``."""
        table = self._ENTITY_TABLE[entity]
        return [
            str(r["ID"])
            for r in self._rows(
                f"SELECT ID FROM {table} WHERE rb_local_deleted = 0"
            )
        ]

    def has_usn(self, entity: Entity) -> bool:
        """True if the entity's table actually populates rb_local_usn.

        The column exists on all djmd tables (StatsFull mixin) but some,
        e.g. djmdCue on RB7, leave it NULL for every row.
        """
        if entity not in self._has_usn_cache:
            table = self._ENTITY_TABLE[entity]
            row = self._rows(
                f"SELECT 1 AS x FROM {table} WHERE rb_local_usn IS NOT NULL LIMIT 1"
            )
            self._has_usn_cache[entity] = bool(row)
        return self._has_usn_cache[entity]

    def entity_delta(
        self, entity: Entity, since_usn: int | None
    ) -> tuple[list[BaseModel], list[str], int | None]:
        """Return ``(upserts, deleted_ids, max_usn)`` for ``entity``.

        All djmd tables expose ``rb_local_usn``/``rb_local_deleted``
        (StatsFull mixin in pyrekordbox), so every entity supports deltas.
        Rows with ``rb_local_usn > since_usn`` are returned; deleted ones go
        into ``deletes``. When ``since_usn`` is None all rows are returned
        and ``deletes`` is empty.
        """
        table = self._ENTITY_TABLE[entity]
        where = ""
        params: dict[str, Any] = {}
        if since_usn is not None:
            where = f"WHERE {self._alias(entity)}rb_local_usn > :usn"
            params["usn"] = since_usn

        if entity == "tracks":
            sql = _TRACK_SQL + f" {where} ORDER BY c.rb_local_usn"
            rows = self._rows(sql, **params)
            models: list[BaseModel] = [self._track_from_row(r) for r in rows]
        else:
            sql = f"SELECT * FROM {table} {where} ORDER BY rb_local_usn"
            rows = self._rows(sql, **params)
            models = [self._entity_model(entity, r) for r in rows]

        id_col = "id" if entity == "tracks" else "ID"
        live = [
            m for m, r in zip(models, rows, strict=True)
            if not r.get("rb_local_deleted")
        ]
        deleted = [str(r[id_col]) for r in rows if r.get("rb_local_deleted")]
        usns = [r["rb_local_usn"] for r in rows]
        max_usn = max([u for u in usns if u is not None], default=None)
        return live, deleted, max_usn

    def _entity_model(self, entity: Entity, r: dict[str, Any]) -> BaseModel:
        if entity == "cues":
            return self._cue(r)
        if entity == "my_tags":
            return self._my_tag(r)
        if entity == "track_my_tags":
            return TrackMyTag(
                id=r["ID"],
                my_tag_id=r["MyTagID"],
                content_id=r["ContentID"],
                track_no=r["TrackNo"],
                rb_local_usn=r.get("rb_local_usn"),
            )
        if entity == "playlists":
            return self._playlist(r)
        if entity == "playlist_entries":
            return PlaylistEntry(
                id=r["ID"],
                playlist_id=r["PlaylistID"],
                content_id=r["ContentID"],
                track_no=r["TrackNo"],
                rb_local_usn=r.get("rb_local_usn"),
            )
        if entity == "history_sessions":
            return self._history_session(r)
        if entity == "history_entries":
            return HistoryEntry(
                id=r["ID"],
                history_id=r["HistoryID"],
                content_id=r["ContentID"],
                track_no=r["TrackNo"],
                created_at=parse_rb_datetime(r["created_at"]),
                rb_local_usn=r.get("rb_local_usn"),
            )
        raise ValueError(entity)

    def snapshot(
        self,
        db_path: str | Path,
        rekordbox_version: str | None = None,
        include_deleted: bool = False,
    ) -> LibrarySnapshot:
        return LibrarySnapshot(
            exported_at=datetime.now(UTC),
            rekordbox_version=rekordbox_version,
            db_path=str(db_path),
            artists=self.artists(),
            albums=self.albums(),
            genres=self.genres(),
            labels=self.labels(),
            keys=self.keys(),
            tracks=self.tracks(include_deleted=include_deleted),
            cues=self.cues(),
            my_tags=self.my_tags(),
            track_my_tags=self.track_my_tags(),
            playlists=self.playlists(),
            playlist_entries=self.playlist_entries(),
            history_sessions=self.history_sessions(),
            history_entries=self.history_entries(),
        )
