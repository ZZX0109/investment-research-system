from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.trusted_market import CacheState, QualityStatus


class DataStatus(BaseModel):
    as_of: datetime
    latest_source_time: datetime | None = None
    fetched_at: datetime | None = None
    received_at: datetime | None = None
    persisted_at: datetime | None = None
    latency_seconds: float | None = Field(default=None, ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    quality_status: QualityStatus
    cache_state: CacheState
    degraded_symbols: list[str] = Field(default_factory=list)
    provider_chain: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


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
    explanation_is_causal: bool = False
    abstained: bool = False


class TaskApprovalManifest(BaseModel):
    schema_version: str = "research-task-manifest-v3"
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
    model_name: str
    model_version: str
    baseline_name: str
    label_policy_version: str
    feature_contract_version: str = "investment-risk-features-v2"
    approved_at: datetime | None = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
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
    gating_reasons: list[str] = Field(default_factory=list)
