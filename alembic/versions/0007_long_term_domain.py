"""Add relational domain tables for long-lived research records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007_long_term_domain"
down_revision = "0006_advanced_research"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "resource_owners",
        _id(),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_resource_owner"),
    )
    op.create_table(
        "resource_shares",
        _id(),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("viewer_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resource_type", "resource_id", "viewer_user_id", name="uq_resource_share"),
    )
    op.create_table(
        "knowledge_sources",
        _id(),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_name", sa.String(256), nullable=False),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column("source_tier", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "canonical_url", name="uq_source_owner_url"),
    )
    op.create_table(
        "source_documents",
        _id(),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("knowledge_sources.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "document_key", name="uq_source_document"),
    )
    op.create_table(
        "source_revisions",
        _id(),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "normalized_hash", name="uq_document_normalized_hash"),
        sa.UniqueConstraint("document_id", "revision_number", name="uq_document_revision_number"),
    )
    op.create_table(
        "knowledge_evidence",
        _id(),
        sa.Column("legacy_evidence_id", sa.String(36), sa.ForeignKey("evidence.id"), nullable=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_revision_id", sa.String(36), sa.ForeignKey("source_revisions.id"), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_evidence_id", name="uq_knowledge_legacy_evidence"),
    )
    op.create_table(
        "citations",
        _id(),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("knowledge_evidence.id"), nullable=False),
        sa.Column("source_revision_id", sa.String(36), sa.ForeignKey("source_revisions.id"), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("table_locator", sa.String(256), nullable=True),
        sa.Column("cell_locator", sa.String(256), nullable=True),
        sa.Column("excerpt", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "claims",
        _id(),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contrary_claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=True),
        sa.Column("supersedes_claim_id", sa.String(36), sa.ForeignKey("claims.id"), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "claim_evidence_links",
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("claims.id"), primary_key=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("knowledge_evidence.id"), primary_key=True),
        sa.Column("citation_id", sa.String(36), sa.ForeignKey("citations.id"), nullable=True),
        sa.Column("relation", sa.String(16), nullable=False),
    )
    op.create_table(
        "research_runs_v2",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("feature_contract_version", sa.String(128), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_run_evidence",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("research_runs_v2.run_id"), primary_key=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("knowledge_evidence.id"), primary_key=True),
    )
    op.create_table(
        "feature_contracts",
        _id(),
        sa.Column("version", sa.String(128), nullable=False, unique=True),
        sa.Column("feature_order_json", sa.Text, nullable=False),
        sa.Column("scaler_object_key", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "model_versions",
        _id(),
        sa.Column("model_id", sa.String(256), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("feature_contract_id", sa.String(36), sa.ForeignKey("feature_contracts.id"), nullable=True),
        sa.Column("artifact_key", sa.String(1024), nullable=False),
        sa.Column("metadata_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "model_runs",
        _id(),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs_v2.run_id"), nullable=False),
        sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.id"), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "inference_outputs",
        _id(),
        sa.Column("model_run_id", sa.String(36), sa.ForeignKey("model_runs.id"), nullable=False),
        sa.Column("risk_probability", sa.Float, nullable=True),
        sa.Column("feature_coverage", sa.Float, nullable=False),
        sa.Column("abstained", sa.Boolean, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "portfolio_snapshots_v2",
        _id(),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs_v2.run_id"), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "portfolio_exposures",
        _id(),
        sa.Column("portfolio_snapshot_id", sa.String(36), sa.ForeignKey("portfolio_snapshots_v2.id"), nullable=False),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("dimension_key", sa.String(128), nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
    )
    op.create_table(
        "risk_contributions",
        _id(),
        sa.Column("portfolio_snapshot_id", sa.String(36), sa.ForeignKey("portfolio_snapshots_v2.id"), nullable=False),
        sa.Column("position_id", sa.String(36), sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("contribution", sa.Float, nullable=False),
    )
    op.create_table(
        "stress_results",
        _id(),
        sa.Column("portfolio_snapshot_id", sa.String(36), sa.ForeignKey("portfolio_snapshots_v2.id"), nullable=False),
        sa.Column("scenario_key", sa.String(128), nullable=False),
        sa.Column("impact", sa.Float, nullable=False),
    )
    op.create_table(
        "quality_gate_policies",
        _id(),
        sa.Column("version", sa.String(128), nullable=False, unique=True),
        sa.Column("rules_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "gate_evaluations",
        _id(),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs_v2.run_id"), nullable=False),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("quality_gate_policies.id"), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "gate_findings",
        _id(),
        sa.Column("gate_evaluation_id", sa.String(36), sa.ForeignKey("gate_evaluations.id"), nullable=False),
        sa.Column("rule_key", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
    )
    op.create_table(
        "outbox_events",
        _id(),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "audit_events",
        _id(),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("details_json", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "legacy_replay_mappings",
        _id(),
        sa.Column("legacy_source", sa.String(128), nullable=False),
        sa.Column("legacy_table", sa.String(128), nullable=False),
        sa.Column("legacy_id", sa.String(256), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_source", "legacy_table", "legacy_id", name="uq_legacy_replay_mapping"),
    )
    op.create_table(
        "legacy_replay_failures",
        _id(),
        sa.Column("legacy_source", sa.String(128), nullable=False),
        sa.Column("legacy_table", sa.String(128), nullable=False),
        sa.Column("legacy_id", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, columns in (
        ("resource_shares", ["viewer_user_id"]),
        ("knowledge_evidence", ["asset_id", "owner_user_id"]),
        ("claims", ["asset_id", "owner_user_id", "status"]),
        ("research_runs_v2", ["owner_user_id", "correlation_id"]),
        ("outbox_events", ["state", "occurred_at"]),
    ):
        op.create_index(f"ix_{table}_{'_'.join(columns)}", table, columns)


def downgrade() -> None:
    for table in (
        "audit_events", "outbox_events", "gate_findings", "gate_evaluations",
        "quality_gate_policies", "stress_results", "risk_contributions",
        "portfolio_exposures", "portfolio_snapshots_v2", "inference_outputs",
        "model_runs", "model_versions", "feature_contracts", "research_run_evidence",
        "research_runs_v2", "claim_evidence_links", "claims", "citations",
        "knowledge_evidence", "source_revisions", "source_documents", "knowledge_sources",
        "legacy_replay_failures", "legacy_replay_mappings", "resource_shares", "resource_owners",
    ):
        op.drop_table(table)
