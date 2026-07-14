"""Add immutable document gold and paper feature snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_agent_validation_details"
down_revision = "0008_evidence_bound_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "document_gold_annotations" not in inspector.get_table_names():
        op.create_table(
            "document_gold_annotations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_sha256", sa.String(64), nullable=False),
            sa.Column("source_url", sa.Text, nullable=False),
            sa.Column("annotation_version", sa.String(64), nullable=False),
            sa.Column("annotation_json", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("document_sha256", "annotation_version", name="uq_document_gold_version"),
        )
    document_columns = {item["name"] for item in inspector.get_columns("document_evaluations")}
    document_foreign_keys = inspector.get_foreign_keys("document_evaluations")
    if "gold_annotation_id" not in document_columns:
        with op.batch_alter_table("document_evaluations") as batch:
            batch.add_column(sa.Column("gold_annotation_id", sa.String(36), nullable=True))
    has_gold_foreign_key = any(
        item.get("referred_table") == "document_gold_annotations"
        and item.get("constrained_columns") == ["gold_annotation_id"]
        for item in document_foreign_keys
    )
    if not has_gold_foreign_key:
        with op.batch_alter_table("document_evaluations") as batch:
            batch.create_foreign_key(
                "fk_document_evaluation_gold",
                "document_gold_annotations",
                ["gold_annotation_id"],
                ["id"],
            )
    paper_columns = {item["name"] for item in inspector.get_columns("paper_predictions_v2")}
    with op.batch_alter_table("paper_predictions_v2") as batch:
        if "feature_values_json" not in paper_columns:
            batch.add_column(sa.Column("feature_values_json", sa.Text, nullable=True))
        if "provider_missing_rate" not in paper_columns:
            batch.add_column(sa.Column("provider_missing_rate", sa.Float, nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("paper_predictions_v2") as batch:
        batch.drop_column("provider_missing_rate")
        batch.drop_column("feature_values_json")
    with op.batch_alter_table("document_evaluations") as batch:
        batch.drop_constraint("fk_document_evaluation_gold", type_="foreignkey")
        batch.drop_column("gold_annotation_id")
    op.drop_table("document_gold_annotations")
