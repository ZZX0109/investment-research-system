from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class StringEnum(str, Enum):
    pass


class Market(StringEnum):
    US = "us"
    CN = "cn"
    HK = "hk"
    JP = "jp"


class InstrumentType(StringEnum):
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"


class CoverageGroup(StringEnum):
    US_CORE = "us_core"
    CHINA_ADR = "china_adr"
    CN_A_SHARE = "cn_a_share"
    HK_PROXY = "hk_proxy"
    JP_PROXY = "jp_proxy"
    ETF = "etf"
    INDEX = "index"


class DataProvider(StringEnum):
    YFINANCE = "yfinance"
    AKSHARE = "akshare"
    SEC = "sec"
    CNINFO = "cninfo"
    NEWSWIRE = "newswire"
    MANUAL = "manual"


class EventType(StringEnum):
    EARNINGS = "earnings"
    FILING = "filing"
    ANNOUNCEMENT = "announcement"
    NEWS = "news"
    POLICY = "policy"
    LITIGATION = "litigation"
    MNA = "m&a"
    REGULATION = "regulation"


class EventDirection(StringEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class EventIntensity(StringEnum):
    MAJOR = "major"
    NORMAL = "normal"
    LOW = "low"


class EventSourceTier(StringEnum):
    OFFICIAL = "official"
    EXCHANGE = "exchange"
    REGULATORY = "regulatory"
    MAINSTREAM_NEWS = "mainstream_news"
    AGGREGATOR = "aggregator"


class SurpriseBucket(StringEnum):
    BIG_BEAT = "big_beat"
    BEAT = "beat"
    INLINE = "inline"
    MISS = "miss"
    BIG_MISS = "big_miss"
    UNKNOWN = "unknown"


class GuidanceBucket(StringEnum):
    RAISE = "raise"
    MAINTAIN = "maintain"
    CUT = "cut"
    UNKNOWN = "unknown"


class MissingValuePolicy(StringEnum):
    ERROR = "error"
    FORWARD_FILL = "forward_fill"
    DROP = "drop"


class HaltHandlingPolicy(StringEnum):
    KEEP = "keep"
    EXCLUDE = "exclude"


class AdjustmentPolicy(StringEnum):
    RAW_CLOSE = "raw_close"
    ADJUSTED_CLOSE = "adjusted_close"


class CurrencyHandlingPolicy(StringEnum):
    NATIVE = "native"
    CONVERT_TO_USD = "convert_to_usd"


class CalendarHandlingPolicy(StringEnum):
    STRICT = "strict"
    ALLOW_GAPS = "allow_gaps"


class IssueSeverity(StringEnum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class CanonicalInstrument(BaseModel):
    symbol: str = Field(min_length=1)
    market: Market
    instrument_type: InstrumentType
    coverage_group: CoverageGroup = CoverageGroup.US_CORE
    name: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    exchange: str | None = None
    industry_key: str | None = None
    benchmark_symbol: str | None = None
    sector_reference_symbol: str | None = None
    style_reference_symbol: str | None = None

    @field_validator("symbol", "currency")
    @classmethod
    def _normalize_upper(cls, value: str) -> str:
        return value.strip().upper()


class CoveragePreset(BaseModel):
    symbol: str
    market: Market
    instrument_type: InstrumentType
    coverage_group: CoverageGroup
    name: str
    currency: str
    exchange: str | None = None
    industry_key: str | None = None
    benchmark_symbol: str | None = None
    sector_reference_symbol: str | None = None
    style_reference_symbol: str | None = None
    primary_provider: DataProvider
    aliases: list[str] = Field(default_factory=list)

    @field_validator("symbol", "currency")
    @classmethod
    def _normalize_preset_upper(cls, value: str) -> str:
        return value.strip().upper()


class CanonicalPriceBar(BaseModel):
    symbol: str = Field(min_length=1)
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None = None
    volume: float | None = None
    amount: float | None = Field(default=None, ge=0)
    turnover_rate: float | None = Field(default=None, ge=0)
    margin_financing_balance: float | None = Field(default=None, ge=0)
    market_breadth_5d: float | None = None
    currency: str = Field(min_length=3, max_length=3)
    fx_rate_to_usd: float | None = Field(default=None, gt=0.0)
    is_halted: bool = False
    is_suspended: bool = False
    split_factor: float | None = Field(default=None, gt=0.0)
    dividend_cash: float | None = None
    calendar_code: str = "XNYS"
    published_at: datetime
    source_time: datetime | None = None
    received_at: datetime | None = None
    persisted_at: datetime | None = None
    available_at: datetime | None = None
    revision: int = Field(default=1, ge=1)
    adjustment_factor: float | None = Field(default=None, gt=0.0)
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_one_price_limit: bool = False
    is_tradeable: bool = True
    provider: str | None = None
    as_of: datetime | None = None
    payload_ref: str | None = None
    source_url: str | None = None
    raw_hash: str | None = None
    normalized_hash: str | None = None
    data_version: str | None = None

    @field_validator("symbol", "currency", "calendar_code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator(
        "published_at",
        "source_time",
        "received_at",
        "persisted_at",
        "available_at",
        "as_of",
    )
    @classmethod
    def _published_at_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _utc(value)

    @model_validator(mode="after")
    def _validate_ohlc(self) -> "CanonicalPriceBar":
        if self.high < max(self.open, self.close):
            raise ValueError("high must be >= open/close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be <= open/close")
        return self


class PointInTimeEvent(BaseModel):
    symbol: str = Field(min_length=1)
    event_type: EventType
    event_time: datetime
    published_at: datetime
    available_at: datetime | None = None
    source_name: str = Field(min_length=1)
    source_url: str | None = None
    headline: str | None = None
    payload_ref: str | None = None
    event_direction: EventDirection = EventDirection.UNKNOWN
    event_intensity: EventIntensity = EventIntensity.NORMAL
    source_tier: EventSourceTier = EventSourceTier.AGGREGATOR
    surprise_bucket: SurpriseBucket = SurpriseBucket.UNKNOWN
    guidance_bucket: GuidanceBucket = GuidanceBucket.UNKNOWN
    filing_subtype: str | None = None
    provider: str | None = None
    as_of: datetime | None = None
    raw_hash: str | None = None
    normalized_hash: str | None = None
    data_version: str | None = None

    @field_validator("symbol")
    @classmethod
    def _normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("event_time", "published_at", "available_at", "as_of")
    @classmethod
    def _event_times_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _utc(value)

    @model_validator(mode="after")
    def _prevent_pre_published_events(self) -> "PointInTimeEvent":
        if self.published_at > self.event_time and self.event_type in {
            EventType.EARNINGS,
            EventType.FILING,
            EventType.ANNOUNCEMENT,
        }:
            return self
        return self


class DataQualityRuleSet(BaseModel):
    missing_value_policy: MissingValuePolicy = MissingValuePolicy.ERROR
    halt_policy: HaltHandlingPolicy = HaltHandlingPolicy.KEEP
    adjustment_policy: AdjustmentPolicy = AdjustmentPolicy.ADJUSTED_CLOSE
    currency_policy: CurrencyHandlingPolicy = CurrencyHandlingPolicy.CONVERT_TO_USD
    calendar_policy: CalendarHandlingPolicy = CalendarHandlingPolicy.STRICT
    target_currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("target_currency")
    @classmethod
    def _normalize_target_currency(cls, value: str) -> str:
        return value.strip().upper()


class DataQualityIssue(BaseModel):
    symbol: str
    trade_date: date | None = None
    code: str
    severity: IssueSeverity
    message: str


class PreparedPriceBar(BaseModel):
    symbol: str
    trade_date: date
    close_native: float
    close_normalized: float
    open_native: float | None = None
    high_native: float | None = None
    low_native: float | None = None
    open_normalized: float | None = None
    high_normalized: float | None = None
    low_normalized: float | None = None
    volume: float
    amount: float | None = None
    turnover_rate: float | None = None
    margin_financing_balance: float | None = None
    market_breadth_5d: float | None = None
    currency: str
    target_currency: str
    is_halted: bool
    is_suspended: bool
    published_at: datetime
    source_time: datetime | None = None
    received_at: datetime | None = None
    persisted_at: datetime | None = None
    available_at: datetime | None = None
    calendar_code: str = "XNYS"
    revision: int = 1
    adjustment_factor: float | None = None
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_one_price_limit: bool = False
    is_tradeable: bool = True
    provider: str | None = None
    as_of: datetime | None = None
    payload_ref: str | None = None
    source_url: str | None = None
    raw_hash: str | None = None
    normalized_hash: str | None = None
    data_version: str | None = None


class CanonicalDatasetBundle(BaseModel):
    instrument: CanonicalInstrument
    provider: DataProvider
    price_bars: list[CanonicalPriceBar] = Field(default_factory=list)
    events: list[PointInTimeEvent] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list)


class LabelSet(BaseModel):
    symbol: str
    as_of_date: date
    future_max_drawdown_20d: float | None = None
    future_max_drawdown_60d: float | None = None
    future_max_drawdown_120d: float | None = None
    future_volatility_20d: float | None = None
    future_volatility_60d: float | None = None
    future_volatility_120d: float | None = None
    future_return_20d: float | None = None
    risk_adjusted_return_20d: float | None = None
    volatility_spike_10d: float | None = None
    event_drawdown_5d: float | None = None
    post_earnings_abnormal_move_5d: float | None = None
    news_event_shock_3d: float | None = None
    excess_return_20d: float | None = None
    excess_return_60d: float | None = None
    excess_return_120d: float | None = None
    industry_excess_return_20d: float | None = None
    industry_excess_return_60d: float | None = None
    industry_excess_return_120d: float | None = None
    future_return_1d: float | None = None
    future_return_5d: float | None = None
    future_return_20d_from_open: float | None = None
    entry_trade_date: date | None = None
    entry_delay_sessions: int | None = None
    label_available: bool = True
    label_unavailable_reason: str | None = None
    maximum_adverse_excursion_20d: float | None = None
    maximum_favorable_excursion_20d: float | None = None
    encountered_suspension_20d: bool | None = None
    direction_1d: str | None = None
    direction_5d: str | None = None
    direction_20d: str | None = None
    label_start: date | None = None
    label_end: date | None = None
    touched_limit_up_20d: bool | None = None
    touched_limit_down_20d: bool | None = None
    maximum_adverse_excursion_5d: float | None = None
    maximum_favorable_excursion_5d: float | None = None
    touched_limit_up_5d: bool | None = None
    touched_limit_down_5d: bool | None = None


class TrainingSample(BaseModel):
    symbol: str
    market: Market
    instrument_type: InstrumentType
    coverage_group: CoverageGroup = CoverageGroup.US_CORE
    industry_key: str | None = None
    benchmark_symbol: str | None = None
    sector_reference_symbol: str | None = None
    style_reference_symbol: str | None = None
    as_of_date: date
    as_of_time: datetime
    feature_cutoff: datetime
    decision_context: str = "close_confirmed"
    prediction_start_date: date | None = None
    market_snapshot_id: str | None = None
    market_snapshot_hash: str | None = Field(default=None, min_length=64, max_length=64)
    feature_version: str
    data_version: str
    features: dict[str, float] = Field(default_factory=dict)
    feature_coverage: float = 1.0
    missing_features: list[str] = Field(default_factory=list)
    labels: LabelSet
    point_in_time_event_count: int = 0
    event_source_available: bool = True
    event_coverage_status: str = "unknown"
    event_count_1d: int = 0
    event_count_7d: int = 0
    event_count_30d: int = 0
    event_provider_count: int = 0
    event_semantic_coverage: float = 0.0
    data_issues: list[str] = Field(default_factory=list)
    provider: str | None = None
    published_at: datetime | None = None
    as_of: datetime | None = None
    payload_ref: str | None = None
    source_url: str | None = None
    raw_hash: str | None = None
    normalized_hash: str | None = None


class CalibratedPrediction(BaseModel):
    symbol: str
    as_of_date: date
    raw_score: float = Field(ge=0.0, le=1.0)
    calibrated_score: float = Field(ge=0.0, le=1.0)
    target_name: str
    predicted_label: int
    market: str | None = None
    coverage_group: str | None = None
    actual_label: int | None = None
    actual_value: float | None = None
    validation_end: date | None = None


class FeatureContribution(BaseModel):
    feature_name: str
    contribution: float
    direction: str


class PredictionExplanation(BaseModel):
    symbol: str
    as_of_date: date
    target_name: str
    top_contributors: list[FeatureContribution] = Field(default_factory=list)
    summary: str


class WalkForwardFold(BaseModel):
    fold_id: str
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    regime: str
    label_horizon_days: int = 0
    purge_days: int = 0
    embargo_days: int = 0


class TrainingBundleIdentity(BaseModel):
    schema_version: str = "trusted-training-bundle-v2"
    universe_version: str
    trading_calendar_version: str
    adjustment_policy: str
    feature_contract_version: str
    label_policy_version: str
    raw_data_versions: list[str]
    fold_hash: str


class FoldMetric(BaseModel):
    fold_id: str
    regime: str
    metric_name: str
    metric_value: float


class WalkForwardFoldResult(BaseModel):
    fold: WalkForwardFold
    metrics: list[FoldMetric] = Field(default_factory=list)
    predictions: list[CalibratedPrediction] = Field(default_factory=list)


class ClassificationEvaluation(BaseModel):
    auc_roc: float | None = None
    pr_auc: float | None = None
    brier_score: float | None = None
    expected_calibration_error: float | None = None
    top_bucket_lift: float | None = None
    top_bucket_precision: float | None = None


class SkippedTrainerRecord(BaseModel):
    trainer_name: str
    algorithm_family: str
    reason: str


class TrainingSampleCoverageSummary(BaseModel):
    sample_count: int = 0
    symbol_count: int = 0
    symbols: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    instrument_types: list[str] = Field(default_factory=list)
    coverage_groups: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    feature_versions: list[str] = Field(default_factory=list)
    data_versions: list[str] = Field(default_factory=list)
    total_point_in_time_events: int = 0
    max_point_in_time_events_in_sample: int = 0
    samples_with_data_issues: int = 0
    total_data_issue_count: int = 0
    data_issue_code_counts: dict[str, int] = Field(default_factory=dict)


class LabelCoverageRecord(BaseModel):
    label_name: str
    available_count: int = 0
    missing_count: int = 0
    availability_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


class TargetLabelAuditSummary(BaseModel):
    target_name: str
    available_count: int = 0
    missing_count: int = 0
    availability_ratio: float = Field(default=0.0, ge=0.0, le=1.0)


class PointInTimeIntegritySummary(BaseModel):
    sample_count_with_events: int = 0
    sample_count_without_events: int = 0
    total_point_in_time_events: int = 0
    samples_with_data_issues: int = 0
    total_data_issue_count: int = 0
    potential_future_leakage_issue_count: int = 0
    potential_future_leakage_issue_codes: dict[str, int] = Field(default_factory=dict)


class RegimeCoverageRecord(BaseModel):
    regime: str
    fold_count: int = 0
    validation_prediction_count: int = 0
    validation_start: date | None = None
    validation_end: date | None = None


class ReferenceCoverageRecord(BaseModel):
    reference_type: str
    configured_sample_count: int = 0
    missing_configuration_count: int = 0
    feature_backed_sample_count: int = 0
    feature_backed_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    reference_symbols: list[str] = Field(default_factory=list)


class TrainingExperimentAuditSummary(BaseModel):
    sample_coverage: TrainingSampleCoverageSummary
    label_coverage: list[LabelCoverageRecord] = Field(default_factory=list)
    target_label: TargetLabelAuditSummary | None = None
    reference_coverage: list[ReferenceCoverageRecord] = Field(default_factory=list)
    point_in_time_integrity: PointInTimeIntegritySummary | None = None
    regime_coverage: list[RegimeCoverageRecord] = Field(default_factory=list)
    skipped_trainers: list[SkippedTrainerRecord] = Field(default_factory=list)


class TrainingExperimentResult(BaseModel):
    trainer_name: str
    algorithm_family: str
    model_card: ModelCard
    fold_results: list[WalkForwardFoldResult] = Field(default_factory=list)
    promotion_result: PromotionGateResult | None = None
    eligible_for_approval: bool = False
    regime_coverage: list[RegimeCoverageRecord] = Field(default_factory=list)


class TrainingExperimentReport(BaseModel):
    target_name: str
    baseline_model_id: str | None = None
    results: list[TrainingExperimentResult] = Field(default_factory=list)
    audit: TrainingExperimentAuditSummary | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelStatus(StringEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


class ModelCard(BaseModel):
    model_id: str
    task_name: str
    algorithm_family: str
    algorithm_name: str
    data_version: str
    feature_version: str
    label_version: str
    decision_context: str = "close_confirmed"
    prediction_horizon_days: int = 0
    fold_hash: str | None = None
    market_snapshot_hashes: list[str] = Field(default_factory=list)
    training_window_start: date
    training_window_end: date
    calibration_method: str | None = None
    status: ModelStatus = ModelStatus.CANDIDATE
    validation_metrics: list[FoldMetric] = Field(default_factory=list)
    training_created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    approved_at: datetime | None = None
    replaced_by: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("training_created_at", "approved_at")
    @classmethod
    def _card_datetimes_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _utc(value)


class RegistryState(BaseModel):
    models: list[ModelCard] = Field(default_factory=list)


class PromotionGatePolicy(BaseModel):
    primary_metric: str = "top_bucket_drawdown_lift"
    minimum_primary_metric_delta: float = 0.0
    min_drawdown_lift: float = 0.0
    min_auroc: float = 0.68
    max_ece: float = 0.15
    max_brier_delta_vs_baseline: float = 0.01
    max_market_auroc_drop_vs_baseline: float = 0.03
    max_coverage_group_auroc_drop_vs_baseline: float = 0.03
    minimum_coverage_group_validation_prediction_count: int = 50
    minimum_positive_regime_count: int = 3
    recent_window_count: int = 2
    require_models: list[str] = Field(default_factory=list)
    minimum_alert_precision: float = 0.5
    minimum_target_label_availability_ratio: float = 0.6
    minimum_reference_feature_backed_ratio: float = 0.6
    minimum_reference_configured_ratio: float = 0.0
    minimum_samples_with_events_ratio: float = 0.0
    minimum_required_regime_validation_prediction_count: int = 0
    maximum_potential_future_leakage_issue_count: int = 0
    maximum_samples_with_data_issues_ratio: float = 0.4
    required_regimes: list[str] = Field(
        default_factory=lambda: ["bull", "bear", "range", "high_vol"]
    )
    deep_model_families: list[str] = Field(
        default_factory=lambda: [
            "deep_learning",
            "patchtst",
            "tcn",
            "itransformer",
        ]
    )
    minimum_deep_regime_count: int = Field(default=2, ge=1)
    # Formal releases override this from config/gate_rules.yaml. Keeping the
    # library default neutral preserves backwards-compatible research use.
    minimum_deep_regime_auroc_delta: float = Field(default=0.0, ge=0.0)


class PromotionGateCheck(BaseModel):
    check_name: str
    status: str
    actual_value: float | int | str | None = None
    threshold_value: float | int | str | None = None
    detail: str


class PromotionGateResult(BaseModel):
    candidate_model_id: str
    baseline_model_id: str | None = None
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    regime_deltas: dict[str, float] = Field(default_factory=dict)
    effective_policy: PromotionGatePolicy | None = None
    checks: list[PromotionGateCheck] = Field(default_factory=list)


class RiskBucketObservation(BaseModel):
    symbol: str
    score: float = Field(ge=0.0, le=1.0)
    future_max_drawdown_20d: float
    alerted_at: datetime | None = None
    risk_event_at: datetime | None = None

    @field_validator("alerted_at", "risk_event_at")
    @classmethod
    def _obs_dt_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _utc(value)
