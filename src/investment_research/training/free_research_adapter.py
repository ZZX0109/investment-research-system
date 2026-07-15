"""Normalize public backfills for research without upgrading their PIT status.

Public download endpoints generally reveal the time *we received* a historical
bar, not when the bar was observable in the past.  This adapter deliberately
sets ``available_at`` to the collection time so downstream leakage gates can
use the records for research while rejecting them from formal PIT release.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, Field

from investment_research.training.models import PreparedPriceBar
from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION


class FreeResearchNormalizationResult(BaseModel):
    data_tier: DataTier = DataTier.RESEARCH_PIT
    bars: list[PreparedPriceBar] = Field(default_factory=list)
    skipped_rows: int = 0
    formal_pit_eligible: bool = False
    blocking_reasons: list[str] = Field(
        default_factory=lambda: [RESEARCH_VISIBILITY_ASSUMPTION]
    )


def normalize_free_daily_payload(
    payload: bytes,
    *,
    market: str,
    symbol: str,
    provider: str,
    received_at: datetime,
) -> FreeResearchNormalizationResult:
    """Convert yfinance/AKShare daily JSON to a common research bar contract."""
    try:
        rows = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("free daily payload is not valid JSON") from exc
    if not isinstance(rows, list):
        raise ValueError("free daily payload must contain a JSON row list")
    received = _utc(received_at)
    digest = sha256(payload).hexdigest()
    bars: list[PreparedPriceBar] = []
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        try:
            trade_date = _trade_date(_value(row, "date", "日期"))
            close = _number(_value(row, "close", "收盘"))
            open_ = _optional_number(_value(row, "open", "开盘"))
            high = _optional_number(_value(row, "high", "最高"))
            low = _optional_number(_value(row, "low", "最低"))
            volume = _optional_number(_value(row, "volume", "成交量")) or 0.0
            amount = _optional_number(_value(row, "amount", "成交额"))
            turnover = _optional_number(_value(row, "turn", "turnover", "换手率"))
            trade_status = str(_value(row, "tradestatus", "交易状态") or "1")
            if close <= 0 or volume < 0:
                raise ValueError("invalid OHLCV")
        except (TypeError, ValueError):
            skipped += 1
            continue
        published_at = datetime.combine(trade_date, datetime.min.time(), timezone.utc)
        bars.append(PreparedPriceBar(
            symbol=symbol, trade_date=trade_date, close_native=close, close_normalized=close,
            open_native=open_, high_native=high, low_native=low,
            open_normalized=open_, high_normalized=high, low_normalized=low,
            volume=volume, amount=amount, turnover_rate=turnover,
            currency=_currency(market), target_currency=_currency(market),
            is_halted=trade_status == "0", is_suspended=trade_status == "0",
            is_tradeable=trade_status != "0", published_at=published_at,
            received_at=received, persisted_at=received, available_at=received,
            calendar_code=_calendar(market), provider=provider, raw_hash=digest,
            normalized_hash=sha256(
                json.dumps({"symbol": symbol, "date": trade_date.isoformat(), "close": close}, sort_keys=True).encode()
            ).hexdigest(), data_version=f"free-research:{digest[:16]}",
        ))
    return FreeResearchNormalizationResult(bars=sorted(bars, key=lambda item: item.trade_date), skipped_rows=skipped)


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    for key, value in row.items():
        lowered = key.lower()
        if any(name.lower() in lowered for name in names):
            return value
    return None


def _trade_date(value: Any) -> date:
    if value is None:
        raise ValueError("date missing")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _number(value: Any) -> float:
    if value is None:
        raise ValueError("number missing")
    return float(value)


def _optional_number(value: Any) -> float | None:
    return None if value is None else float(value)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _currency(market: str) -> str:
    return {"cn": "CNY", "us": "USD", "hk": "HKD", "jp": "JPY"}[market]


def _calendar(market: str) -> str:
    return {"cn": "XSHG", "us": "XNYS", "hk": "XHKG", "jp": "XTKS"}[market]
