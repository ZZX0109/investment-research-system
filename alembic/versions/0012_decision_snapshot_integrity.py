"""Add decision snapshots, provider coverage and artifact integrity state."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_decision_snapshot_integrity"
down_revision = "0011_trusted_cn_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("decision_context", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("quality_status", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_market_snapshot_symbol_decision",
        "market_snapshots",
        ["symbol", "decision_context", "decision_time"],
    )
    op.create_table(
        "provider_coverage_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(64), nullable=False),
        sa.Column("checked_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("coverage_ratio", sa.Float, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_table(
        "ingestion_cursors",
        sa.Column("provider", sa.String(128), primary_key=True),
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("interval", sa.String(16), primary_key=True),
        sa.Column("cursor_value", sa.String(512), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "model_artifact_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("decision_context", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_artifact_task_context_status",
        "model_artifact_sets",
        ["task", "decision_context", "status"],
    )


def downgrade() -> None:
    op.drop_table("model_artifact_sets")
    op.drop_table("ingestion_cursors")
    op.drop_table("provider_coverage_runs")
    op.drop_table("market_snapshots")
