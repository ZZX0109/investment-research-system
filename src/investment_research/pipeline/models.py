from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from investment_research.domain.models import (
    AnalysisRun,
    Asset,
    Evidence,
    InvestmentRecommendation,
    JudgeScore,
    ModelPrediction,
    PriceSeries,
    ResearchReport,
    RiskConclusion,
)
from investment_research.pipeline.run_views import RunDossierSummary, RunReplaySummary, RunScopeSummary
from investment_research.pipeline.source_meta import SourceLayerMetadata


class AnalysisSnapshot(BaseModel):
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = None
    decision_context: str = "close_confirmed"
    decision_time: datetime | None = None
    prediction_start_date: datetime | None = None
    feature_built_at: datetime | None = None
    asset_id: str
    asset_snapshot: Asset | None = None
    captured_at: datetime
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    data_modes: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    intake_strategy: str = "persisted_repository"
    price_provider_name: str = "unknown"
    price_provider_version: str = "unknown"
    price_provider_status: str = "unavailable"
    evidence_provider_name: str = "unknown"
    evidence_provider_version: str = "unknown"
    evidence_provider_status: str = "unavailable"
    event_coverage_status: str = "unknown"
    fallback_reasons: list[str] = Field(default_factory=list)
    latest_close: float | None = None
    latest_price_timestamp: datetime | None = None
    price_freshness_status: str = "unknown"
    evidence_freshness_status: str = "unknown"
    refresh_recommendation: str = "unknown"
    stale_reasons: list[str] = Field(default_factory=list)
    evidence_citation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    price_series_snapshot: list[PriceSeries] = Field(default_factory=list)
    evidence_snapshot: list[Evidence] = Field(default_factory=list)
    synthetic_share: float = 0.0
    real_share: float = 0.0
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)


class AnalysisBundle(BaseModel):
    asset: Asset
    run: AnalysisRun
    snapshot: AnalysisSnapshot
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)
    evidence: list[Evidence] = Field(default_factory=list)
    predictions: list[ModelPrediction] = Field(default_factory=list)
    risk_conclusions: list[RiskConclusion] = Field(default_factory=list)
    recommendations: list[InvestmentRecommendation] = Field(default_factory=list)
    judge_scores: list[JudgeScore] = Field(default_factory=list)
    reports: list[ResearchReport] = Field(default_factory=list)


class RunComparisonSummary(BaseModel):
    current_run_id: str
    baseline_run_id: str
    current_report_version: str = "pending"
    baseline_report_version: str = "pending"
    current_model_version: str = "n/a"
    baseline_model_version: str = "n/a"
    judge_score_delta: float = 0.0
    confidence_delta: float = 0.0
    latest_close_delta: float | None = None
    added_gates: list[str] = Field(default_factory=list)
    removed_gates: list[str] = Field(default_factory=list)
    added_fallbacks: list[str] = Field(default_factory=list)
    removed_fallbacks: list[str] = Field(default_factory=list)
    thesis_changed: bool = False
    current_source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)
    baseline_source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)


class RunLineageEntry(BaseModel):
    class EvidenceItem(BaseModel):
        id: str
        title: str
        summary: str
        source_type: str
        data_mode: str


    run_id: str
    created_at: datetime
    input_snapshot_ref: str
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    synthetic_share: float = 0.0
    real_share: float = 0.0
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    report_id: str | None = None
    report_title: str | None = None
    report_version: str | None = None
    report_thesis: str | None = None
    report_generated_at: datetime | None = None
    judge_verdict: str | None = None
    judge_score: float | None = None
    recommendation_action: str | None = None
    recommendation_reasoning: str | None = None
    model_version: str | None = None
    price_provider_status: str
    evidence_provider_status: str
    fallback_reasons: list[str] = Field(default_factory=list)
    gating_reasons: list[str] = Field(default_factory=list)
    audit_actions: list[str] = Field(default_factory=list)


class RunLineageTimeline(BaseModel):
    asset_id: str
    entries: list[RunLineageEntry] = Field(default_factory=list)
