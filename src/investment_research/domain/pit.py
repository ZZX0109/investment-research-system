from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.data_tier import DataTier


class EventCoverageStatus(str, Enum):
    EVENTS_PRESENT = "events_present"
    CONFIRMED_NONE = "confirmed_none"
    UNSUPPORTED = "unsupported"
    FETCH_FAILED = "fetch_failed"
    PENDING_UPDATE = "pending_update"
    PARTIAL = "partial"

    @property
    def permits_zero_features(self) -> bool:
        return self in {self.EVENTS_PRESENT, self.CONFIRMED_NONE}


class PITDataQualityStatus(str, Enum):
    PASSED = "passed"
    DEGRADED = "degraded"
    FAILED = "failed"


class StandardEventRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    logical_event_id: str
    revision: int = Field(ge=1)
    active: bool = True
    symbol: str
    market: Literal["cn", "us", "hk", "jp"]
    provider: str
    event_type: str
    event_time: datetime
    first_published_at: datetime
    source_collected_at: datetime
    revised_at: datetime | None = None
    received_at: datetime
    persisted_at: datetime
    available_at: datetime
    raw_batch_id: UUID
    raw_hash: str = Field(min_length=64, max_length=64)
    normalized_hash: str = Field(min_length=64, max_length=64)
    payload_ref: str
    fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_visibility(self) -> "StandardEventRevision":
        if self.available_at < self.first_published_at:
            raise ValueError("event cannot be model-visible before first publication")
        if self.persisted_at < self.received_at:
            raise ValueError("persisted_at cannot precede received_at")
        return self


class HistoricalUniverseMembership(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    market: Literal["cn", "us", "hk", "jp"]
    exchange: str
    instrument_type: str
    effective_from: datetime
    effective_to: datetime | None = None
    listed_on: date
    delisted_on: date | None = None
    merger_date: date | None = None
    index_memberships: list[str] = Field(default_factory=list)
    industry: str | None = None
    size_bucket: str | None = None
    liquidity_bucket: str | None = None
    is_st: bool = False
    is_suspended: bool = False
    is_tradeable: bool = True
    available_at: datetime
    provider: str
    revision: int = Field(default=1, ge=1)


class CorporateActionRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    market: Literal["cn", "us", "hk", "jp"]
    action_type: Literal["split", "dividend", "rights", "merger", "delisting"]
    ex_date: date
    announced_at: datetime
    available_at: datetime
    revised_at: datetime | None = None
    revision: int = Field(default=1, ge=1)
    split_factor: float | None = Field(default=None, gt=0)
    cash_amount: float | None = None
    currency: str | None = None
    provider: str
    payload_hash: str = Field(min_length=64, max_length=64)


class TradingCostSchedule(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    market: Literal["cn", "us", "hk", "jp"]
    effective_from: date
    effective_to: date | None = None
    version: str
    commission_bps_buy: float = Field(ge=0)
    commission_bps_sell: float = Field(ge=0)
    stamp_tax_bps_sell: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    minimum_liquidity_amount: float = Field(default=0, ge=0)
    settlement_rule: str
    source_ref: str
    verified: bool = False

    @property
    def round_trip_cost(self) -> float:
        bps = (
            self.commission_bps_buy
            + self.commission_bps_sell
            + self.stamp_tax_bps_sell
            + 2 * self.slippage_bps
        )
        return bps / 10_000.0


class PITFeatureRecord(BaseModel):
    schema_version: str = "pit-feature-record-v1"
    data_tier: DataTier = DataTier.FORMAL_PIT
    symbol: str
    market: Literal["cn", "us", "hk", "jp"]
    decision_context: Literal["close_confirmed", "pre_open"]
    decision_time: datetime
    feature_cutoff: datetime
    market_snapshot_id: UUID
    market_snapshot_hash: str = Field(min_length=64, max_length=64)
    feature_version: str
    historical_universe_version: str
    adjustment_policy: str
    event_coverage_status: EventCoverageStatus
    data_quality_status: PITDataQualityStatus
    coverage_ratio: float = Field(ge=0, le=1)
    missing_mask: dict[str, bool] = Field(default_factory=dict)
    input_revision_ids: list[str] = Field(default_factory=list)
    features: dict[str, float | None]
    feature_hash: str = Field(min_length=64, max_length=64)
    data_quality_mask: dict[str, float] = Field(default_factory=dict)
    event_missing_mask: dict[str, float] = Field(default_factory=dict)
    provider_id: str | None = None
    revision_id: str | None = None
    source_delay_seconds: float | None = Field(default=None, ge=0)
    cache_state: str | None = None

    @classmethod
    def hash_features(cls, features: dict[str, float | None]) -> str:
        return hashlib.sha256(
            json.dumps(features, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @model_validator(mode="after")
    def validate_hash_and_events(self) -> "PITFeatureRecord":
        if self.feature_hash != self.hash_features(self.features):
            raise ValueError("feature_hash does not match features")
        if not self.event_coverage_status.permits_zero_features:
            event_names = [
                name
                for name in self.features
                if "event" in name or "news" in name or "filing" in name
            ]
            if event_names and not all(
                self.missing_mask.get(name, False) for name in event_names
            ):
                raise ValueError(
                    "unavailable event coverage must be represented as missing, not zero"
                )
        return self


class PITSampleRecord(BaseModel):
    schema_version: str = "pit-sample-record-v1"
    data_tier: DataTier = DataTier.FORMAL_PIT
    symbol: str
    market: Literal["cn", "us", "hk", "jp"]
    decision_context: Literal["close_confirmed", "pre_open"]
    decision_time: datetime
    feature_cutoff: datetime
    market_snapshot_id: UUID
    market_snapshot_hash: str = Field(min_length=64, max_length=64)
    feature_version: str
    label_version: str
    event_coverage_status: EventCoverageStatus
    data_quality_status: PITDataQualityStatus
    historical_universe_version: str
    adjustment_policy: str
    label_start: datetime | None = None
    label_end: datetime | None = None
    label_available: bool
    label_unavailable_reason: str | None = None
    entry_delay_trading_days: int = Field(default=0, ge=0, le=5)
    input_revision_ids: list[str] = Field(default_factory=list)
    missing_mask: dict[str, bool] = Field(default_factory=dict)
    features: dict[str, float | None]
    labels: dict[str, float | str | bool | None]
    sample_hash: str = Field(min_length=64, max_length=64)
    data_quality_mask: dict[str, float] = Field(default_factory=dict)
    event_missing_mask: dict[str, float] = Field(default_factory=dict)
    provider_id: str | None = None
    revision_id: str | None = None
    source_delay_seconds: float | None = Field(default=None, ge=0)
    cache_state: str | None = None


class PITDatasetManifest(BaseModel):
    schema_version: str = "pit-dataset-manifest-v1"
    data_tier: DataTier = DataTier.FORMAL_PIT
    id: UUID = Field(default_factory=uuid4)
    training_run_id: str
    market: Literal["cn", "us", "hk", "jp"]
    decision_context: Literal["close_confirmed", "pre_open"]
    task: str
    parquet_refs: list[str]
    # Immutable normalized inputs are catalogued separately from the feature
    # and sample layers.  They make every released training scope traceable
    # back to the exact standard price/event/universe/action revisions used to
    # build it, without forcing training readers to materialize raw data.
    standard_parquet_refs: list[str] = Field(default_factory=list)
    standard_layer_hash: str | None = Field(default=None, min_length=64, max_length=64)
    row_count: int = Field(ge=0)
    dataset_hash: str = Field(min_length=64, max_length=64)
    schema_hash: str = Field(min_length=64, max_length=64)
    feature_version: str
    label_version: str
    historical_universe_version: str
    leakage_report_hash: str = Field(min_length=64, max_length=64)
    quality_status: PITDataQualityStatus
    created_at: datetime


class PITDatasetPartition(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    market: Literal["cn", "us", "hk", "jp"]
    dataset: str
    schema_version: str
    trade_year: int
    object_ref: str
    payload_hash: str = Field(min_length=64, max_length=64)
    schema_hash: str = Field(min_length=64, max_length=64)
    row_count: int = Field(ge=0)
    quality_status: PITDataQualityStatus
    created_at: datetime


class ModelApprovalEvidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    training_run_id: str
    market: Literal["cn", "us", "hk", "jp"]
    decision_context: Literal["close_confirmed", "pre_open"]
    task: str
    evidence_type: str
    artifact_ref: str
    artifact_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime


class ShadowRunSession(BaseModel):
    """Immutable daily shadow evidence for one exact release scope."""

    id: UUID = Field(default_factory=uuid4)
    training_run_id: str
    market: Literal["cn", "us", "hk", "jp"]
    decision_context: Literal["close_confirmed", "pre_open"]
    task: str
    trade_date: date
    frozen_at: datetime
    market_snapshot_id: UUID
    market_snapshot_hash: str = Field(min_length=64, max_length=64)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    coverage_ratio: float = Field(ge=0, le=1)
    formal_synthetic_output_count: int = Field(default=0, ge=0)
    provider_switch_count: int = Field(default=0, ge=0)
    abstained: bool = False
    valid: bool
    invalid_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_session(self) -> "ShadowRunSession":
        expected_valid = (
            self.coverage_ratio >= 0.98
            and self.formal_synthetic_output_count == 0
            and bool(self.artifact_hashes)
            and not self.invalid_reasons
        )
        if self.valid != expected_valid:
            raise ValueError("shadow validity must be derived from immutable session evidence")
        return self


class ShadowRunOutcome(BaseModel):
    """Immutable realized-result backfill attached to a frozen shadow session."""

    id: UUID = Field(default_factory=uuid4)
    shadow_session_id: UUID
    horizon_sessions: Literal[1, 5, 20, 60]
    filled_at: datetime
    realized_return: float | None = None
    realized_max_drawdown: float | None = None
    mae: float | None = None
    mfe: float | None = None
    direction: Literal["up", "down", "flat", "unavailable"] = "unavailable"
    data_complete: bool = False
    suspended_during_window: bool = False
    limit_event_during_window: bool = False
    error_category: str | None = None
