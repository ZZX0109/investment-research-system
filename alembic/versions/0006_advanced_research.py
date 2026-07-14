from __future__ import annotations

from pathlib import Path

from alembic import op
from investment_research.repository.migration_utils import execute_sql_script

revision = "0006_advanced_research"
down_revision = "0005_analysis_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "migrations" / "006_advanced_research.sql").read_text()
    execute_sql_script(sql)


def downgrade() -> None:
    for table in (
        "paper_observations", "research_audits", "document_artifacts", "report_schedules",
        "portfolio_risk_snapshots", "historical_scenarios", "refresh_runs",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
