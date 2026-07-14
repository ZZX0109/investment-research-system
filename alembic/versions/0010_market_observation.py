"""Add durable market observation and directional research records."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_market_observation"
down_revision = "0009_agent_validation_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_quotes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("quote_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_price", sa.Float, nullable=False),
        sa.Column("previous_close", sa.Float, nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_market_quotes_asset_time", "market_quotes", ["asset_id", "quote_at"])
    op.create_table(
        "market_quote_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_quote_attempts_asset_time", "market_quote_attempts", ["asset_id", "attempted_at"])
    op.create_table(
        "observation_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("observation_id", "revision", name="uq_observation_revision"),
    )
    op.create_table(
        "directional_forecasts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ("directional_forecasts", "observation_revisions", "market_quote_attempts", "market_quotes"):
        op.drop_table(table)
