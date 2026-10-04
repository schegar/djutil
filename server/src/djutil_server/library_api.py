"""Read API for the single user (cookie auth)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .auth import require_user
from .deps import get_engine
from .schemas import (
    FacetItem,
    Facets,
    HistoryEntryOut,
    PlaylistNode,
    PlaylistRef,
    SessionDetail,
    SessionOut,
    Suggestion,
    TagNode,
    TrackDetail,
    TrackListResponse,
    TrackOut,
    TrackSummary,
)

router = APIRouter(prefix="/api", tags=["library"], dependencies=[Depends(require_user)])

_TRACK_COLS = (
    "t.id, t.title, t.mix, t.artist, t.original_artist, t.remixer, t.composer,"
    " t.album, t.genre, t.label, t.key_name, t.camelot, t.bpm, t.length_s,"
    " t.rating, t.color, t.comment, t.dj_play_count AS play_count,"
    " t.file_path, t.file_name, t.file_type, t.bitrate, t.sample_rate,"
    " t.release_year, t.release_date, t.date_added, t.artwork_hash,"
    " t.updated_at,"
    " (SELECT COUNT(*) FROM plays p WHERE p.track_id = t.id)"
    " AS app_play_count"
)

_SORTS = {
    "title": "title",
    "artist": "artist",
    "bpm": "bpm",
    "camelot": "camelot",
    "rating": "rating",
    "dj_play_count": "dj_play_count",
    "date_added": "date_added",
    "length_s": "length_s",
    "genre": "genre",
}

_FTS_TOKEN = re.compile(r"[\w#+]+", re.UNICODE)

# Streaming services seen in the wild have URI-ish file paths; local files
# have drive-letter or absolute paths. Order matters: service prefixes first.
_SOURCE_CASE = """CASE
 WHEN t.file_path LIKE 'spotify:%' THEN 'spotify'
 WHEN t.file_path LIKE 'tidal:%' THEN 'tidal'
 WHEN t.file_path LIKE 'soundcloud:%' THEN 'soundcloud'
 WHEN t.file_path LIKE 'beatport:%' THEN 'beatport'
 WHEN t.file_path GLOB '[a-zA-Z]:/*' OR t.file_path GLOB '[a-zA-Z]:\\\\*'
      OR t.file_path LIKE '/%' OR t.file_path LIKE '\\\\%'
      OR t.file_path IS NULL OR t.file_path = '' THEN 'local'
 WHEN t.file_path LIKE '%:%' THEN 'other_stream'
 ELSE 'local'
END"""

_SOURCES = ["local", "spotify", "tidal", "soundcloud", "beatport",
            "other_stream"]

_URI_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")


def _derive_source(file_path: str | None) -> str:
    if not file_path:
        return "local"
    m = _URI_RE.match(file_path)
    if not m:
        return "local"
    scheme = m.group(1).lower()
    if len(scheme) == 1:  # Windows drive letter, e.g. C:/
        return "local"
    if scheme in ("spotify", "tidal", "soundcloud", "beatport"):
        return scheme
    return "other_stream"


def _fts_query(q: str) -> str | None:
    """Turn free text into a safe FTS5 prefix-token query (no syntax errors)."""
    tokens = _FTS_TOKEN.findall(q)
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens)


def _track_out(row: dict[str, Any]) -> TrackOut:
    t = TrackOut.model_validate(row)
    if "source" not in row:
        t.source = _derive_source(row.get("file_path"))
    return t


@router.get("/tracks", response_model=TrackListResponse)
def list_tracks(
    q: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    camelot: str | None = None,
    genre: str | None = None,
    my_tag: str | None = None,
    playlist: str | None = None,
    rating_min: int | None = None,
    added_from: str | None = None,
    added_to: str | None = None,
    play_count_min: int | None = None,
    play_count_max: int | None = None,
    source: str | None = None,
    never_played: bool = False,
    include_deleted: bool = False,
    sort: str = Query("title", pattern="^(" + "|".join(_SORTS) + ")$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(50, le=500),
    offset: int = 0,
    engine: Engine = Depends(get_engine),
) -> TrackListResponse:
    where: list[str] = []
    params: dict[str, Any] = {}
    joins = ""

    if not include_deleted:
        where.append("t.deleted = 0")

    match = _fts_query(q) if q else None
    if match:
        joins += " JOIN tracks_fts f ON f.rowid = t.pk"
        where.append("tracks_fts MATCH :match")
        params["match"] = match
    if bpm_min is not None:
        where.append("t.bpm >= :bpm_min")
        params["bpm_min"] = bpm_min
    if bpm_max is not None:
        where.append("t.bpm <= :bpm_max")
        params["bpm_max"] = bpm_max
    for name, col, value in (
        ("camelot", "t.camelot", camelot),
        ("genre", "t.genre", genre),
    ):
        if value:
            items = [v.strip() for v in value.split(",") if v.strip()]
            if items:
                keys = ", ".join(f":{name}_{i}" for i in range(len(items)))
                where.append(f"{col} IN ({keys})")
                params.update({f"{name}_{i}": v for i, v in enumerate(items)})
    if my_tag:
        joins += (
            " JOIN track_my_tags mt ON mt.content_id = t.id"
            " AND mt.my_tag_id = :my_tag"
        )
        params["my_tag"] = my_tag
    if playlist:
        joins += (
            " JOIN playlist_entries pe ON pe.content_id = t.id"
            " AND pe.playlist_id = :playlist"
        )
        params["playlist"] = playlist
    if rating_min is not None:
        where.append("t.rating >= :rating_min")
        params["rating_min"] = rating_min
    if added_from:
        where.append("t.date_added >= :added_from")
        params["added_from"] = added_from
    if added_to:
        where.append("t.date_added <= :added_to")
        params["added_to"] = added_to
    if play_count_min is not None:
        where.append("t.dj_play_count >= :pc_min")
        params["pc_min"] = play_count_min
    if play_count_max is not None:
        where.append("t.dj_play_count <= :pc_max")
        params["pc_max"] = play_count_max
    if never_played:
        where.append("(t.dj_play_count IS NULL OR t.dj_play_count = 0)")
    if source:
        items = [v.strip() for v in source.split(",") if v.strip()]
        if items:
            keys = ", ".join(f":src_{i}" for i in range(len(items)))
            where.append(f"({_SOURCE_CASE}) IN ({keys})")
            params.update({f"src_{i}": v for i, v in enumerate(items)})

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM tracks t{joins}{where_sql}"

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(DISTINCT t.id) {base}"), params
        ).scalar() or 0
        order_sql = f"t.{_SORTS[sort]} {order.upper()}, t.id"
        if sort == "title":
            order_sql = (
                "CASE WHEN t.title IS NULL OR t.title = '' THEN 1 ELSE 0 END,"
                f" t.title {order.upper()}, t.id"
            )
        rows = conn.execute(
            text(
                f"SELECT DISTINCT {_TRACK_COLS} {base}"
                f" ORDER BY {order_sql}"
                f" LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": limit, "offset": offset},
        ).mappings().all()

    return TrackListResponse(
        items=[_track_out(dict(r)) for r in rows], total=int(total)
    )


@router.get("/tracks/{track_id}", response_model=TrackDetail)
def track_detail(
    track_id: str, engine: Engine = Depends(get_engine)
) -> TrackDetail:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(f"SELECT {_TRACK_COLS} FROM tracks t WHERE t.id = :id"),
                {"id": track_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Track not found")

        cues = conn.execute(
            text(
                "SELECT id, content_id, kind, in_ms, out_ms, color, comment"
                " FROM cues WHERE content_id = :id ORDER BY in_ms, id"
            ),
            {"id": track_id},
        ).mappings().all()
        tags = conn.execute(
            text(
                "SELECT m.id, m.name, m.parent_id FROM my_tags m"
                " JOIN track_my_tags tmt ON tmt.my_tag_id = m.id"
                " WHERE tmt.content_id = :id ORDER BY m.name"
            ),
            {"id": track_id},
        ).mappings().all()
        playlists = conn.execute(
            text(
                "SELECT p.id, p.name, p.parent_id, pe.track_no"
                " FROM playlist_entries pe JOIN playlists p"
                " ON p.id = pe.playlist_id WHERE pe.content_id = :id"
                " ORDER BY p.name"
            ),
            {"id": track_id},
        ).mappings().all()
        history = conn.execute(
            text(
                "SELECT e.id, e.history_id, e.content_id, e.track_no,"
                " e.created_at, h.name AS history_name,"
                " h.date_created AS history_date"
                " FROM rb_history_entries e"
                " JOIN rb_history_sessions h ON h.id = e.history_id"
                " WHERE e.content_id = :id ORDER BY e.created_at DESC"
            ),
            {"id": track_id},
        ).mappings().all()

        transitions_out = conn.execute(
            text(
                "SELECT to_track_id AS other_id, count, fav_count, avg_rating"
                " FROM transition_stats WHERE from_track_id = :id"
                " ORDER BY count DESC"
            ),
            {"id": track_id},
        ).mappings().all()
        transitions_in = conn.execute(
            text(
                "SELECT from_track_id AS other_id, count, fav_count, avg_rating"
                " FROM transition_stats WHERE to_track_id = :id"
                " ORDER BY count DESC"
            ),
            {"id": track_id},
        ).mappings().all()
        comments = {
            (r["from_track_id"], r["to_track_id"]): r["comment"]
            for r in conn.execute(
                text(
                    "SELECT from_track_id, to_track_id, comment FROM transitions"
                    " WHERE comment IS NOT NULL AND comment != ''"
                    " AND (from_track_id = :id OR to_track_id = :id)"
                    " ORDER BY played_at DESC"
                ),
                {"id": track_id},
            ).mappings().all()
        }
        track_sets = conn.execute(
            text(
                "SELECT DISTINCT s.id, s.name, s.started_at FROM sets s"
                " JOIN set_entries e ON e.set_id = s.id"
                " WHERE e.track_id = :id ORDER BY s.started_at DESC"
            ),
            {"id": track_id},
        ).mappings().all()

    from djutil_shared import Cue, MyTag

    from .schemas import SetRef, TransitionStatOut

    def _stat_out(rows: Any, key_from: bool) -> list[TransitionStatOut]:
        out = []
        for r in rows:
            other = conn_summary(engine, r["other_id"])
            pair = (track_id, r["other_id"]) if key_from else (r["other_id"], track_id)
            out.append(
                TransitionStatOut(
                    other_track=other,
                    count=r["count"],
                    fav_count=r["fav_count"],
                    avg_rating=r["avg_rating"],
                    last_comment=comments.get(pair),
                )
            )
        return out

    track = TrackDetail.model_validate(dict(row))
    track.cues = [Cue.model_validate(dict(c)) for c in cues]
    track.my_tags = [MyTag.model_validate(dict(t)) for t in tags]
    track.playlists = [PlaylistRef(**dict(p)) for p in playlists]
    track.history = [HistoryEntryOut(**dict(h)) for h in history]
    track.transitions_out = _stat_out(transitions_out, key_from=True)
    track.transitions_in = _stat_out(transitions_in, key_from=False)
    track.sets = [SetRef(**dict(s)) for s in track_sets]
    return track


def conn_summary(engine: Engine, track_id: str) -> TrackSummary | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, title, mix, artist, bpm, camelot, artwork_hash"
                " FROM tracks WHERE id = :id"
            ),
            {"id": track_id},
        ).mappings().first()
    return TrackSummary(**dict(row)) if row else None


@router.get("/tracks/{track_id}/compatible", response_model=list[Suggestion])
def compatible_tracks(
    track_id: str,
    limit: int = 50,
    engine: Engine = Depends(get_engine),
) -> list[dict[str, Any]]:
    from .services.suggest import suggestions_for

    with engine.connect() as conn:
        return suggestions_for(conn, track_id, limit=limit)


@router.get("/facets", response_model=Facets)
def facets(engine: Engine = Depends(get_engine)) -> Facets:
    with engine.connect() as conn:
        genres = conn.execute(
            text(
                "SELECT genre AS name, COUNT(*) AS count FROM tracks"
                " WHERE deleted = 0 AND genre IS NOT NULL AND genre != ''"
                " GROUP BY genre ORDER BY count DESC, name"
            )
        ).mappings().all()
        camelots = conn.execute(
            text(
                "SELECT camelot AS name, COUNT(*) AS count FROM tracks"
                " WHERE deleted = 0 AND camelot IS NOT NULL AND camelot != ''"
                " GROUP BY camelot ORDER BY name"
            )
        ).mappings().all()
        tags = conn.execute(
            text("SELECT id, name, parent_id FROM my_tags")
        ).mappings().all()
        playlists = conn.execute(
            text(
                "SELECT id, name, parent_id, is_folder, is_smart"
                " FROM playlists ORDER BY seq"
            )
        ).mappings().all()
        bpm = conn.execute(
            text(
                "SELECT MIN(bpm), MAX(bpm) FROM tracks WHERE deleted = 0"
            )
        ).first()
        sources = conn.execute(
            text(
                f"SELECT src AS name, COUNT(*) AS count FROM"
                f" (SELECT {_SOURCE_CASE} AS src FROM tracks t"
                f"  WHERE deleted = 0) GROUP BY src ORDER BY count DESC"
            )
        ).mappings().all()

    tag_nodes = {
        t["id"]: TagNode(id=t["id"], name=t["name"]) for t in tags
    }
    tag_roots: list[TagNode] = []
    for t in tags:
        node = tag_nodes[t["id"]]
        parent = t["parent_id"]
        if parent and parent in tag_nodes:
            tag_nodes[parent].children.append(node)
        else:
            tag_roots.append(node)

    pl_nodes = {
        p["id"]: PlaylistNode(
            id=p["id"],
            name=p["name"],
            is_folder=bool(p["is_folder"]),
            is_smart=bool(p["is_smart"]),
        )
        for p in playlists
    }
    pl_roots: list[PlaylistNode] = []
    for p in playlists:
        pl_node = pl_nodes[p["id"]]
        pl_parent = p["parent_id"]
        if pl_parent and pl_parent in pl_nodes:
            pl_nodes[pl_parent].children.append(pl_node)
        else:
            pl_roots.append(pl_node)

    return Facets(
        genres=[FacetItem(**dict(g)) for g in genres],
        camelots=[FacetItem(**dict(c)) for c in camelots],
        sources=[FacetItem(**dict(s)) for s in sources],
        my_tags=tag_roots,
        playlists=pl_roots,
        bpm_min=bpm[0] if bpm else None,
        bpm_max=bpm[1] if bpm else None,
    )


@router.get("/history/sessions", response_model=list[SessionOut])
def history_sessions(engine: Engine = Depends(get_engine)) -> list[SessionOut]:
    rows = (
        engine.connect()
        .execute(
            text(
                "SELECT h.id, h.name, h.date_created,"
                " (SELECT COUNT(*) FROM rb_history_entries e"
                "  WHERE e.history_id = h.id) AS entry_count"
                " FROM rb_history_sessions h"
                " WHERE h.is_folder = 0"
                " ORDER BY h.date_created DESC, h.id"
            )
        )
        .mappings()
        .all()
    )
    return [SessionOut(**dict(r)) for r in rows]


@router.get("/history/sessions/{session_id}", response_model=SessionDetail)
def history_session(
    session_id: str, engine: Engine = Depends(get_engine)
) -> SessionDetail:
    with engine.connect() as conn:
        sess = conn.execute(
            text(
                "SELECT id, name, date_created,"
                " (SELECT COUNT(*) FROM rb_history_entries e"
                "  WHERE e.history_id = rb_history_sessions.id)"
                " AS entry_count FROM rb_history_sessions WHERE id = :id"
            ),
            {"id": session_id},
        ).mappings().first()
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found")
        entries = conn.execute(
            text(
                "SELECT e.id, e.history_id, e.content_id, e.track_no,"
                " e.created_at, t.title, t.artist, t.mix, t.bpm, t.camelot"
                " FROM rb_history_entries e"
                " LEFT JOIN tracks t ON t.id = e.content_id"
                " WHERE e.history_id = :id ORDER BY e.track_no, e.id"
            ),
            {"id": session_id},
        ).mappings().all()

    out_entries = []
    for e in entries:
        d = dict(e)
        track = None
        if d.get("title") is not None or d.get("artist") is not None:
            track = TrackOut(
                id=d["content_id"],
                title=d.pop("title"),
                artist=d.pop("artist"),
                mix=d.pop("mix"),
                bpm=d.pop("bpm"),
                camelot=d.pop("camelot"),
            )
        else:
            for k in ("title", "artist", "mix", "bpm", "camelot"):
                d.pop(k, None)
        out_entries.append(HistoryEntryOut(**d, track=track))

    return SessionDetail(
        id=sess["id"],
        name=sess["name"],
        date_created=sess["date_created"],
        entry_count=sess["entry_count"],
        entries=out_entries,
    )


