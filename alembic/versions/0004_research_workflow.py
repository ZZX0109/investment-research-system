from __future__ import annotations

from pathlib import Path

from alembic import op
from investment_research.repository.migration_utils import execute_sql_script

revision = "0004_research_workflow"
down_revision = "0003_positions_and_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "migrations" / "004_research_workflow.sql").read_text()
    execute_sql_script(sql)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_research_reports_analysis_run_id")
    op.execute("DROP INDEX IF EXISTS idx_research_reports_asset_id")
    op.execute("DROP TABLE IF EXISTS research_reports")
    op.execute("DROP INDEX IF EXISTS idx_price_series_asset_id")
    op.execute("DROP TABLE IF EXISTS price_series")
    op.execute("DROP INDEX IF EXISTS idx_watchlists_user_id")
    op.execute("DROP TABLE IF EXISTS watchlists")
