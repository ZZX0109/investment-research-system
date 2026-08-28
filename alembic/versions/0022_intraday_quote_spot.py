"""Add intraday quote spot tables (round 33) — hourly-polled A-share spot
snapshot (full market) + major-index spot, persisted so the "盘中行情" board
and the LLM snapshot can read the latest spot.  NOT a tick push stream; it is
the latest spot snapshot polled hourly (off-hours skipped)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_intraday_quote_spot"
down_revision = "0021_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intraday_quote_spot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("market", sa.String(4), nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("latest_price", sa.Float, nullable=True),
        sa.Column("change_pct", sa.Float, nullable=True),
        sa.Column("volume", sa.Float, nullable=True),
        sa.Column("amount", sa.Float, nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.String(48), nullable=False),
    )
    op.create_index(
        "ix_intraday_quote_spot_captured",
        "intraday_quote_spot",
        ["captured_at"],
    )
    op.create_index(
        "ix_intraday_quote_spot_symbol",
        "intraday_quote_spot",
        ["symbol", "captured_at"],
    )
    op.create_table(
        "intraday_index_spot",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("market", sa.String(4), nullable=True),
        sa.Column("name", sa.Text, nullable=True),
        sa.Column("latest_price", sa.Float, nullable=True),
        sa.Column("change_pct", sa.Float, nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("captured_at", sa.String(48), nullable=False),
    )
    op.create_index(
        "ix_intraday_index_spot_captured",
        "intraday_index_spot",
        ["captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_intraday_index_spot_captured", table_name="intraday_index_spot")
    op.drop_table("intraday_index_spot")
    op.drop_index("ix_intraday_quote_spot_symbol", table_name="intraday_quote_spot")
    op.drop_index("ix_intraday_quote_spot_captured", table_name="intraday_quote_spot")
    op.drop_table("intraday_quote_spot")
