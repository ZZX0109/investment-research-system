"""Persistent delayed-quote paper trading game."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_paper_game"
down_revision = "0022_intraday_quote_spot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_game_days",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trade_date", sa.String(10), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("bulletin_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
    )
    op.create_table(
        "paper_game_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("day_id", sa.String(36), sa.ForeignKey("paper_game_days.id"), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("alias", sa.Text, nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("sector", sa.String(32), nullable=False),
        sa.Column("lot_size", sa.Integer, nullable=False),
        sa.Column("t_plus_one", sa.Boolean, nullable=False),
        sa.UniqueConstraint("day_id", "symbol", name="uq_paper_game_day_symbol"),
    )
    op.create_index("ix_paper_game_assets_day", "paper_game_assets", ["day_id"])
    op.create_table(
        "paper_game_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("visitor_token", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("persona_code", sa.String(24), nullable=True),
        sa.Column("nickname", sa.String(48), nullable=False),
        sa.Column("initial_cash_cents", sa.BigInteger, nullable=False),
        sa.Column("cash_cents", sa.BigInteger, nullable=False),
        sa.Column("realized_pnl_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("fees_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
    )
    op.create_table(
        "paper_game_positions",
        sa.Column("account_id", sa.String(36), sa.ForeignKey("paper_game_accounts.id"), primary_key=True),
        sa.Column("symbol", sa.String(12), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("available_quantity", sa.Integer, nullable=False),
        sa.Column("average_cost_cents", sa.BigInteger, nullable=False),
        sa.Column("last_buy_date", sa.String(10), nullable=True),
        sa.Column("updated_at", sa.String(48), nullable=False),
    )
    op.create_table(
        "paper_game_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("paper_game_accounts.id"), nullable=False),
        sa.Column("day_id", sa.String(36), sa.ForeignKey("paper_game_days.id"), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("submitted_at", sa.String(48), nullable=False),
        sa.Column("filled_at", sa.String(48), nullable=True),
        sa.Column("fill_price_cents", sa.BigInteger, nullable=True),
        sa.Column("fee_cents", sa.BigInteger, nullable=True),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_paper_order_idempotency"),
    )
    op.create_index("ix_paper_game_orders_account", "paper_game_orders", ["account_id", "submitted_at"])
    op.create_table(
        "paper_game_trades",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("paper_game_orders.id"), nullable=False, unique=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(12), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("price_cents", sa.BigInteger, nullable=False),
        sa.Column("fee_cents", sa.BigInteger, nullable=False),
        sa.Column("executed_at", sa.String(48), nullable=False),
    )
    op.create_table(
        "paper_game_equity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("captured_at", sa.String(48), nullable=False),
        sa.Column("cash_cents", sa.BigInteger, nullable=False),
        sa.Column("market_value_cents", sa.BigInteger, nullable=False),
        sa.Column("total_equity_cents", sa.BigInteger, nullable=False),
    )
    op.create_index("ix_paper_game_equity_account", "paper_game_equity", ["account_id", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_paper_game_equity_account", table_name="paper_game_equity")
    op.drop_table("paper_game_equity")
    op.drop_table("paper_game_trades")
    op.drop_index("ix_paper_game_orders_account", table_name="paper_game_orders")
    op.drop_table("paper_game_orders")
    op.drop_table("paper_game_positions")
    op.drop_table("paper_game_accounts")
    op.drop_index("ix_paper_game_assets_day", table_name="paper_game_assets")
    op.drop_table("paper_game_assets")
    op.drop_table("paper_game_days")
