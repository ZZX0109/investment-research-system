"""Twice-daily paper-game personality bot snapshots."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_paper_game_bots"
down_revision = "0023_paper_game"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_game_bot_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trade_date", sa.String(10), nullable=False),
        sa.Column("session", sa.String(16), nullable=False),
        sa.Column("persona_code", sa.String(24), nullable=False),
        sa.Column("return_pct", sa.Float, nullable=False),
        sa.Column("max_drawdown_pct", sa.Float, nullable=False),
        sa.Column("risk_adjusted_score", sa.Float, nullable=False),
        sa.Column("strategy_source", sa.Text, nullable=False),
        sa.Column("captured_at", sa.String(48), nullable=False),
        sa.UniqueConstraint("trade_date", "session", "persona_code", name="uq_paper_bot_session"),
    )
    op.create_index("ix_paper_bot_latest", "paper_game_bot_snapshots", ["trade_date", "session"])


def downgrade() -> None:
    op.drop_index("ix_paper_bot_latest", table_name="paper_game_bot_snapshots")
    op.drop_table("paper_game_bot_snapshots")
