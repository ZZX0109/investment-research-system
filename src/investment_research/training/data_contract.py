"""Canonical row contracts shared by landing, PIT joins and training.

These models are intentionally provider-neutral. Provider adapters may retain
their original payloads, but normalized rows must carry the same availability,
revision and missingness semantics before entering a snapshot.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QualityStatus(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class MissingReason(str, Enum):
    NO_EVENTS_CONFIRMED = "no_events_confirmed"
    PROVIDER_NOT_COVERED = "provider_not_covered"
    PUBLISHED_TIME_UNVERIFIED = "published_time_unverified"
    FIELD_MISSING_IN_SOURCE = "field_missing_in_source"
    FETCH_FAILED = "fetch_failed"
    PENDING_BACKFILL = "pending_backfill"


class EventCoverage(str, Enum):
    PRESENT = "events_present"
    CONFIRMED_NONE = "confirmed_none"
    PROVIDER_NOT_COVERED = "provider_not_covered"
    FETCH_FAILED = "fetch_failed"
    PENDING_BACKFILL = "pending_backfill"


class CanonicalDataRecord(BaseModel):
    symbol: str = Field(min_length=1)
    trade_date: date | None = None
    effective_date: date | None = None
    published_at: datetime | None = None
    available_at: datetime | None = None
    revision_id: str = Field(min_length=1)
    collected_at: datetime
    provider: str = Field(min_length=1)
    raw_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality_status: QualityStatus
    missing_reason: MissingReason | None = None

    @model_validator(mode="after")
    def validate_times_and_missingness(self) -> "CanonicalDataRecord":
        if self.trade_date is None and self.effective_date is None:
            raise ValueError("record requires trade_date or effective_date")
        for field_name in ("published_at", "available_at", "collected_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{field_name} requires an explicit timezone")
        # ``collected_at`` is local ingestion time and may be later than the
        # provider's publication/availability time.  Only the source timeline
        # (published_at <= available_at) is constrained here.
        # An event file may be complete even when the provider explicitly
        # confirmed that no event occurred.  Preserve that distinction instead
        # of treating it as an unqualified missing value.  No other complete
        # record may carry a missing reason.
        confirmed_none = (
            getattr(self, "coverage", None) == EventCoverage.CONFIRMED_NONE
            and self.missing_reason == MissingReason.NO_EVENTS_CONFIRMED
        )
        if self.quality_status == QualityStatus.COMPLETE and self.missing_reason is not None and not confirmed_none:
            raise ValueError("complete record cannot carry missing_reason")
        if self.quality_status == QualityStatus.COMPLETE and (
            self.published_at is None or self.available_at is None
        ):
            raise ValueError("complete record requires published_at and available_at")
        if self.quality_status != QualityStatus.COMPLETE and self.missing_reason is None:
            raise ValueError("degraded/unavailable record requires missing_reason")
        if self.available_at is not None and self.published_at is not None and self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        return self


class PITFinancialRecord(CanonicalDataRecord):
    report_period_start: date
    report_period_end: date
    filing_kind: str = Field(min_length=1)
    statement_scope: Literal["single_quarter", "cumulative"] = Field(
        description="single_quarter or cumulative"
    )
    unit: str = Field(min_length=1)
    value: float | None = None

    @model_validator(mode="after")
    def validate_report_period(self) -> "PITFinancialRecord":
        if self.report_period_end < self.report_period_start:
            raise ValueError("report period end precedes start")
        if self.value is None and self.quality_status == QualityStatus.COMPLETE:
            raise ValueError("complete financial field requires a value")
        return self


class PITMacroRecord(CanonicalDataRecord):
    series_id: str = Field(min_length=1)
    release_at: datetime
    observation_period: str = Field(min_length=1)
    revision_number: int = Field(default=1, ge=1)
    value: float | None = None

    @model_validator(mode="after")
    def validate_release_visibility(self) -> "PITMacroRecord":
        if self.release_at.tzinfo is None or self.release_at.utcoffset() is None:
            raise ValueError("release_at requires an explicit timezone")
        if self.available_at is not None and self.release_at > self.available_at:
            raise ValueError("macro release_at cannot follow available_at")
        return self


class PITIndustryMembership(CanonicalDataRecord):
    industry_key: str = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def validate_membership_period(self) -> "PITIndustryMembership":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("industry valid_to precedes valid_from")
        return self


class PITSecurityMasterRecord(CanonicalDataRecord):
    """Point-in-time security identity and lifecycle state."""

    instrument_type: str = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None
    listed_on: date | None = None
    delisted_on: date | None = None
    st_status: str | None = None
    code_change_from: str | None = None
    code_change_to: str | None = None
    industry_key: str | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "PITSecurityMasterRecord":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("security valid_to precedes valid_from")
        if self.delisted_on is not None and self.listed_on is not None and self.delisted_on < self.listed_on:
            raise ValueError("delisted_on precedes listed_on")
        return self


class PITTradingStatusRecord(CanonicalDataRecord):
    is_halted: bool = False
    is_suspended: bool = False
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_one_price_limit: bool = False
    is_tradeable: bool = True


class PITFinancingRecord(CanonicalDataRecord):
    market: str = Field(min_length=1)
    balance: float | None = None
    change: float | None = None
    publication_lag_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_publication_lag(self) -> "PITFinancingRecord":
        if self.published_at is None or self.available_at is None:
            return self
        lag = (self.available_at - self.published_at).total_seconds()
        if self.quality_status == QualityStatus.COMPLETE and self.publication_lag_seconds is None:
            raise ValueError("complete financing record requires publication_lag_seconds")
        if self.publication_lag_seconds is not None and abs(self.publication_lag_seconds - lag) > 1.0:
            raise ValueError("publication_lag_seconds does not match published_at and available_at")
        return self


class PITMarketBreadthRecord(CanonicalDataRecord):
    historical_universe_version: str = Field(min_length=1)
    member_count: int = Field(ge=0)
    return_observation_count: int = Field(ge=0)
    advance_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    cross_section_coverage: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_member_counts(self) -> "PITMarketBreadthRecord":
        if self.return_observation_count > self.member_count:
            raise ValueError("breadth return_observation_count exceeds member_count")
        return self


class PITCorporateAction(CanonicalDataRecord):
    action_type: str = Field(min_length=1)
    announced_at: datetime
    record_date: date | None = None
    ex_date: date | None = None

    @model_validator(mode="after")
    def validate_action_visibility(self) -> "PITCorporateAction":
        if self.announced_at.tzinfo is None or self.announced_at.utcoffset() is None:
            raise ValueError("announced_at requires an explicit timezone")
        if self.available_at is not None and self.announced_at > self.available_at:
            raise ValueError("corporate action announced_at cannot follow available_at")
        return self


class PITEventRecord(CanonicalDataRecord):
    event_type: str = Field(min_length=1)
    event_time: datetime
    coverage: EventCoverage

    @model_validator(mode="after")
    def validate_event_semantics(self) -> "PITEventRecord":
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("event_time requires an explicit timezone")
        if self.coverage == EventCoverage.CONFIRMED_NONE:
            if self.quality_status == QualityStatus.COMPLETE and self.missing_reason not in {None, MissingReason.NO_EVENTS_CONFIRMED}:
                raise ValueError("confirmed_none event coverage has an incompatible missing reason")
        if self.coverage in {EventCoverage.PROVIDER_NOT_COVERED, EventCoverage.FETCH_FAILED, EventCoverage.PENDING_BACKFILL} and self.missing_reason is None:
            raise ValueError("unavailable event coverage requires missing_reason")
        return self
