"""Plays (live events), settings kv, sets.auto.

Revision ID: 0002_live_sets
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_live_sets"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plays",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("history_entry_id", sa.Text, unique=True),
        sa.Column("track_id", sa.Text),
        sa.Column("history_id", sa.Text),
        sa.Column("played_at", sa.DateTime),
        sa.Column("detected_at", sa.DateTime),
        sa.Column(
            "set_id",
            sa.Integer,
            sa.ForeignKey("sets.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_plays_track_id", "plays", ["track_id"])

    op.create_table(
        "settings",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text),
    )
    op.execute("INSERT INTO settings (key, value) VALUES ('auto_record', '1')")

    op.add_column(
        "sets", sa.Column("auto", sa.Boolean, nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("sets", "auto")
    op.drop_table("settings")
    op.drop_table("plays")
