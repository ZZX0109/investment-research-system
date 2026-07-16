from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.trusted_market import CacheState, QualityStatus
from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.domain.pit import EventCoverageStatus


class DataStatus(BaseModel):
    data_tier: DataTier = DataTier.RESEARCH_PIT
    research_only: bool = True
    historical_visibility_assumption: str | None = RESEARCH_VISIBILITY_ASSUMPTION
    as_of: datetime
    latest_source_time: datetime | None = None
    fetched_at: datetime | None = None
    received_at: datetime | None = None
    persisted_at: datetime | None = None
    latency_seconds: float | None = Field(default=None, ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    quality_status: QualityStatus
    cache_state: CacheState
    event_coverage_status: EventCoverageStatus = EventCoverageStatus.UNSUPPORTED
    degraded_symbols: list[str] = Field(default_factory=list)
    provider_chain: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tier_semantics(self) -> "DataStatus":
        if self.data_tier == DataTier.FORMAL_PIT:
            if self.research_only or self.historical_visibility_assumption is not None:
                raise ValueError("formal_pit status cannot carry research-only visibility semantics")
        elif not self.research_only:
            raise ValueError("non-formal data status must be research-only")
        return self


class ModelTaskStatus(BaseModel):
    task: Literal[
        "direction_1d",
        "direction_5d",
        "direction_20d",
        "return_20d",
        "drawdown_20d",
        "drawdown_60d",
        "drawdown_120d",
        "volatility_20d",
        "volatility_60d",
        "volatility_120d",
    ]
    status: Literal["approved", "fallback", "research_only", "unavailable", "abstain"]
    model_name: str | None = None
    model_version: str | None = None
    manifest_version: str | None = None
    gating_reasons: list[str] = Field(default_factory=list)
    fallback_from: str | None = None
    artifact_hash_verified: bool | None = None


class DirectionDistribution(BaseModel):
    horizon_days: Literal[1, 5]
    up: float = Field(ge=0, le=1)
    down: float = Field(ge=0, le=1)
    flat: float = Field(ge=0, le=1)
    raw_up: float | None = Field(default=None, ge=0, le=1)
    raw_down: float | None = Field(default=None, ge=0, le=1)
    raw_flat: float | None = Field(default=None, ge=0, le=1)
    confidence_interval: tuple[float, float] | None = None

    @model_validator(mode="after")
    def probabilities_sum_to_one(self) -> "DirectionDistribution":
        if abs((self.up + self.down + self.flat) - 1.0) > 1e-6:
            raise ValueError("direction probabilities must sum to one")
        return self


class ReturnDistribution(BaseModel):
    horizon_days: Literal[20] = 20
    p10: float
    p50: float
    p90: float
    confidence_interval: tuple[float, float] | None = None

    @model_validator(mode="after")
    def ordered(self) -> "ReturnDistribution":
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("return quantiles must be ordered")
        return self


class DrawdownDistribution(BaseModel):
    horizon_days: Literal[20] = 20
    threshold: float = -0.08
    threshold_probability: float = Field(ge=0, le=1)
    raw_threshold_probability: float | None = Field(default=None, ge=0, le=1)
    confidence_interval: tuple[float, float] | None = None
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None


class ResearchForecastBundle(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_run_id: UUID
    asset_id: UUID
    market: Literal["cn", "us", "hk", "jp"] | None = None
    data_tier: DataTier = DataTier.RESEARCH_PIT
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = None
    decision_context: Literal["close_confirmed", "pre_open"] = "close_confirmed"
    decision_time: datetime | None = None
    feature_built_at: datetime | None = None
    as_of: datetime
    adjustment_policy: str | None = None
    trading_status: str | None = None
    direction_1d: DirectionDistribution | None = None
    direction_5d: DirectionDistribution | None = None
    return_20d: ReturnDistribution | None = None
    drawdown_20d: DrawdownDistribution | None = None
    evidence_coverage: float = Field(ge=0, le=1)
    feature_coverage: float = Field(ge=0, le=1)
    data_status: DataStatus
    tasks: list[ModelTaskStatus]
    gating_reasons: list[str] = Field(default_factory=list)
    influence_facts: list[str] = Field(default_factory=list)
    model_disagreement: dict[str, float] = Field(default_factory=dict)
    # These top-level states are the UI contract.  ``tasks`` remains the
    # detailed per-task evidence, while these fields make an unavailable or
    # abstained result explicit instead of requiring clients to infer it from
    # missing probability objects.
    training_status: Literal["complete", "partial", "blocked", "unavailable"] = "partial"
    model_status: Literal["approved", "fallback", "research_only", "unavailable", "abstain", "blocked"] = "unavailable"
    prediction_status: Literal["approved", "fallback", "research_only", "unavailable", "abstain", "blocked"] = "unavailable"
    evidence_status: Literal["valid", "partial", "missing", "blocked"] = "partial"
    blocking_reasons: list[str] = Field(default_factory=list)
    abstain_reasons: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "unavailable"] = "unavailable"
    explanation_is_causal: bool = False
    abstained: bool = False

    @model_validator(mode="after")
    def research_tier_cannot_claim_formal_output(self) -> "ResearchForecastBundle":
        if self.data_status.data_tier != self.data_tier:
            raise ValueError("forecast bundle and data status must have the same data_tier")
        if self.data_tier == DataTier.RESEARCH_PIT:
            if any(task.status in {"approved", "fallback"} for task in self.tasks):
                raise ValueError("research_pit forecasts cannot claim approved or fallback tasks")
        return self


class TaskApprovalManifest(BaseModel):
    schema_version: str = "research-task-manifest-v4"
    task: Literal[
        "direction_1d",
        "direction_5d",
        "direction_20d",
        "return_20d",
        "drawdown_20d",
        "drawdown_60d",
        "drawdown_120d",
        "volatility_20d",
        "volatility_60d",
        "volatility_120d",
    ]
    decision_context: Literal["close_confirmed", "pre_open"] = "close_confirmed"
    status: Literal["approved", "research_only", "rejected"] = "research_only"
    deployment_ready: bool = False
    # This manifest is the formal model-registration contract.  Free-data
    # writers must explicitly opt into ``research_pit``; retaining the formal
    # default keeps older formal manifests and the formal release matrix
    # backward compatible while still making a research manifest impossible to
    # approve.
    data_tier: DataTier = DataTier.FORMAL_PIT
    model_name: str
    model_version: str
    baseline_name: str
    label_policy_version: str
    feature_contract_version: str = "investment-risk-features-v2"
    approved_at: datetime | None = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    # Every scope-level approval report is content-addressed separately from
    # runtime artifacts.  This prevents a deployable manifest from referring
    # only to a convenient subset of the training evidence.
    approval_evidence_hashes: dict[str, str] = Field(default_factory=dict)
    data_snapshot_hash: str | None = None
    code_commit: str | None = None
    dependency_lock_hash: str | None = None
    approval_id: str | None = None
    rollback_version: str | None = None
    applicable_markets: list[str] = Field(default_factory=lambda: ["cn"])
    market: Literal["cn", "us", "hk", "jp"]
    training_run_id: str
    dataset_manifest_hash: str
    leakage_report_hash: str
    holdout_12m_report_hash: str
    stress_6m_report_hash: str
    ablation_report_hash: str
    calibration_method: Literal["platt", "isotonic", "beta"] | None = None
    shadow_run_sessions: int = 0
    critical_data_coverage: float = Field(default=0.0, ge=0, le=1)
    formal_synthetic_output_count: int = 0
    leakage_error_count: int = 0
    calibration_leakage_error_count: int = 0
    holdout_12m_passed: bool = False
    stress_6m_passed: bool = False
    market_regime_sample_gate_passed: bool = False
    cost_gate_passed: bool = False
    gating_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def research_tier_cannot_be_deployed(self) -> "TaskApprovalManifest":
        if self.data_tier != DataTier.FORMAL_PIT and (
            self.status == "approved" or self.deployment_ready
        ):
            raise ValueError("non-formal data tiers cannot be approved or deployment ready")
        return self


class ResearchRosterEntry(BaseModel):
    role: Literal["primary", "fallback", "challenger"]
    task: Literal["direction_1d", "direction_5d", "return_20d", "drawdown_20d"]
    candidate_name: str
    component: Literal["primary", "comparator"] = "primary"
    artifact_ref: str
    artifact_hashes: dict[str, str]
    report_hashes: dict[str, str]
    data_tier: DataTier = DataTier.RESEARCH_PIT
    status: Literal["research_only"] = "research_only"
    deployment_ready: Literal[False] = False


class ResearchModelRoster(BaseModel):
    schema_version: str = "cn-research-model-roster-v2"
    data_tier: DataTier = DataTier.RESEARCH_PIT
    status: Literal["research_only"] = "research_only"
    deployment_ready: Literal[False] = False
    market: Literal["cn"] = "cn"
    decision_context: Literal["close_confirmed", "pre_open"]
    cohort: Literal["cn_equity_core", "cn_etf_benchmark"]
    cohort_version: str
    task: Literal["direction_1d", "direction_5d", "return_20d", "drawdown_20d"]
    training_run_id: str
    dataset_hash: str = Field(min_length=64, max_length=64)
    market_snapshot_hash: str = Field(min_length=64, max_length=64)
    feature_contract_version: str = "investment-risk-features-v2"
    code_hash: str = Field(min_length=64, max_length=64)
    dependency_hash: str = Field(min_length=64, max_length=64)
    primary: ResearchRosterEntry
    fallback: ResearchRosterEntry
    challengers: list[ResearchRosterEntry] = Field(default_factory=list)
    sequence_challengers: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    abstain_rules: list[str] = Field(default_factory=list)
    roster_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_roster(self) -> "ResearchModelRoster":
        if self.primary.role != "primary" or self.fallback.role != "fallback":
            raise ValueError("research roster requires one primary and one fallback role")
        entries = [self.primary, self.fallback, *self.challengers]
        if any(item.task != self.task for item in entries):
            raise ValueError("research roster cannot mix tasks")
        if any(item.role != "challenger" for item in self.challengers):
            raise ValueError("research roster challenger role mismatch")
        if len({item.candidate_name for item in entries}) != len(entries):
            raise ValueError("research roster candidates must be unique")
        return self
