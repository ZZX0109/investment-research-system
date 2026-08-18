"""Add multi-turn conversation sessions + messages (Phase 3)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_conversations"
down_revision = "0020_financial_line_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("as_of", sa.String(48), nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
    )
    op.create_index(
        "ix_conversations_user",
        "conversations",
        ["user_id", "asset_id"],
    )
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("agent_run_id", sa.String(36), nullable=True),
        sa.Column("snapshot_as_of", sa.String(48), nullable=True),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.UniqueConstraint("session_id", "sequence", name="uq_conversation_message_sequence"),
    )
    op.create_index(
        "ix_conversation_messages_session",
        "conversation_messages",
        ["session_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_session", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user", table_name="conversations")
    op.drop_table("conversations")
