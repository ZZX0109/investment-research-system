"""Add revocable, least-privilege WorkBuddy connector credentials."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_workbuddy_connections"
down_revision = "0017_financial_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workbuddy_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("token_prefix", sa.String(20), nullable=False),
        sa.Column("scopes_json", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
        sa.Column("last_used_at", sa.String(48), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workbuddy_connections_owner", "workbuddy_connections", ["owner_user_id", "enabled"])


def downgrade() -> None:
    op.drop_index("ix_workbuddy_connections_owner", table_name="workbuddy_connections")
    op.drop_table("workbuddy_connections")
