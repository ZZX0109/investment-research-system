from __future__ import annotations

from pathlib import Path

from alembic import op
from investment_research.repository.migration_utils import execute_sql_script

revision = "0003_positions_and_audit"
down_revision = "0002_auth_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "migrations" / "003_positions_and_audit.sql").read_text()
    execute_sql_script(sql)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_records_target_id")
    op.execute("DROP INDEX IF EXISTS idx_audit_records_actor")
    op.execute("DROP TABLE IF EXISTS audit_records")
    op.execute("DROP INDEX IF EXISTS idx_positions_asset_id")
    op.execute("DROP INDEX IF EXISTS idx_positions_user_id")
    op.execute("DROP TABLE IF EXISTS positions")
