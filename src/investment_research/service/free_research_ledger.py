"""Coverage accounting for free public-data research collection.

The ledger intentionally measures what a run attempted, not an imagined
complete exchange universe.  A successful raw download is different from a
complete event feed, and both remain research-only until a qualified source is
configured.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.domain.pit import EventCoverageStatus


CollectionStatus = Literal["backfilled", "fetch_failed", "unsupported", "partial"]


class FreeCoverageRecord(BaseModel):
    market: Literal["cn", "us", "hk", "jp"]
    dataset: str
    provider: str
    status: CollectionStatus
    symbol: str | None = None
    provider_chain: list[str] = Field(default_factory=list)
    rows_or_bytes: int | None = Field(default=None, ge=0)
    reason: str | None = None
    degraded_reason: str | None = None
    payload_hash: str | None = None
    backup_payload_hash: str | None = None
    provider_comparison: dict[str, Any] | None = None
    event_coverage_status: EventCoverageStatus | None = None
    data_tier: DataTier = DataTier.RESEARCH_PIT
    historical_visibility_assumption: str = RESEARCH_VISIBILITY_ASSUMPTION

    @model_validator(mode="after")
    def research_only(self) -> "FreeCoverageRecord":
        if self.data_tier != DataTier.RESEARCH_PIT:
            raise ValueError("free collection records must be research_pit")
        if self.dataset in {"events", "filings", "companyfacts", "security_master"}:
            allowed = {
                "backfilled": {EventCoverageStatus.PENDING_UPDATE, EventCoverageStatus.EVENTS_PRESENT, EventCoverageStatus.CONFIRMED_NONE},
                "fetch_failed": EventCoverageStatus.FETCH_FAILED,
                "unsupported": EventCoverageStatus.UNSUPPORTED,
                "partial": EventCoverageStatus.PARTIAL,
            }
            expected = allowed[self.status]
            if self.event_coverage_status is None:
                self.event_coverage_status = (
                    EventCoverageStatus.PENDING_UPDATE if self.status == "backfilled" else expected
                )
            elif (
                self.event_coverage_status not in expected
                if isinstance(expected, set)
                else self.event_coverage_status != expected
            ):
                raise ValueError("free event collection status and coverage status disagree")
        return self


class MarketCoverageLedger(BaseModel):
    schema_version: str = "free-research-market-coverage-v1"
    market: Literal["cn", "us", "hk", "jp"]
    generated_at: datetime
    data_tier: DataTier = DataTier.RESEARCH_PIT
    research_only: bool = True
    historical_visibility_assumption: str = RESEARCH_VISIBILITY_ASSUMPTION
    target_count: int = Field(ge=0)
    successful_target_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    failed_providers: list[str] = Field(default_factory=list)
    unavailable_symbols: list[str] = Field(default_factory=list)
    security_state_status: Literal["unknown", "partial", "available"] = "unknown"
    event_coverage_status: EventCoverageStatus = EventCoverageStatus.UNSUPPORTED
    records: list[FreeCoverageRecord] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


def build_coverage_ledgers(
    *,
    records: list[dict[str, Any]],
    targets: dict[str, set[str]],
    generated_at: datetime,
) -> list[MarketCoverageLedger]:
    """Build deterministic per-market coverage from explicit requested symbols.

    Dataset-only entries (macro and event probes) do not inflate price-symbol
    coverage.  They instead feed the event coverage state and provider failure
    list visible to callers.
    """
    parsed = [FreeCoverageRecord.model_validate(item) for item in records]
    by_market: dict[str, list[FreeCoverageRecord]] = defaultdict(list)
    for item in parsed:
        by_market[item.market].append(item)
    output: list[MarketCoverageLedger] = []
    for market in ("cn", "us", "hk", "jp"):
        market_records = by_market[market]
        requested = set(targets.get(market, set()))
        successes = {
            item.symbol
            for item in market_records
            if item.dataset == "daily_bars" and item.status == "backfilled" and item.symbol
        }
        unavailable = sorted(requested - successes)
        event_records = [
            item for item in market_records
            if item.dataset in {"events", "filings", "companyfacts", "security_master"}
        ]
        event_state = _event_state(event_records)
        failures = sorted({
            item.provider for item in market_records
            if item.status in {"fetch_failed", "unsupported", "partial"}
        })
        target_count = len(requested)
        ratio = 0.0 if target_count == 0 else len(successes & requested) / target_count
        reasons = [
            "historical_security_state_unavailable_from_free_collectors",
            RESEARCH_VISIBILITY_ASSUMPTION,
        ]
        if ratio < 1:
            reasons.append("partial_public_price_coverage")
        if event_state not in {EventCoverageStatus.EVENTS_PRESENT, EventCoverageStatus.CONFIRMED_NONE}:
            reasons.append(f"event_coverage:{event_state.value}")
        output.append(MarketCoverageLedger(
            market=market, generated_at=generated_at, target_count=target_count,
            successful_target_count=len(successes & requested), coverage_ratio=ratio,
            failed_providers=failures, unavailable_symbols=unavailable,
            event_coverage_status=event_state, records=market_records, reasons=reasons,
        ))
    return output


def _event_state(records: list[FreeCoverageRecord]) -> EventCoverageStatus:
    if not records:
        return EventCoverageStatus.UNSUPPORTED
    states = Counter(item.event_coverage_status for item in records)
    completed = states[EventCoverageStatus.EVENTS_PRESENT] + states[EventCoverageStatus.CONFIRMED_NONE]
    if states[EventCoverageStatus.FETCH_FAILED]:
        return EventCoverageStatus.PARTIAL if completed else EventCoverageStatus.FETCH_FAILED
    if states[EventCoverageStatus.PARTIAL]:
        return EventCoverageStatus.PARTIAL
    if completed and (states[EventCoverageStatus.UNSUPPORTED] or states[EventCoverageStatus.PENDING_UPDATE]):
        return EventCoverageStatus.PARTIAL
    if states[EventCoverageStatus.PENDING_UPDATE]:
        return EventCoverageStatus.PENDING_UPDATE
    if states[EventCoverageStatus.UNSUPPORTED]:
        return EventCoverageStatus.UNSUPPORTED
    # Free collectors currently do not parse a source window sufficiently to
    # establish either "events present" or "confirmed none".  Keep this
    # branch for future normalized public event providers.
    if states[EventCoverageStatus.EVENTS_PRESENT]:
        return EventCoverageStatus.EVENTS_PRESENT
    return EventCoverageStatus.CONFIRMED_NONE
