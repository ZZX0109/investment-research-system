from __future__ import annotations

from pathlib import Path

from alembic import op
from investment_research.repository.migration_utils import execute_sql_script

revision = "0002_auth_schema"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "migrations" / "002_auth.sql").read_text()
    execute_sql_script(sql)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_refresh_sessions_user_id")
    op.execute("DROP INDEX IF EXISTS idx_refresh_sessions_token_id")
    op.execute("DROP TABLE IF EXISTS refresh_sessions")
    op.execute("DROP INDEX IF EXISTS idx_users_email")
    op.execute("DROP TABLE IF EXISTS users")
