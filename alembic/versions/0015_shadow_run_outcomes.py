"""Add immutable shadow outcome backfills."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_shadow_run_outcomes"
down_revision = "0014_shadow_run_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_run_outcomes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shadow_session_id", sa.String(36), nullable=False),
        sa.Column("horizon_sessions", sa.Integer, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["shadow_session_id"], ["shadow_run_sessions.id"]),
        sa.UniqueConstraint("shadow_session_id", "horizon_sessions", name="uq_shadow_outcome_session_horizon"),
    )


def downgrade() -> None:
    op.drop_table("shadow_run_outcomes")
