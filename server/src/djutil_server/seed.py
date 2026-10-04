"""Deterministic demo data for dev, Playwright and screenshots."""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from .config import get_settings
from .db import make_engine, run_migrations

_GENRES = ["House", "Techno", "Drum & Bass", "Trance", "Disco", "UK Garage"]
_LABELS = ["Anjunadeep", "Drumcode", "Defected", "Innervisions", "Hospital"]
_ARTISTS = ["Alpha Wave", "Beat Mechanic", "Cirrus", "Deep Vector",
            "Echo Park", "Future Funk", "Grey Skies", "Halcyon",
            "Ion Drive", "Juno Rise", "Kinetic Flux", "Lunar Tides"]
_CAMELOTS = [f"{i}{a}" for i in range(1, 13) for a in ("A", "B")]


def seed_demo(n_tracks: int, force: bool = False) -> None:
    settings = get_settings()
    engine = make_engine(settings.db_path)
    run_migrations(engine)

    rng = random.Random(42)
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM tracks")).scalar()
        if count and not force:
            sys.exit(
                f"tracks table is not empty ({count} rows); "
                "pass --force to seed anyway"
            )

        now = datetime.now(UTC)
        for i in range(n_tracks):
            title = f"Track {i + 1:04d}"
            conn.execute(
                text(
                    "INSERT INTO tracks (id, title, mix, artist, remixer,"
                    " album, genre, label, key_name, camelot, bpm, length_s,"
                    " rating, comment, dj_play_count, file_path, file_name,"
                    " file_type, bitrate, sample_rate, release_year,"
                    " release_date, date_added, rb_local_usn, updated_at,"
                    " deleted, synced_at) VALUES"
                    " (:id,:title,:mix,:artist,:remixer,:album,:genre,:label,"
                    " :key_name,:camelot,:bpm,:length_s,:rating,:comment,"
                    " :dj_play_count,:file_path,:file_name,:file_type,:bitrate,"
                    " :sample_rate,:release_year,:release_date,:date_added,"
                    " :usn,:updated_at,0,:synced_at)"
                ),
                {
                    "id": f"demo-{i + 1:05d}",
                    "title": title,
                    "mix": rng.choice([None, "Extended Mix", "Club Mix",
                                     "Original Mix"]),
                    "artist": rng.choice(_ARTISTS),
                    "remixer": rng.choice([None, *(_ARTISTS[:6])]),
                    "album": f"Album {i // 12 + 1:02d}",
                    "genre": rng.choice(_GENRES),
                    "label": rng.choice(_LABELS),
                    "key_name": rng.choice(["Am", "Gm", "C", "F", "Dm", "Em"]),
                    "camelot": rng.choice(_CAMELOTS),
                    "bpm": round(rng.uniform(118.0, 174.0), 2),
                    "length_s": rng.randint(240, 480),
                    "rating": rng.choice([0, 0, 3, 4, 4, 5]),
                    "comment": rng.choice(
                        [None, "peak time", "warm-up", "closer"]
                    ),
                    "dj_play_count": rng.choice([0, 0, 0, 1, 2, 5, 9, 14]),
                    "file_path": "C:/Music/Demo/",
                    "file_name": f"{title}.mp3",
                    "file_type": 1,
                    "bitrate": 320,
                    "sample_rate": 44100,
                    "release_year": rng.randint(2015, 2026),
                    "release_date": f"20{rng.randint(15, 26):02d}-"
                                    f"{rng.randint(1, 12):02d}-01",
                    "date_added": (now - timedelta(
                        days=rng.randint(0, 900))).strftime("%Y-%m-%d"),
                    "usn": i + 1,
                    "updated_at": now,
                    "synced_at": now,
                },
            )
            for k in range(rng.randint(0, 4)):
                conn.execute(
                    text(
                        "INSERT INTO cues (id, content_id, kind, in_ms,"
                        " out_ms, color, comment, rb_local_usn) VALUES"
                        " (:id,:cid,:kind,:in_ms,NULL,:color,:comment,:usn)"
                    ),
                    {
                        "id": f"cue-{i + 1:05d}-{k}",
                        "cid": f"demo-{i + 1:05d}",
                        "kind": k,
                        "in_ms": rng.randint(0, 300_000),
                        "color": rng.randint(1, 7),
                        "comment": None if k else "start",
                        "usn": n_tracks + k,
                    },
                )

        conn.execute(
            text(
                "INSERT INTO my_tags (id, name, parent_id, rb_local_usn)"
                " VALUES ('tag-energy','Energy',NULL,1),"
                " ('tag-peak','Peak','tag-energy',2),"
                " ('tag-groove','Groove','tag-energy',3),"
                " ('tag-vocal','Vocal',NULL,4)"
            )
        )
        for i in range(0, n_tracks, 3):
            conn.execute(
                text(
                    "INSERT INTO track_my_tags"
                    " (id, my_tag_id, content_id, track_no, rb_local_usn)"
                    " VALUES (:id,:tag,:cid,1,:usn)"
                ),
                {
                    "id": f"tmt-{i}",
                    "tag": rng.choice(["tag-peak", "tag-groove", "tag-vocal"]),
                    "cid": f"demo-{i + 1:05d}",
                    "usn": i,
                },
            )

        conn.execute(
            text(
                "INSERT INTO playlists (id, name, parent_id, is_folder,"
                " is_smart, seq, rb_local_usn) VALUES"
                " ('pl-root','Demo Playlists',NULL,1,0,0,1),"
                " ('pl-peak','Peak Time','pl-root',0,0,1,2),"
                " ('pl-warmup','Warm-up','pl-root',0,0,2,3)"
            )
        )
        for i in range(0, n_tracks, 5):
            conn.execute(
                text(
                    "INSERT INTO playlist_entries"
                    " (id, playlist_id, content_id, track_no, rb_local_usn)"
                    " VALUES (:id,:pl,:cid,:no,:usn)"
                ),
                {
                    "id": f"ple-{i}",
                    "pl": "pl-peak" if i % 10 == 0 else "pl-warmup",
                    "cid": f"demo-{i + 1:05d}",
                    "no": i // 5 + 1,
                    "usn": i,
                },
            )

        for s in range(3):
            sid = f"hist-{s + 1}"
            conn.execute(
                text(
                    "INSERT INTO rb_history_sessions (id, name, date_created,"
                    " parent_id, is_folder, rb_local_usn) VALUES"
                    " (:id,:name,:dc,NULL,0,:usn)"
                ),
                {
                    "id": sid,
                    "name": f"HISTORY 2026-09-{28 - s * 3:02d}",
                    "dc": (now - timedelta(days=s * 3)).strftime("%Y-%m-%d"),
                    "usn": s,
                },
            )
            for j in range(20):
                tid = f"demo-{(s * 20 + j) % n_tracks + 1:05d}"
                conn.execute(
                    text(
                        "INSERT INTO rb_history_entries (id, history_id,"
                        " content_id, track_no, created_at, rb_local_usn)"
                        " VALUES (:id,:hid,:cid,:no,:ca,:usn)"
                    ),
                    {
                        "id": f"he-{s}-{j}",
                        "hid": sid,
                        "cid": tid,
                        "no": j + 1,
                        "ca": now - timedelta(days=s * 3, hours=-(20 - j)),
                        "usn": s * 100 + j,
                    },
                )
    print(f"Seeded {n_tracks} demo tracks into {settings.db_path}")
