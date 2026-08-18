"""Add point-in-time, revisioned financial line items (structured facts)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_financial_line_items"
down_revision = "0019_financial_knowledge_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_line_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("period", sa.String(24), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("available_at", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_financial_line_items_scope",
        "financial_line_items",
        ["market", "symbol", "period", "metric", "available_at"],
    )
    op.create_index(
        "uq_financial_line_items_hash",
        "financial_line_items",
        ["content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_financial_line_items_hash", table_name="financial_line_items")
    op.drop_index("ix_financial_line_items_scope", table_name="financial_line_items")
    op.drop_table("financial_line_items")
