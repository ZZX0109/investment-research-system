from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from investment_research.domain.models import ModelDiagnostic
from investment_research.pipeline.source_meta import SourceLayerMetadata


class RunObservationOutcome(BaseModel):
    run_id: str
    predicted_risk: float | None = None
    prediction_price: float | None = None
    latest_price: float | None = None
    cumulative_return: float | None = None
    realized_max_drawdown: float | None = None
    observed_trading_days: int = 0
    remaining_trading_days: int = 20
    outcome: str = "pending"
    judge_verdict: str | None = None
    evaluation_due_at: datetime


class RunMarketObservation(BaseModel):
    asset_id: str
    market_status: str
    provider: str
    provider_status: str
    latest_price: float | None = None
    latest_price_at: datetime | None = None
    last_close: float | None = None
    stale: bool = True
    degraded_reasons: list[str] = Field(default_factory=list)
    outcomes: list[RunObservationOutcome] = Field(default_factory=list)


class RunDirectionalForecastStatus(BaseModel):
    status: str
    gating_reasons: list[str] = Field(default_factory=list)


class RunReplaySummary(BaseModel):
    run_id: str
    asset_id: str
    asset_ticker: str
    asset_name: str
    created_at: datetime
    captured_at: datetime
    report_version: str = "pending"
    report_title: str = "Pending fixed report"
    judge_verdict: str = "n/a"
    recommendation_action: str = "n/a"
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    data_mode: str
    source_type: str
    source_name: str
    observed_at: datetime
    confidence: float = 0.0
    synthetic_share: float = 0.0
    evidence_count: int = 0
    report_count: int = 0
    gate_count: int = 0
    fallback_count: int = 0
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)
    market_observation: RunMarketObservation | None = None
    directional_forecast_status: RunDirectionalForecastStatus | None = None


class RunDossierSummary(BaseModel):
    run_id: str
    asset_ticker: str
    report_title: str = "Pending fixed report"
    report_version: str = "pending"
    report_thesis: str = "No fixed report has been generated from this run yet."
    report_body_markdown: str | None = None
    judge_verdict: str = "n/a"
    judge_score: float = 0.0
    gate_count: int = 0
    gating_reasons: list[str] = Field(default_factory=list)
    fallback_count: int = 0
    fallback_reasons: list[str] = Field(default_factory=list)
    recommendation_action: str = "n/a"
    recommendation_reasoning: str = "No recommendation available."
    recommendation_guardrails: list[str] = Field(default_factory=list)
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    confidence: float = 0.0
    model_name: str = "n/a"
    model_version: str = "n/a"
    model_status: str = "unknown"
    risk_probability: float | None = None
    feature_coverage: float = 0.0
    missing_features: list[str] = Field(default_factory=list)
    deployment_approved: bool = False
    inference_warnings: list[str] = Field(default_factory=list)
    model_diagnostic: ModelDiagnostic | None = None
    synthetic_share: float = 0.0
    risk_level: str = "n/a"
    risk_summary: str = "No risk conclusion generated for this run."
    risk_stale_after: datetime | None = None
    price_freshness_status: str = "unknown"
    evidence_freshness_status: str = "unknown"
    refresh_recommendation: str = "unknown"
    stale_reasons: list[str] = Field(default_factory=list)
    evidence_citation_ids: list[str] = Field(default_factory=list)
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)
    market_observation: RunMarketObservation | None = None
    directional_forecast_status: RunDirectionalForecastStatus | None = None


class RunScopeSummary(BaseModel):
    run_id: str
    asset_id: str
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    report_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    report_count: int = 0
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)


class RunLineageDetailSummary(BaseModel):
    run_id: str
    asset_id: str
    input_snapshot_ref: str
    intake_strategy: str
    captured_at: datetime
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    data_modes: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    latest_close: float | None = None
    price_provider_name: str = "unknown"
    price_provider_version: str = "unknown"
    price_provider_status: str = "unavailable"
    evidence_provider_name: str = "unknown"
    evidence_provider_version: str = "unknown"
    evidence_provider_status: str = "unavailable"
    judge_verdict: str = "n/a"
    judge_score: float = 0.0
    recommendation_action: str = "n/a"
    recommendation_reasoning: str = "No recommendation reasoning."
    model_confidence: float = 0.0
    model_name: str = "n/a"
    model_version: str = "n/a"
    model_status: str = "unknown"
    risk_probability: float | None = None
    feature_coverage: float = 0.0
    missing_features: list[str] = Field(default_factory=list)
    deployment_approved: bool = False
    inference_warnings: list[str] = Field(default_factory=list)
    model_diagnostic: ModelDiagnostic | None = None
    report_version: str = "pending"
    report_title: str | None = None
    fallback_reasons: list[str] = Field(default_factory=list)
    price_freshness_status: str = "unknown"
    evidence_freshness_status: str = "unknown"
    refresh_recommendation: str = "unknown"
    stale_reasons: list[str] = Field(default_factory=list)
    evidence_citation_ids: list[str] = Field(default_factory=list)
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)


class RunRefreshStatusSummary(BaseModel):
    run_id: str
    asset_id: str
    report_version: str = "pending"
    judge_verdict: str = "n/a"
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    price_freshness_status: str = "unknown"
    evidence_freshness_status: str = "unknown"
    refresh_recommendation: str = "unknown"
    stale_reasons: list[str] = Field(default_factory=list)
    evidence_citation_ids: list[str] = Field(default_factory=list)
    source_meta: SourceLayerMetadata = Field(default_factory=SourceLayerMetadata)


class AssetRefreshStatusSummary(BaseModel):
    asset_id: str
    latest_run_id: str | None = None
    has_run: bool = False
    status: str = "missing_run"
    mode: str | None = None
    provider: str | None = None
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
    price_freshness_status: str = "unknown"
    evidence_freshness_status: str = "unknown"
    refresh_recommendation: str = "create_first_run"
    stale_reasons: list[str] = Field(default_factory=list)
    evidence_citation_ids: list[str] = Field(default_factory=list)
    source_meta: SourceLayerMetadata | None = None
