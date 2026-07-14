"""Add evidence-bound agent runtime and validation records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_evidence_bound_agent"
down_revision = "0007_long_term_domain"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "llm_provider_profiles",
        _id(),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.Text, nullable=True),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("credential_ref", sa.String(256), nullable=True),
        sa.Column("timeout_seconds", sa.Float, nullable=False),
        sa.Column("context_limit", sa.Integer, nullable=False),
        sa.Column("fallback_profile_id", sa.String(36), sa.ForeignKey("llm_provider_profiles.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_llm_profile_owner_name"),
    )
    op.create_table(
        "agent_runs",
        _id(),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("research_reports.id"), nullable=True),
        sa.Column("provider_profile_id", sa.String(36), sa.ForeignKey("llm_provider_profiles.id"), nullable=True),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("task_text", sa.Text, nullable=False),
        sa.Column("user_preference", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("current_node", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=True),
        sa.Column("abstain_reason", sa.Text, nullable=True),
        sa.Column("llm_calls_used", sa.Integer, nullable=False),
        sa.Column("tool_calls_used", sa.Integer, nullable=False),
        sa.Column("input_tokens_used", sa.Integer, nullable=False),
        sa.Column("output_tokens_used", sa.Integer, nullable=False),
        sa.Column("repair_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "agent_plan_revisions",
        _id(),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("plan_json", sa.Text, nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_run_id", "revision_number", name="uq_agent_plan_revision"),
    )
    op.create_table(
        "agent_node_executions",
        _id(),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_json", sa.Text, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_run_id", "node_name", "attempt", name="uq_agent_node_attempt"),
    )
    op.create_table(
        "agent_tool_calls",
        _id(),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("tool_id", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "llm_calls",
        _id(),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("provider_protocol", sa.String(32), nullable=False),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("cache_hit", sa.Boolean, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "llm_cache_entries",
        sa.Column("cache_key", sa.String(64), primary_key=True),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_events",
        _id(),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_run_id", "sequence", name="uq_agent_event_sequence"),
    )
    op.create_table(
        "paper_predictions_v2",
        _id(),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("inference_output_id", sa.String(36), sa.ForeignKey("inference_outputs.id"), nullable=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("research_run_id", sa.String(36), sa.ForeignKey("research_runs_v2.run_id"), nullable=True),
        sa.Column("model_role", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_probability", sa.Float, nullable=True),
        sa.Column("risk_bucket", sa.String(32), nullable=False),
        sa.Column("feature_coverage", sa.Float, nullable=False),
        sa.Column("abstained", sa.Boolean, nullable=False),
        sa.Column("evaluation_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_outcomes",
        _id(),
        sa.Column("paper_prediction_id", sa.String(36), sa.ForeignKey("paper_predictions_v2.id"), nullable=False, unique=True),
        sa.Column("realized_max_drawdown", sa.Float, nullable=False),
        sa.Column("alert_lead_days", sa.Integer, nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "drift_evaluations",
        _id(),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("psi", sa.Float, nullable=True),
        sa.Column("ece", sa.Float, nullable=True),
        sa.Column("brier", sa.Float, nullable=True),
        sa.Column("drawdown_lift", sa.Float, nullable=True),
        sa.Column("feature_coverage", sa.Float, nullable=False),
        sa.Column("abstention_rate", sa.Float, nullable=False),
        sa.Column("provider_missing_rate", sa.Float, nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "document_evaluations",
        _id(),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("document_artifacts.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("gold_version", sa.String(64), nullable=False),
        sa.Column("numeric_accuracy", sa.Float, nullable=False),
        sa.Column("cell_location_accuracy", sa.Float, nullable=False),
        sa.Column("trend_accuracy", sa.Float, nullable=False),
        sa.Column("citation_completeness", sa.Float, nullable=False),
        sa.Column("numeric_refusal_rate", sa.Float, nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("details_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, columns in (
        ("agent_runs", ["owner_user_id", "state"]),
        ("agent_node_executions", ["agent_run_id", "node_name"]),
        ("agent_events", ["agent_run_id", "sequence"]),
        ("paper_predictions_v2", ["evaluation_due_at", "model_role"]),
    ):
        op.create_index(f"ix_{table}_{'_'.join(columns)}", table, columns)


def downgrade() -> None:
    for table in (
        "document_evaluations", "drift_evaluations", "paper_outcomes",
        "paper_predictions_v2", "agent_events", "llm_cache_entries", "llm_calls",
        "agent_tool_calls", "agent_node_executions", "agent_plan_revisions",
        "agent_runs", "llm_provider_profiles",
    ):
        op.drop_table(table)
