"""Play sources: deck-reader plays linked to history rows.

Revision ID: 0003_play_sources
Revises: 0002_live_sets
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_play_sources"
down_revision = "0002_live_sets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plays",
        sa.Column(
            "source", sa.Text, nullable=False, server_default="history"
        ),
    )
    op.add_column("plays", sa.Column("deck", sa.Integer, nullable=True))
    op.add_column(
        "plays", sa.Column("rb_history_entry_id", sa.Text, nullable=True)
    )
    op.create_index(
        "ix_plays_rb_history_entry_id", "plays", ["rb_history_entry_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_plays_rb_history_entry_id", table_name="plays")
    op.drop_column("plays", "rb_history_entry_id")
    op.drop_column("plays", "deck")
    op.drop_column("plays", "source")
