from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator, computed_field

from investment_research.domain.base import DomainEntity, GenerationLink, Provenance
from investment_research.domain.enums import (
    AssetType,
    EvidenceType,
    JudgeVerdict,
    RecommendationAction,
    RiskLevel,
)


class User(DomainEntity):
    email: str
    display_name: str
    auth_subject: str


class Asset(DomainEntity):
    ticker: str
    name: str
    asset_type: AssetType
    currency: str = "USD"
    exchange: str | None = None


class Position(DomainEntity):
    user_id: UUID
    asset_id: UUID
    quantity: float
    cost_basis: float
    opened_at: datetime


class Watchlist(DomainEntity):
    user_id: UUID
    name: str
    asset_ids: list[UUID] = Field(default_factory=list)


class PricePoint(DomainEntity):
    asset_id: UUID
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None
    turnover_rate: float | None = None
    margin_financing_balance: float | None = None
    market_breadth_5d: float | None = None
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_suspended: bool = False


class PriceSeries(DomainEntity):
    asset_id: UUID
    interval: Literal["1m", "5m", "1h", "1d", "1w"]
    series_role: Literal["asset", "benchmark", "sector", "style"] = "asset"
    reference_symbol: str | None = None
    points: list[PricePoint] = Field(default_factory=list)


class Evidence(DomainEntity):
    asset_id: UUID
    asset_refs: list[UUID] = Field(default_factory=list)
    evidence_type: EvidenceType
    title: str
    summary: str
    source_url: str | None = None
    collected_at: datetime
    published_at: datetime | None = None
    # Explicit public-availability time for PIT Agent evidence.  Legacy
    # records may omit it; in that case ``published_at`` is the only allowed
    # visibility fallback, never ``collected_at``.
    available_at: datetime | None = None
    # Legacy in-process fixtures historically treated ``collected_at`` as a
    # verified public time. API ingestion explicitly sets this false when no
    # publication/availability timestamp is supplied, so formal PIT paths can
    # reject the ambiguity without breaking old replay records.
    publication_time_verified: bool = True
    payload_ref: str | None = None
    event_type: str | None = None
    direction: str | None = None
    intensity: str | None = None
    source_tier: str | None = None
    surprise_bucket: str | None = None
    guidance_bucket: str | None = None
    filing_type: str | None = None
    raw_hash: str | None = None
    normalized_hash: str | None = None
    data_version: str | None = None
    related_ids: list[UUID] = Field(default_factory=list)

    @computed_field
    def lineage(self) -> list[GenerationLink]:
        return self.provenance.generation_chain

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_related_ids(cls, values: dict[str, object]) -> dict[str, object]:
        if not isinstance(values, dict):
            return values
        if "asset_refs" not in values and "related_ids" in values:
            values = {**values, "asset_refs": values["related_ids"]}
        return values

    @model_validator(mode="after")
    def _normalize_asset_refs(self) -> "Evidence":
        normalized = [asset_id for asset_id in self.asset_refs]
        if not normalized:
            normalized = [self.asset_id]
        elif self.asset_id not in normalized:
            normalized.append(self.asset_id)
        self.asset_refs = normalized
        self.related_ids = normalized
        return self


class ResearchReport(DomainEntity):
    asset_id: UUID
    analysis_run_id: UUID
    title: str
    thesis: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    report_version: str
    body_markdown: str | None = None


class ModelDiagnostic(BaseModel):
    feature_coverage: float = Field(ge=0.0, le=1.0)
    missing_features: list[str] = Field(default_factory=list)
    out_of_range_features: list[str] = Field(default_factory=list)
    drift_score: float = Field(ge=0.0, le=1.0)
    provider_missing_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class ModelPrediction(DomainEntity):
    asset_id: UUID
    analysis_run_id: UUID
    model_name: str
    model_version: str
    horizon: str
    signal: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    risk_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    model_status: str = "unknown"
    feature_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    missing_features: list[str] = Field(default_factory=list)
    deployment_approved: bool = False
    manifest_version: str | None = None
    target_name: str | None = None
    inference_warnings: list[str] = Field(default_factory=list)
    diagnostic: ModelDiagnostic | None = None


class RiskConclusion(DomainEntity):
    asset_id: UUID
    analysis_run_id: UUID
    risk_level: RiskLevel
    summary: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    stale_after: datetime | None = None


class InvestmentRecommendation(DomainEntity):
    asset_id: UUID
    analysis_run_id: UUID
    action: RecommendationAction
    conviction: float = Field(ge=0.0, le=1.0)
    reasoning: str
    guardrails: list[str] = Field(default_factory=list)


class AuditRecord(DomainEntity):
    actor: str
    action: str
    target_type: str
    target_id: UUID
    details: dict[str, str] = Field(default_factory=dict)


class JudgeScore(DomainEntity):
    analysis_run_id: UUID
    score: float = Field(ge=0.0, le=1.0)
    verdict: JudgeVerdict
    gating_reasons: list[str] = Field(default_factory=list)


class AnalysisRun(DomainEntity):
    asset_id: UUID
    triggered_by: str
    input_snapshot_ref: str
    input_snapshot_hash: str | None = None
    model_version: str | None = None
    reasoning_steps: list[str] = Field(default_factory=list)
    data_mode: str | None = None
    provider: str | None = None
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    report_version: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    prediction_ids: list[UUID] = Field(default_factory=list)
    risk_conclusion_ids: list[UUID] = Field(default_factory=list)
    recommendation_ids: list[UUID] = Field(default_factory=list)
    report_ids: list[UUID] = Field(default_factory=list)
    judge_score_ids: list[UUID] = Field(default_factory=list)
    refresh_run_id: UUID | None = None
    feature_contract_version: str | None = None
    feature_vector_hash: str | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    historical_scenario_ids: list[UUID] = Field(default_factory=list)
    portfolio_snapshot_id: UUID | None = None
    audit_id: UUID | None = None


class RefreshRun(DomainEntity):
    asset_id: UUID
    triggered_by: str
    refresh_mode: Literal["online", "cache", "auto"] = "auto"
    state: Literal["running", "succeeded", "degraded", "failed"] = "running"
    started_at: datetime
    completed_at: datetime | None = None
    provider_attempts: list[dict[str, Any]] = Field(default_factory=list)
    cache_hit: bool = False
    price_count: int = 0
    evidence_count: int = 0
    failure_reasons: list[str] = Field(default_factory=list)
    data_version: str | None = None


class HistoricalScenario(DomainEntity):
    asset_id: UUID
    analysis_run_id: UUID | None = None
    as_of: datetime
    candidate_date: datetime
    similarity: float = Field(ge=0.0, le=1.0)
    regime: str
    feature_snapshot: dict[str, float] = Field(default_factory=dict)
    return_1w: float | None = None
    return_1m: float | None = None
    return_3m: float | None = None
    max_drawdown_3m: float | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)


class PortfolioRiskSnapshot(DomainEntity):
    user_id: UUID
    as_of: datetime
    total_market_value: float = 0.0
    concentration_hhi: float = 0.0
    volatility_20d: float | None = None
    max_drawdown: float | None = None
    market_exposure: dict[str, float] = Field(default_factory=dict)
    industry_exposure: dict[str, float] = Field(default_factory=dict)
    position_risk_contributions: dict[str, float] = Field(default_factory=dict)
    correlation_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    covariance_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    marginal_risk_contributions: dict[str, float] = Field(default_factory=dict)
    liquidity_exposure: dict[str, float] = Field(default_factory=dict)
    stress_scenarios: dict[str, float] = Field(default_factory=dict)
    stress_scenario_source: str = "illustrative_not_historical"
    warnings: list[str] = Field(default_factory=list)


class ReportSchedule(DomainEntity):
    user_id: UUID
    asset_id: UUID | None = None
    frequency: Literal["manual", "daily", "weekly", "monthly", "event_triggered"] = (
        "manual"
    )
    enabled: bool = True
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    timezone: str = "Asia/Shanghai"


class DocumentArtifact(DomainEntity):
    user_id: UUID
    asset_id: UUID | None = None
    filename: str
    content_type: str
    storage_path: str
    source_url: str | None = None
    sha256: str
    page_count: int = 0
    parse_status: Literal["pending", "parsed", "needs_visual_review", "failed"] = (
        "pending"
    )
    text_summary: str | None = None
    tables: list[dict[str, Any]] = Field(default_factory=list)
    figures: list[dict[str, Any]] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class ResearchAudit(DomainEntity):
    analysis_run_id: UUID
    verdict: JudgeVerdict
    score: float = Field(ge=0.0, le=1.0)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    contrary_evidence_ids: list[UUID] = Field(default_factory=list)
    evidence_budget: int = 12
    rounds_used: int = 1
    token_estimate: int = 0
    summary: str


class ObservationMilestone(BaseModel):
    horizon_days: Literal[1, 5, 20, 60]
    evaluated_at: datetime
    realized_return: float
    realized_max_drawdown: float
    maximum_adverse_excursion: float
    maximum_favorable_excursion: float
    realized_direction: Literal["up", "down", "flat"]
    data_complete: bool = True
    suspended_days: int = 0
    limit_up_days: int = 0
    limit_down_days: int = 0


class PaperObservation(DomainEntity):
    asset_id: UUID
    analysis_run_id: UUID
    prediction_as_of: datetime
    horizon_days: int = 20
    predicted_risk: float | None = None
    prediction_price: float | None = None
    latest_price: float | None = None
    cumulative_return: float | None = None
    observed_trading_days: int = 0
    outcome: Literal["pending", "risk_hit", "risk_miss"] = "pending"
    settlement_source: str | None = None
    realized_max_drawdown: float | None = None
    evaluation_due_at: datetime
    evaluated_at: datetime | None = None
    state: Literal["pending", "evaluated", "expired"] = "pending"
    forecast_bundle_id: UUID | None = None
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = None
    decision_context: Literal["close_confirmed", "pre_open"] = "close_confirmed"
    model_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    data_version: str | None = None
    evidence_snapshot_hash: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    frozen_probabilities: dict[str, Any] = Field(default_factory=dict)
    gate_conclusion: str | None = None
    abstained: bool = False
    abstain_reasons: list[str] = Field(default_factory=list)
    milestones: dict[str, ObservationMilestone] = Field(default_factory=dict)
    error_category: Literal[
        "pending", "correct", "data_error", "direction_error", "risk_level_error",
        "event_omission", "evidence_explanation_error", "evidence_misjudgment",
        "correct_abstain", "incorrect_abstain",
    ] = "pending"


def build_default_provenance(
    *,
    data_mode,
    source_type,
    source_name: str,
    observed_at: datetime,
) -> Provenance:
    return Provenance(
        data_mode=data_mode,
        source_type=source_type,
        source_name=source_name,
        observed_at=observed_at,
    )
