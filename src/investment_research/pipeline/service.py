from __future__ import annotations

from investment_research.domain.models import (
    User,
)
from investment_research.domain.decision_context import DecisionContextType
from investment_research.domain.decision_context import SHANGHAI
from investment_research.domain.trusted_market import MarketSnapshot, ProviderCoverage
from investment_research.domain.base import utc_now
from uuid import UUID
from investment_research.pipeline.conclusion_factory import AnalysisConclusionFactory
from investment_research.pipeline.models import AnalysisBundle
from investment_research.pipeline.run_factory import AnalysisRunFactory
from investment_research.pipeline.snapshot_factory import AnalysisSnapshotFactory
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.analysis_intake import (
    AnalysisProviderRegistry,
    build_default_provider_registry,
)
from investment_research.service.data_mode import DataModePolicyService


class AnalysisPipelineService:
    def __init__(self, uow: SQLiteUnitOfWork, *, provider_registry: AnalysisProviderRegistry | None = None) -> None:
        self.uow = uow
        self.mode_policy = DataModePolicyService()
        self.run_factory = AnalysisRunFactory()
        self.snapshot_factory = AnalysisSnapshotFactory(mode_policy=self.mode_policy)
        self.conclusion_factory = AnalysisConclusionFactory()
        self.provider_registry = provider_registry or build_default_provider_registry()
        self.intake = self.provider_registry.create_intake_service()

    def build_analysis_for_asset(
        self,
        asset_id: str,
        *,
        user: User,
        decision_context: DecisionContextType | str = DecisionContextType.CLOSE_CONFIRMED,
    ) -> AnalysisBundle:
        asset = self.uow.assets.get(asset_id)
        if asset is None:
            raise ValueError("Asset not found")

        resolution = self.intake.resolve(
            asset,
            price_series=self.uow.price_series.list_for_asset(asset_id),
            evidence=self.uow.evidence.list_for_asset(asset_id),
        )
        latest_dates = [
            point.timestamp.astimezone(SHANGHAI).date()
            for series in resolution.price_series
            if series.series_role == "asset"
            for point in series.points[-1:]
        ]
        context = None
        if latest_dates:
            from investment_research.domain.decision_context import build_decision_context

            context = build_decision_context(max(latest_dates), decision_context)
        snapshot = self.snapshot_factory.build_snapshot(
            asset, resolution, decision_context=context
        )
        if snapshot.market_snapshot_id and snapshot.market_snapshot_hash:
            fetched_at = snapshot.captured_at
            coverage = ProviderCoverage(
                provider=snapshot.price_provider_name,
                dataset="daily_bars_and_evidence",
                checked_from=snapshot.decision_time or fetched_at,
                checked_until=snapshot.decision_time or fetched_at,
                source_time=snapshot.latest_price_timestamp,
                fetched_at=fetched_at,
                status=(
                    "complete"
                    if snapshot.event_coverage_status == "complete"
                    else "partial" if resolution.evidence else "failed"
                ),
                coverage_ratio=snapshot.real_share,
                issues=snapshot.stale_reasons,
            )
            self.uow.trusted_market.add_market_snapshot(
                MarketSnapshot(
                    id=UUID(snapshot.market_snapshot_id),
                    symbol=asset.ticker,
                    decision_context=snapshot.decision_context,
                    trade_date=(snapshot.decision_time or fetched_at).astimezone(SHANGHAI).date(),
                    decision_time=snapshot.decision_time or fetched_at,
                    prediction_start_date=(snapshot.prediction_start_date or fetched_at).date(),
                    feature_built_at=snapshot.feature_built_at or utc_now(),
                    security_universe_version="legacy-compatible-v1",
                    trading_calendar_version="cn-calendar-v1",
                    adjustment_policy="raw",
                    data_version="snapshot-v1",
                    evidence_ids=[item.id for item in snapshot.evidence_snapshot],
                    provider_coverage=[coverage],
                    quality_status=(
                        "failed" if snapshot.synthetic_share > 0 else
                        "degraded" if snapshot.stale_reasons else "passed"
                    ),
                    quality_issues=[
                        *snapshot.stale_reasons,
                        *([] if snapshot.synthetic_share == 0 else ["synthetic_data_forbidden"]),
                    ],
                    content_hash=snapshot.market_snapshot_hash,
                )
            )
        run = self.run_factory.build_run(asset=asset, user=user, snapshot=snapshot, evidence=resolution.evidence)
        conclusions = self.conclusion_factory.build_outputs(
            asset=asset,
            run=run,
            snapshot=snapshot,
            evidence=resolution.evidence,
        )

        self.uow.snapshots.add(str(run.id), snapshot)
        self.uow.predictions.add(conclusions.prediction)
        self.uow.risks.add(conclusions.risk)
        self.uow.recommendations.add(conclusions.recommendation)
        self.uow.judge_scores.add(conclusions.judge)

        resolved_model_version = f"{conclusions.prediction.model_name}@{conclusions.prediction.model_version}"
        stored_run = self.uow.analysis_runs.add(
            run.model_copy(
                update={
                    "model_version": resolved_model_version,
                    "prediction_ids": [conclusions.prediction.id],
                    "risk_conclusion_ids": [conclusions.risk.id],
                    "recommendation_ids": [conclusions.recommendation.id],
                    "judge_score_ids": [conclusions.judge.id],
                }
            )
        )
        correlation_id = str(stored_run.id)
        if self.uow.domain.is_registered_user(user.id):
            for evidence in resolution.evidence:
                self.uow.domain.register_evidence(evidence=evidence, owner=user)
            self.uow.domain.record_research_run(
                run=stored_run, owner=user, correlation_id=correlation_id
            )
            self.uow.domain.record_model_inference(
                run=stored_run,
                prediction=conclusions.prediction,
                owner=user,
                correlation_id=correlation_id,
            )
            self.uow.domain.record_gate_evaluation(
                run=stored_run,
                owner=user,
                verdict=conclusions.judge.verdict,
                score=conclusions.judge.score,
                reasons=conclusions.judge.gating_reasons,
                correlation_id=correlation_id,
            )

        return AnalysisBundle(
            asset=asset,
            run=stored_run,
            snapshot=snapshot,
            source_meta=snapshot.source_meta,
            evidence=resolution.evidence,
            predictions=[conclusions.prediction],
            risk_conclusions=[conclusions.risk],
            recommendations=[conclusions.recommendation],
            judge_scores=[conclusions.judge],
        )

    def get_bundle(self, run_id: str) -> AnalysisBundle | None:
        run = self.uow.analysis_runs.get(run_id)
        if run is None:
            return None
        snapshot = self.uow.snapshots.get(run_id)
        if snapshot is None:
            return None
        asset = snapshot.asset_snapshot or self.uow.assets.get(str(run.asset_id))
        if asset is None:
            return None
        evidence = snapshot.evidence_snapshot
        if not evidence:
            evidence = [item for item in self.uow.evidence.list_for_asset(str(asset.id)) if str(item.id) in snapshot.evidence_ids]
        return AnalysisBundle(
            asset=asset,
            run=run,
            snapshot=snapshot,
            source_meta=snapshot.source_meta,
            evidence=evidence,
            predictions=self.uow.predictions.list_for_run(run_id),
            risk_conclusions=self.uow.risks.list_for_run(run_id),
            recommendations=self.uow.recommendations.list_for_run(run_id),
            judge_scores=self.uow.judge_scores.list_for_run(run_id),
            reports=self.uow.reports.list_for_run(run_id),
        )
