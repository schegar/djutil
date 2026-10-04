"""Initial schema: library mirror, sync state, sets/transitions, FTS.

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tracks",
        # Integer pk keeps tracks_fts stable across VACUUM (FTS rowids are
        # renumbered for rowid tables); `id` stays the Rekordbox ContentID.
        sa.Column("pk", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("id", sa.Text, unique=True, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("mix", sa.Text),
        sa.Column("artist_id", sa.Text),
        sa.Column("artist", sa.Text),
        sa.Column("original_artist_id", sa.Text),
        sa.Column("original_artist", sa.Text),
        sa.Column("remixer_id", sa.Text),
        sa.Column("remixer", sa.Text),
        sa.Column("composer_id", sa.Text),
        sa.Column("composer", sa.Text),
        sa.Column("album_id", sa.Text),
        sa.Column("album", sa.Text),
        sa.Column("genre_id", sa.Text),
        sa.Column("genre", sa.Text),
        sa.Column("label_id", sa.Text),
        sa.Column("label", sa.Text),
        sa.Column("key_id", sa.Text),
        sa.Column("key_name", sa.Text),
        sa.Column("camelot", sa.Text),
        sa.Column("bpm", sa.Float),
        sa.Column("length_s", sa.Integer),
        sa.Column("rating", sa.Integer),
        sa.Column("color", sa.Text),
        sa.Column("comment", sa.Text),
        sa.Column("dj_play_count", sa.Integer),
        sa.Column("file_path", sa.Text),
        sa.Column("file_name", sa.Text),
        sa.Column("file_type", sa.Integer),
        sa.Column("bitrate", sa.Integer),
        sa.Column("sample_rate", sa.Integer),
        sa.Column("release_year", sa.Integer),
        sa.Column("release_date", sa.Text),
        sa.Column("date_added", sa.Text),
        sa.Column("artwork_path", sa.Text),
        sa.Column("artwork_hash", sa.Text),
        sa.Column("rb_local_usn", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime),
        sa.Column("deleted", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("synced_at", sa.DateTime),
    )
    for col in ("bpm", "camelot", "genre", "date_added", "dj_play_count"):
        op.create_index(f"ix_tracks_{col}", "tracks", [col])

    op.execute(
        "CREATE VIRTUAL TABLE tracks_fts USING fts5("
        "title, mix, artist, remixer, album, label, genre, comment,"
        " content='tracks', content_rowid='pk')"
    )
    op.execute(
        "CREATE TRIGGER tracks_fts_ai AFTER INSERT ON tracks BEGIN"
        " INSERT INTO tracks_fts(rowid, title, mix, artist, remixer, album,"
        " label, genre, comment) VALUES (new.pk, new.title, new.mix,"
        " new.artist, new.remixer, new.album, new.label, new.genre,"
        " new.comment); END"
    )
    op.execute(
        "CREATE TRIGGER tracks_fts_ad AFTER DELETE ON tracks BEGIN"
        " INSERT INTO tracks_fts(tracks_fts, rowid, title, mix, artist,"
        " remixer, album, label, genre, comment) VALUES('delete', old.pk,"
        " old.title, old.mix, old.artist, old.remixer, old.album, old.label,"
        " old.genre, old.comment); END"
    )
    op.execute(
        "CREATE TRIGGER tracks_fts_au AFTER UPDATE ON tracks BEGIN"
        " INSERT INTO tracks_fts(tracks_fts, rowid, title, mix, artist,"
        " remixer, album, label, genre, comment) VALUES('delete', old.pk,"
        " old.title, old.mix, old.artist, old.remixer, old.album, old.label,"
        " old.genre, old.comment);"
        " INSERT INTO tracks_fts(rowid, title, mix, artist, remixer, album,"
        " label, genre, comment) VALUES (new.pk, new.title, new.mix,"
        " new.artist, new.remixer, new.album, new.label, new.genre,"
        " new.comment); END"
    )

    op.create_table(
        "cues",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("content_id", sa.Text, index=True),
        sa.Column("kind", sa.Integer),
        sa.Column("in_ms", sa.Integer),
        sa.Column("out_ms", sa.Integer),
        sa.Column("color", sa.Integer),
        sa.Column("comment", sa.Text),
        sa.Column("rb_local_usn", sa.BigInteger),
    )
    op.create_table(
        "my_tags",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("parent_id", sa.Text),
        sa.Column("rb_local_usn", sa.BigInteger),
    )
    op.create_table(
        "track_my_tags",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("my_tag_id", sa.Text, index=True),
        sa.Column("content_id", sa.Text, index=True),
        sa.Column("track_no", sa.Integer),
        sa.Column("rb_local_usn", sa.BigInteger),
    )
    op.create_table(
        "playlists",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("parent_id", sa.Text),
        sa.Column("is_folder", sa.Boolean, server_default="0"),
        sa.Column("is_smart", sa.Boolean, server_default="0"),
        sa.Column("seq", sa.Integer),
        sa.Column("rb_local_usn", sa.BigInteger),
    )
    op.create_table(
        "playlist_entries",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("playlist_id", sa.Text, index=True),
        sa.Column("content_id", sa.Text),
        sa.Column("track_no", sa.Integer),
        sa.Column("rb_local_usn", sa.BigInteger),
    )
    op.create_table(
        "rb_history_sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("date_created", sa.Text),
        sa.Column("parent_id", sa.Text),
        sa.Column("is_folder", sa.Boolean, server_default="0"),
        sa.Column("rb_local_usn", sa.BigInteger),
    )
    op.create_table(
        "rb_history_entries",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("history_id", sa.Text, index=True),
        sa.Column("content_id", sa.Text),
        sa.Column("track_no", sa.Integer),
        sa.Column("created_at", sa.DateTime),
        sa.Column("rb_local_usn", sa.BigInteger),
    )

    op.create_table(
        "sync_state",
        sa.Column("entity", sa.Text, primary_key=True),
        sa.Column("last_usn", sa.BigInteger),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "sets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text),
        sa.Column("started_at", sa.DateTime),
        sa.Column("ended_at", sa.DateTime),
        sa.Column(
            "source",
            sa.Text,
            sa.CheckConstraint("source IN ('live','rb_import')"),
        ),
        sa.Column("rb_history_id", sa.Text, unique=True),
        sa.Column("notes", sa.Text),
    )
    op.create_table(
        "set_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "set_id",
            sa.Integer,
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("track_id", sa.Text),
        sa.Column("position", sa.Integer),
        sa.Column("played_at", sa.DateTime),
        sa.Column("offset_seconds", sa.Integer),
        sa.Column("rb_history_entry_id", sa.Text, unique=True),
    )
    op.create_table(
        "transitions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("from_track_id", sa.Text),
        sa.Column("to_track_id", sa.Text),
        sa.Column(
            "set_id",
            sa.Integer,
            sa.ForeignKey("sets.id", ondelete="CASCADE"),
        ),
        sa.Column("from_entry_id", sa.Integer),
        sa.Column("to_entry_id", sa.Integer),
        sa.Column("played_at", sa.DateTime),
        sa.Column("favorite", sa.Boolean, server_default="0"),
        sa.Column(
            "rating",
            sa.Integer,
            sa.CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5"),
        ),
        sa.Column("comment", sa.Text),
    )
    op.execute(
        "CREATE VIEW transition_stats AS"
        " SELECT from_track_id, to_track_id, COUNT(*) AS count,"
        " SUM(CASE WHEN favorite THEN 1 ELSE 0 END) AS fav_count,"
        " AVG(rating) AS avg_rating"
        " FROM transitions"
        " WHERE from_track_id IS NOT NULL AND to_track_id IS NOT NULL"
        " GROUP BY from_track_id, to_track_id"
    )


def downgrade() -> None:
    for table in (
        "tracks_fts",
        "transitions",
        "set_entries",
        "sets",
        "sync_state",
        "rb_history_entries",
        "rb_history_sessions",
        "playlist_entries",
        "playlists",
        "track_my_tags",
        "my_tags",
        "cues",
        "tracks",
    ):
        op.drop_table(table)
    op.execute("DROP VIEW transition_stats")
