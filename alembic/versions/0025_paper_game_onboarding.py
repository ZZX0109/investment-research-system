"""Add frozen close snapshots and setup state to paper trading."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_paper_game_onboarding"
down_revision = "0024_paper_game_bots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_game_accounts", sa.Column("setup_status", sa.String(24), nullable=False, server_default="setup_required"))
    op.add_column("paper_game_accounts", sa.Column("setup_trade_date", sa.String(10), nullable=True))
    op.add_column("paper_game_accounts", sa.Column("setup_confirmed_at", sa.String(48), nullable=True))
    op.create_table(
        "paper_game_close_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trade_date", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("close_cents", sa.BigInteger, nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("captured_at", sa.String(48), nullable=False),
        sa.UniqueConstraint("trade_date", "symbol", name="uq_paper_game_close_symbol"),
    )
    op.create_index("ix_paper_game_close_date", "paper_game_close_snapshots", ["trade_date"])


def downgrade() -> None:
    op.drop_index("ix_paper_game_close_date", table_name="paper_game_close_snapshots")
    op.drop_table("paper_game_close_snapshots")
    op.drop_column("paper_game_accounts", "setup_confirmed_at")
    op.drop_column("paper_game_accounts", "setup_trade_date")
    op.drop_column("paper_game_accounts", "setup_status")
