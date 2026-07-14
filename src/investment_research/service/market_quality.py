from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from investment_research.domain.trusted_market import QualityStatus, VersionedMarketBar
from investment_research.domain.decision_context import EXCHANGE_SESSIONS


class MarketQualityResult(BaseModel):
    status: QualityStatus
    issues: list[str] = Field(default_factory=list)


class MarketDataQualityGate:
    """Deterministic PIT and A-share market-structure validation."""

    def evaluate_bars(self, bars: list[VersionedMarketBar], *, cutoff: datetime) -> MarketQualityResult:
        issues: list[str] = []
        fatal: list[str] = []
        seen: set[tuple[str, datetime, str, str, int]] = set()
        last_source_time: dict[tuple[str, str], datetime] = {}
        for bar in sorted(bars, key=lambda item: (item.symbol, item.provider, item.source_time)):
            key = (bar.symbol, bar.bar_start, bar.interval, bar.provider, bar.revision)
            if key in seen:
                fatal.append(f"duplicate_bar:{bar.symbol}:{bar.bar_start.isoformat()}")
            seen.add(key)
            if bar.available_at > cutoff or bar.as_of > cutoff:
                fatal.append(f"future_data:{bar.symbol}:{bar.bar_start.isoformat()}")
            previous = last_source_time.get((bar.symbol, bar.provider))
            if previous is not None and bar.source_time < previous:
                fatal.append(f"source_timestamp_regression:{bar.symbol}")
            last_source_time[(bar.symbol, bar.provider)] = bar.source_time
            if bar.bar_start.tzinfo is None or bar.source_time.tzinfo is None:
                fatal.append(f"naive_timestamp:{bar.symbol}")
            elif bar.bar_start.astimezone(ZoneInfo(EXCHANGE_SESSIONS[bar.calendar_code].timezone)).date() != bar.trade_date:
                fatal.append(f"cross_timezone_trade_date:{bar.symbol}")
            if bar.limit_up is not None and bar.high > bar.limit_up * 1.001:
                fatal.append(f"above_limit_up:{bar.symbol}")
            if bar.limit_down is not None and bar.low < bar.limit_down * 0.999:
                fatal.append(f"below_limit_down:{bar.symbol}")
            if bar.is_suspended and (bar.volume or 0) > 0:
                issues.append(f"suspended_with_volume:{bar.symbol}")
            if bar.volume is not None and bar.volume > 1e13:
                issues.append(f"abnormal_volume:{bar.symbol}")
        if fatal:
            return MarketQualityResult(status="failed", issues=[*fatal, *issues])
        if issues:
            return MarketQualityResult(status="degraded", issues=issues)
        return MarketQualityResult(status="passed")
