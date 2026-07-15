"""Add immutable per-scope shadow-run evidence."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_shadow_run_sessions"
down_revision = "0013_pit_data_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_run_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("training_run_id", sa.String(128), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("decision_context", sa.String(32), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("valid", sa.Boolean, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "training_run_id", "market", "decision_context", "task", "trade_date",
            name="uq_shadow_run_scope_day",
        ),
    )
    op.create_index(
        "ix_shadow_run_scope", "shadow_run_sessions",
        ["training_run_id", "market", "decision_context", "task", "valid"],
    )


def downgrade() -> None:
    op.drop_table("shadow_run_sessions")
