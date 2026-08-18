from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.data_tier import DataTier


QualityStatus = Literal["passed", "degraded", "failed"]
CacheState = Literal["fresh", "stale_usable", "expired", "unavailable"]
ProviderDataStatus = Literal["real_fresh", "real_stale", "backfilled", "synthetic", "unavailable"]
JobState = Literal["queued", "running", "retrying", "succeeded", "degraded", "failed", "cancelled"]
JobType = Literal[
    "security_master",
    "daily_close_confirmation",
    "price_backfill",
    "announcement_incremental",
    "news_incremental",
    "financial_update",
    "minute_collection",
    "model_training",
    "model_evaluation",
    "model_approval",
    # Research-only lifecycle jobs.  These are deliberately separate from
    # formal training/approval jobs and are always persisted as evidence for
    # the public-data research path.
    "research_daily_close",
    "research_weekly_monitor",
    "research_monthly_training",
    "research_quarterly_challenger",
    "research_label_backfill",
    "research_model_promotion",
    "research_model_rollback",
    "knowledge_daily_incremental",
    "knowledge_weekly_audit",
    "knowledge_monthly_reindex",
    "knowledge_historical_backfill",
    "knowledge_document_fetch",
]


class SecurityMasterRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    exchange: Literal["XSHG", "XSHE", "XBSE", "XNYS", "XNAS", "XHKG", "XTKS"]
    instrument_type: Literal["equity", "etf", "index"]
    name: str
    listed_on: date
    delisted_on: date | None = None
    industry: str | None = None
    board: str | None = None
    currency: str
    lot_size: int = Field(default=100, gt=0)
    calendar_code: str = "XSHG"
    source_time: datetime
    ingest_time: datetime
    available_at: datetime


class SecurityStateRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    security_id: UUID
    effective_from: datetime
    effective_to: datetime | None = None
    is_st: bool = False
    is_suspended: bool = False
    is_tradeable: bool = True
    limit_up_rate: float = Field(default=0.10, ge=0, le=1)
    limit_down_rate: float = Field(default=0.10, ge=0, le=1)
    adjustment_policy: Literal["raw", "qfq", "hfq"] = "raw"
    industry: str | None = None
    board: str | None = None
    source_time: datetime
    ingest_time: datetime
    available_at: datetime


class RawDataBatch(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    data_tier: DataTier = DataTier.FORMAL_PIT
    time_semantics: Literal[
        "formal_pit", "research_collection_time_semantics", "legacy_time_semantics",
        "test_fixture",
    ] = "formal_pit"
    provider: str
    request_id: str
    dataset: str
    payload_ref: str
    payload_hash: str = Field(min_length=64, max_length=64)
    schema_version: str
    symbol: str | None = None
    interval: str | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    market_session: str | None = None
    fetched_at: datetime
    source_time: datetime | None = None
    exchange_time: datetime | None = None
    received_at: datetime | None = None
    persisted_at: datetime | None = None
    available_at: datetime
    quality_status: QualityStatus = "passed"
    quality_issues: list[str] = Field(default_factory=list)


class VersionedMarketBar(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    raw_batch_id: UUID
    symbol: str
    provider: str
    interval: Literal["1m", "5m", "15m", "1d"]
    bar_start: datetime
    trade_date: date
    calendar_code: Literal["XSHG", "XSHE", "XBSE", "XNYS", "XNAS", "XHKG", "XTKS"] = "XSHG"
    adjustment_mode: Literal["raw", "qfq", "hfq"] = "raw"
    adjustment_factor: float = Field(default=1.0, gt=0)
    revision: int = Field(default=1, ge=1)
    active: bool = True
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)
    turnover_rate: float | None = Field(default=None, ge=0)
    previous_close: float | None = Field(default=None, gt=0)
    limit_up: float | None = Field(default=None, gt=0)
    limit_down: float | None = Field(default=None, gt=0)
    is_suspended: bool = False
    is_st: bool = False
    is_one_price_limit: bool = False
    is_tradeable: bool = True
    hit_limit_up: bool = False
    hit_limit_down: bool = False
    source_time: datetime
    exchange_time: datetime | None = None
    received_at: datetime | None = None
    persisted_at: datetime | None = None
    ingest_time: datetime
    available_at: datetime
    as_of: datetime
    quality_status: QualityStatus = "passed"
    normalized_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "VersionedMarketBar":
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC ordering")
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        return self


class MarketSnapshotEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    raw_batch_id: UUID | None = None
    symbol: str
    provider: str
    event_time: datetime
    source_time: datetime
    ingest_time: datetime
    available_at: datetime
    as_of: datetime
    latest_price: float = Field(gt=0)
    previous_close: float | None = Field(default=None, gt=0)
    volume: float | None = Field(default=None, ge=0)
    amount: float | None = Field(default=None, ge=0)
    bid_price: float | None = Field(default=None, gt=0)
    ask_price: float | None = Field(default=None, gt=0)
    high: float | None = Field(default=None, gt=0)
    low: float | None = Field(default=None, gt=0)
    turnover_rate: float | None = Field(default=None, ge=0)
    is_suspended: bool = False
    quality_status: QualityStatus = "passed"
    payload_hash: str = Field(min_length=64, max_length=64)


class ProviderAttempt(BaseModel):
    provider: str
    state: Literal["succeeded", "failed", "skipped"]
    started_at: datetime
    completed_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None


class ProviderCoverage(BaseModel):
    provider: str
    dataset: str
    checked_from: datetime
    checked_until: datetime
    source_time: datetime | None = None
    fetched_at: datetime
    status: Literal["complete", "partial", "failed"]
    coverage_ratio: float = Field(ge=0, le=1)
    authorized: bool = False
    sla_name: str | None = None
    fallback_used: bool = False
    issues: list[str] = Field(default_factory=list)


class MarketSnapshot(BaseModel):
    """Immutable aggregate shared by training, inference, approval and replay."""

    id: UUID = Field(default_factory=uuid4)
    data_tier: DataTier = DataTier.FORMAL_PIT
    symbol: str
    decision_context: Literal["close_confirmed", "pre_open"]
    trade_date: date
    decision_time: datetime
    prediction_start_date: date
    feature_built_at: datetime
    security_universe_version: str
    trading_calendar_version: str
    adjustment_policy: Literal["raw", "qfq", "hfq"]
    data_version: str
    bar_ids: list[UUID] = Field(default_factory=list)
    snapshot_event_ids: list[UUID] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    provider_coverage: list[ProviderCoverage] = Field(default_factory=list)
    quality_status: QualityStatus
    quality_issues: list[str] = Field(default_factory=list)
    content_hash: str = Field(min_length=64, max_length=64)


class IngestionJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    idempotency_key: str
    job_type: JobType
    state: JobState = "queued"
    priority: int = Field(default=100, ge=0)
    symbols: list[str] = Field(default_factory=list)
    requested_by: str
    created_at: datetime
    scheduled_for: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    next_attempt_at: datetime | None = None
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    cancel_requested: bool = False
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list)
    quality_status: QualityStatus | None = None
    quality_issues: list[str] = Field(default_factory=list)
    coverage_ratio: float = Field(default=0.0, ge=0, le=1)
    degraded_symbols: list[str] = Field(default_factory=list)
    duplicate_count: int = Field(default=0, ge=0)
    revision_count: int = Field(default=0, ge=0)
    provider_switch_count: int = Field(default=0, ge=0)
    artifact_version: str | None = None
    latest_source_time: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    # Optional research lifecycle scope.  Keeping these fields in the
    # immutable JSON payload preserves compatibility with existing SQLite and
    # PostgreSQL ingestion tables without a destructive migration.
    market: str | None = None
    decision_context: str | None = None
    trade_date: date | None = None
    cutoff_time: datetime | None = None
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = None
    dataset_hash: str | None = None
    training_run_id: str | None = None
    candidate_version: str | None = None
    report_hash: str | None = None
    rollback_version: str | None = None
    data_tier: DataTier | None = None


class SecurityMasterProvider(Protocol):
    def fetch_security_master(self, *, as_of: datetime) -> tuple[list[SecurityMasterRecord], dict[str, Any]]: ...


class DailyBarProvider(Protocol):
    def fetch_daily_bars(self, symbols: list[str], *, start: date, end: date) -> tuple[list[VersionedMarketBar], dict[str, Any]]: ...


class SnapshotProvider(Protocol):
    def fetch_snapshots(self, symbols: list[str], *, as_of: datetime) -> tuple[list[MarketSnapshotEvent], dict[str, Any]]: ...


class MinuteBarProvider(Protocol):
    def fetch_minute_bars(self, symbols: list[str], *, start: datetime, end: datetime, interval: str) -> tuple[list[VersionedMarketBar], dict[str, Any]]: ...


class EventProvider(Protocol):
    def fetch_events(self, symbols: list[str], *, since: datetime, as_of: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...
