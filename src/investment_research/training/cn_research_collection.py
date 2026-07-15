"""Deterministic controls for zero-budget A-share collection.

The controls are intentionally provider-neutral and persist only research
metadata.  They do not promote public backfills to formal PIT data.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import random
import time
from typing import Any, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")
CACHE_STATES = ("fresh", "stale_usable", "expired", "unavailable")


@dataclass(frozen=True)
class ProviderPolicy:
    requests_per_second: float
    max_attempts: int = 4
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
    jitter_ratio: float = 0.15

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if self.max_attempts <= 0 or self.max_attempts > len(self.backoff_seconds):
            raise ValueError("max_attempts must fit configured backoff schedule")


class SerialRateLimiter:
    def __init__(
        self,
        requests_per_second: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.minimum_interval = 1.0 / requests_per_second
        self.monotonic = monotonic
        self.sleep = sleep
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self.monotonic()
        if self._last_call is not None:
            remaining = self.minimum_interval - (now - self._last_call)
            if remaining > 0:
                self.sleep(remaining)
                now = self.monotonic()
        self._last_call = now


def call_with_retry(
    operation: Callable[[], T],
    *,
    policy: ProviderPolicy,
    limiter: SerialRateLimiter,
    sleep: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
) -> tuple[T, int]:
    failures: list[str] = []
    for attempt in range(1, policy.max_attempts + 1):
        limiter.wait()
        try:
            return operation(), attempt
        except Exception as exc:
            failures.append(f"attempt={attempt}:{type(exc).__name__}:{exc}")
            if attempt == policy.max_attempts:
                break
            base = policy.backoff_seconds[attempt - 1]
            jitter = base * policy.jitter_ratio * random_value()
            sleep(base + jitter)
    raise RuntimeError("provider retries exhausted:" + ";".join(failures))


class CollectionCursor(BaseModel):
    provider: str
    symbol: str
    adjustment_mode: str
    last_successful_trade_date: date
    updated_at: datetime
    payload_hash: str

    @property
    def overlap_start(self) -> date:
        current = self.last_successful_trade_date
        remaining = 5
        while remaining:
            current -= timedelta(days=1)
            if current.weekday() < 5:
                remaining -= 1
        return current


class CursorStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, provider: str, symbol: str, adjustment_mode: str) -> CollectionCursor | None:
        payload = self._read()
        value = payload.get(self._key(provider, symbol, adjustment_mode))
        return None if value is None else CollectionCursor.model_validate(value)

    def put(self, cursor: CollectionCursor) -> None:
        payload = self._read()
        payload[self._key(cursor.provider, cursor.symbol, cursor.adjustment_mode)] = cursor.model_dump(mode="json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor store must contain a JSON object")
        return payload

    @staticmethod
    def _key(provider: str, symbol: str, adjustment_mode: str) -> str:
        return f"{provider}:{symbol}:{adjustment_mode}"


class ResearchCacheManifest(BaseModel):
    provider: str
    symbol: str
    adjustment_mode: str
    fetched_at: datetime
    latest_source_date: date
    coverage_start: date
    coverage_end: date
    payload_hash: str
    schema_hash: str
    quality_status: str

    def state(self, *, as_of: date) -> str:
        if self.quality_status == "failed":
            return "unavailable"
        age = trading_day_distance(self.latest_source_date, as_of)
        if age <= 1:
            return "fresh"
        if age <= 3:
            return "stale_usable"
        return "expired"


class SymbolQualityReport(BaseModel):
    symbol: str
    quality_status: str
    row_count: int
    coverage_ratio_120d: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    provider_conflict: bool = False


def audit_research_bars(
    symbol: str,
    bars: list[Any],
    *,
    as_of: date,
    provider_conflict: bool = False,
) -> SymbolQualityReport:
    issues: list[str] = []
    dates = [bar.trade_date for bar in bars if bar.trade_date <= as_of]
    if len(dates) != len(set(dates)):
        issues.append("duplicate_trade_date")
    ordered = sorted((bar for bar in bars if bar.trade_date <= as_of), key=lambda item: item.trade_date)
    for bar in ordered:
        if bar.close_native <= 0 or bar.volume < 0:
            issues.append("non_positive_price_or_negative_volume")
        if bar.high_native is not None and bar.high_native < max(bar.open_native or bar.close_native, bar.close_native):
            issues.append("invalid_ohlc_high")
        if bar.low_native is not None and bar.low_native > min(bar.open_native or bar.close_native, bar.close_native):
            issues.append("invalid_ohlc_low")
        if bar.amount is not None and bar.amount < 0:
            issues.append("negative_amount")
    window = ordered[-120:]
    coverage = min(1.0, len({bar.trade_date for bar in window}) / 120)
    if coverage < 0.98:
        issues.append("recent_120d_coverage_below_98pct")
    if provider_conflict:
        issues.append("provider_conflict")
    unique = sorted(set(issues))
    return SymbolQualityReport(
        symbol=symbol,
        quality_status="failed" if provider_conflict else "degraded" if unique else "passed",
        row_count=len(ordered),
        coverage_ratio_120d=coverage,
        issues=unique,
        provider_conflict=provider_conflict,
    )


def trading_day_distance(start: date, end: date) -> int:
    if end <= start:
        return 0
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count
