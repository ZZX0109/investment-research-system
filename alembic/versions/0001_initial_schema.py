from __future__ import annotations

from pathlib import Path

from alembic import op
from investment_research.repository.migration_utils import execute_sql_script

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "migrations" / "001_initial.sql").read_text()
    execute_sql_script(sql)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_analysis_runs_observed_at")
    op.execute("DROP INDEX IF EXISTS idx_analysis_runs_asset_id")
    op.execute("DROP TABLE IF EXISTS analysis_runs")
    op.execute("DROP INDEX IF EXISTS idx_evidence_observed_at")
    op.execute("DROP INDEX IF EXISTS idx_evidence_asset_id")
    op.execute("DROP TABLE IF EXISTS evidence")
    op.execute("DROP INDEX IF EXISTS idx_assets_observed_at")
    op.execute("DROP INDEX IF EXISTS idx_assets_source_type")
    op.execute("DROP TABLE IF EXISTS assets")
