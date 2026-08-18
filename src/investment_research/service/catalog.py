from __future__ import annotations

from datetime import datetime, timezone

from investment_research.domain.base import GenerationLink, Provenance
from investment_research.domain.catalog import AnalysisProviderConfig, AnalysisProviderSummary, DomainCatalog
from investment_research.domain.enums import (
    AssetType,
    DataMode,
    DataSourceType,
    EvidenceType,
    RecommendationAction,
    RiskLevel,
)
from investment_research.domain.models import (
    AnalysisRun,
    Asset,
    Evidence,
    InvestmentRecommendation,
    JudgeScore,
    ModelPrediction,
    ResearchReport,
    RiskConclusion,
    User,
)
from investment_research.service.analysis_intake import (
    AnalysisProviderRegistry,
    AnalysisProviderSettings,
    build_provider_registry,
)
from investment_research.service.data_mode import DataModePolicyService


class DomainCatalogService:
    """Thin application service for exposing the current domain contract."""

    def __init__(
        self,
        *,
        provider_registry: AnalysisProviderRegistry | None = None,
        provider_settings: AnalysisProviderSettings | None = None,
    ) -> None:
        self.mode_policy = DataModePolicyService()
        self.provider_settings = provider_settings or AnalysisProviderSettings()
        self.provider_registry = provider_registry or build_provider_registry(self.provider_settings)

    def describe_domain(self) -> DomainCatalog:
        return DomainCatalog(
            entities=[
                "User",
                "Asset",
                "Position",
                "Watchlist",
                "PricePoint",
                "PriceSeries",
                "Evidence",
                "ResearchReport",
                "ModelPrediction",
                "RiskConclusion",
                "InvestmentRecommendation",
                "AuditRecord",
                "JudgeScore",
                "AnalysisRun",
            ],
            data_modes=[mode.value for mode in DataMode],
            data_source_types=[source.value for source in DataSourceType],
            mode_policies=self.mode_policy.describe_modes(),
            analysis_provider_config=AnalysisProviderConfig(
                market_data_provider=self.provider_settings.market_data_provider,
                evidence_provider=self.provider_settings.evidence_provider,
            ),
            analysis_providers=[
                AnalysisProviderSummary(
                    provider_name=descriptor.provider_name,
                    provider_version=descriptor.provider_version,
                    kind=descriptor.kind,
                )
                for descriptor in self.provider_registry.describe()
            ],
            principles=[
                "Every domain object carries status, schema version, entity version, and provenance.",
                "Reports are generated from immutable analysis runs rather than mutable current state.",
                "Synthetic and real data remain visible to users across the full chain.",
            ],
        )

    def build_demo_analysis_run(self) -> AnalysisRun:
        observed_at = datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc)
        provenance = Provenance(
            data_mode=DataMode.DEMO,
            source_type=DataSourceType.SYNTHETIC,
            source_name="demo-seed-v1",
            observed_at=observed_at,
            confidence=0.72,
            generation_chain=[
                GenerationLink(step="market_seed", producer="demo_generator", version="1.0.0"),
                GenerationLink(step="analysis_bundle", producer="judge_pipeline", version="1.0.0"),
            ],
        )

        asset = Asset(
            ticker="NVDA",
            name="NVIDIA Corporation",
            asset_type=AssetType.EQUITY,
            exchange="NASDAQ",
            provenance=provenance,
        )
        evidence = Evidence(
            asset_id=asset.id,
            evidence_type=EvidenceType.RESEARCH_NOTE,
            title="Synthetic growth narrative",
            summary="Demo evidence describing sustained datacenter demand and margin resilience.",
            collected_at=observed_at,
            provenance=provenance,
        )
        run = AnalysisRun(
            asset_id=asset.id,
            triggered_by="demo-mode",
            input_snapshot_ref="demo://snapshots/nvda-2026-07-03",
            input_snapshot_hash="demo-snapshot-hash",
            model_version="trend-ensemble@2026.07.0",
            reasoning_steps=[
                "resolve_intake_sources",
                "freeze_snapshot",
                "score_prediction",
                "evaluate_risk",
                "apply_judge_gate",
                "emit_recommendation",
            ],
            data_mode="demo",
            provider="demo-seed-v1 | synthetic-evidence-v1",
            as_of=observed_at,
            overrides=["demo fixture is synthetic and presentation-only"],
            synthetic_ratio=1.0,
            report_version="1.0.0",
            evidence_ids=[evidence.id],
            provenance=provenance,
        )
        prediction = ModelPrediction(
            asset_id=asset.id,
            analysis_run_id=run.id,
            model_name="trend-ensemble",
            model_version="2026.07.0",
            horizon="90d",
            signal="outperform",
            confidence=0.68,
            rationale="Synthetic ensemble favors demand momentum but remains bounded by demo confidence.",
            provenance=provenance,
        )
        risk = RiskConclusion(
            asset_id=asset.id,
            analysis_run_id=run.id,
            risk_level=RiskLevel.MEDIUM,
            summary="Valuation stretch and concentration risk remain visible even in demo mode.",
            evidence_ids=[evidence.id],
            provenance=provenance,
        )
        recommendation = InvestmentRecommendation(
            asset_id=asset.id,
            analysis_run_id=run.id,
            action=RecommendationAction.HOLD,
            conviction=0.58,
            reasoning="Judge gating prevents a stronger recommendation because demo evidence dominates the run.",
            guardrails=["Requires real data confirmation before changing the research observation."],
            provenance=provenance,
        )
        report = ResearchReport(
            asset_id=asset.id,
            analysis_run_id=run.id,
            title="NVDA Demo Analysis",
            thesis="A reproducible demo run should expose both upside thesis and synthetic-data caveats.",
            evidence_ids=[evidence.id],
            report_version="1.0.0",
            provenance=provenance,
        )
        judge = JudgeScore(
            analysis_run_id=run.id,
            score=0.61,
            verdict="warn",
            gating_reasons=[
                "Synthetic evidence share above threshold",
                "No live market verification attached to this run",
            ],
            provenance=provenance,
        )

        return run.model_copy(
            update={
                "prediction_ids": [prediction.id],
                "risk_conclusion_ids": [risk.id],
                "recommendation_ids": [recommendation.id],
                "report_ids": [report.id],
                "judge_score_ids": [judge.id],
            }
        )

    def build_demo_analysis_run_for_user(self, user: User) -> AnalysisRun:
        run = self.build_demo_analysis_run()
        return run.model_copy(update={"triggered_by": user.auth_subject})
