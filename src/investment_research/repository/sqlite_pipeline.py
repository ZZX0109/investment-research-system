from __future__ import annotations

import sqlite3

from investment_research.domain.models import InvestmentRecommendation, JudgeScore, ModelPrediction, RiskConclusion
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.repository.sqlite_base import SQLiteRepositoryMixin


class SQLiteAnalysisSnapshotRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, run_id: str, snapshot: AnalysisSnapshot) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO analysis_snapshots (run_id, payload)
            VALUES (?, ?)
            """,
            (run_id, snapshot.model_dump_json()),
        )
        self.connection.commit()

    def get(self, run_id: str) -> AnalysisSnapshot | None:
        row = self.connection.execute(
            "SELECT payload FROM analysis_snapshots WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return None if row is None else AnalysisSnapshot.model_validate_json(str(row[0]))


class SQLiteModelPredictionRepository(SQLiteRepositoryMixin):
    table_name = "model_predictions"
    model_cls = ModelPrediction

    def add(self, prediction: ModelPrediction) -> ModelPrediction:
        values = self._serialize_entity(prediction)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO model_predictions (
                id, analysis_run_id, asset_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(prediction.analysis_run_id),
                str(prediction.asset_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return prediction

    def list_for_run(self, run_id: str) -> list[ModelPrediction]:
        rows = self.connection.execute(
            "SELECT payload FROM model_predictions WHERE analysis_run_id = ? ORDER BY observed_at DESC",
            (run_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteRiskConclusionRepository(SQLiteRepositoryMixin):
    table_name = "risk_conclusions"
    model_cls = RiskConclusion

    def add(self, conclusion: RiskConclusion) -> RiskConclusion:
        values = self._serialize_entity(conclusion)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO risk_conclusions (
                id, analysis_run_id, asset_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(conclusion.analysis_run_id),
                str(conclusion.asset_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return conclusion

    def list_for_run(self, run_id: str) -> list[RiskConclusion]:
        rows = self.connection.execute(
            "SELECT payload FROM risk_conclusions WHERE analysis_run_id = ? ORDER BY observed_at DESC",
            (run_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteRecommendationRepository(SQLiteRepositoryMixin):
    table_name = "recommendations"
    model_cls = InvestmentRecommendation

    def add(self, recommendation: InvestmentRecommendation) -> InvestmentRecommendation:
        values = self._serialize_entity(recommendation)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO recommendations (
                id, analysis_run_id, asset_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(recommendation.analysis_run_id),
                str(recommendation.asset_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return recommendation

    def list_for_run(self, run_id: str) -> list[InvestmentRecommendation]:
        rows = self.connection.execute(
            "SELECT payload FROM recommendations WHERE analysis_run_id = ? ORDER BY observed_at DESC",
            (run_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteJudgeScoreRepository(SQLiteRepositoryMixin):
    table_name = "judge_scores"
    model_cls = JudgeScore

    def add(self, judge_score: JudgeScore) -> JudgeScore:
        values = self._serialize_entity(judge_score)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO judge_scores (
                id, analysis_run_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(judge_score.analysis_run_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return judge_score

    def list_for_run(self, run_id: str) -> list[JudgeScore]:
        rows = self.connection.execute(
            "SELECT payload FROM judge_scores WHERE analysis_run_id = ? ORDER BY observed_at DESC",
            (run_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]
