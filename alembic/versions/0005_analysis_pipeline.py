from __future__ import annotations

from pathlib import Path

from alembic import op
from investment_research.repository.migration_utils import execute_sql_script

revision = "0005_analysis_pipeline"
down_revision = "0004_research_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[2] / "migrations" / "005_analysis_pipeline.sql").read_text()
    execute_sql_script(sql)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_judge_scores_run_id")
    op.execute("DROP TABLE IF EXISTS judge_scores")
    op.execute("DROP INDEX IF EXISTS idx_recommendations_run_id")
    op.execute("DROP TABLE IF EXISTS recommendations")
    op.execute("DROP INDEX IF EXISTS idx_risk_conclusions_run_id")
    op.execute("DROP TABLE IF EXISTS risk_conclusions")
    op.execute("DROP INDEX IF EXISTS idx_model_predictions_run_id")
    op.execute("DROP TABLE IF EXISTS model_predictions")
    op.execute("DROP TABLE IF EXISTS analysis_snapshots")
