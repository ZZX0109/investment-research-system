"""Add four-layer PIT catalog and approval evidence metadata."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_pit_data_catalog"
down_revision = "0012_decision_snapshot_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pit_dataset_partitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("dataset", sa.String(48), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("trade_year", sa.Integer, nullable=False),
        sa.Column("object_ref", sa.Text, nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pit_partition_lookup", "pit_dataset_partitions", ["market", "dataset", "schema_version", "trade_year"])
    op.create_table(
        "standard_event_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("logical_event_id", sa.String(256), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("logical_event_id", "revision", name="uq_standard_event_revision"),
    )
    op.create_index("ix_event_revision_pit", "standard_event_revisions", ["symbol", "available_at", "active"])
    op.create_table(
        "historical_universe_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_historical_universe_pit", "historical_universe_memberships", ["market", "effective_from", "effective_to", "available_at"])
    op.create_table(
        "corporate_action_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_corporate_action_pit", "corporate_action_revisions", ["symbol", "ex_date", "available_at"])
    op.create_table(
        "trading_cost_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("verified", sa.Boolean, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("market", "version", name="uq_market_cost_version"),
    )
    op.create_table(
        "pit_dataset_manifests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("training_run_id", sa.String(128), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("decision_context", sa.String(32), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("training_run_id", "market", "decision_context", "task", name="uq_pit_manifest_scope"),
    )
    op.create_table(
        "model_approval_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("training_run_id", sa.String(128), nullable=False),
        sa.Column("market", sa.String(8), nullable=False),
        sa.Column("decision_context", sa.String(32), nullable=False),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("evidence_type", sa.String(48), nullable=False),
        sa.Column("artifact_ref", sa.Text, nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_evidence_scope", "model_approval_evidence", ["training_run_id", "market", "decision_context", "task"])


def downgrade() -> None:
    for table in (
        "model_approval_evidence", "pit_dataset_manifests", "trading_cost_schedules",
        "corporate_action_revisions", "historical_universe_memberships",
        "standard_event_revisions", "pit_dataset_partitions",
    ):
        op.drop_table(table)
