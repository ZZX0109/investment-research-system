"""Cross-sectional, point-in-time feature helpers for CN research Feature V4.

The functions in this module only use observations from the same or an
earlier trade date.  They deliberately keep unavailable information missing;
callers must not turn an absent industry or event observation into a genuine
zero signal.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from math import sqrt
from statistics import median
from typing import Iterable

from investment_research.training.models import PreparedPriceBar


FEATURE_VERSION = "cn-research-feature-v4.1"
REGIME_VERSION = "cn-regime-v3"
DIRECTION_LABEL_VERSION = "cn-direction-volatility-label-v3"
RETURN_LABEL_VERSION = "cn-return-label-v2"
DRAWDOWN_LABEL_VERSION = "cn-drawdown-label-v2"


def build_equal_weight_reference_bars(
    bars_by_symbol: dict[str, list[PreparedPriceBar]],
    *,
    symbols: Iterable[str],
    reference_symbol: str,
) -> list[PreparedPriceBar]:
    """Build a reproducible equal-weight return index from constituent bars."""
    returns_by_date: dict[date, list[tuple[float, PreparedPriceBar]]] = defaultdict(list)
    for symbol in sorted(set(symbols)):
        ordered = sorted(bars_by_symbol.get(symbol, []), key=lambda item: item.trade_date)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.close_normalized <= 0 or current.close_normalized <= 0:
                continue
            value = current.close_normalized / previous.close_normalized - 1.0
            returns_by_date[current.trade_date].append((max(-0.2, min(0.2, value)), current))
    if not returns_by_date:
        return []
    level = 100.0
    output: list[PreparedPriceBar] = []
    for trade_date in sorted(returns_by_date):
        observations = returns_by_date[trade_date]
        daily_return = sum(value for value, _bar in observations) / len(observations)
        previous_level = level
        level *= 1.0 + daily_return
        template = max((bar for _value, bar in observations), key=lambda item: item.published_at)
        output.append(template.model_copy(update={
            "symbol": reference_symbol,
            "open_native": previous_level,
            "high_native": max(previous_level, level),
            "low_native": min(previous_level, level),
            "close_native": level,
            "open_normalized": previous_level,
            "high_normalized": max(previous_level, level),
            "low_normalized": min(previous_level, level),
            "close_normalized": level,
            "volume": sum(max(0.0, bar.volume) for _value, bar in observations),
            "amount": sum(max(0.0, bar.amount or 0.0) for _value, bar in observations),
            "turnover_rate": None,
            "provider": "research-equal-weight-reference",
            "data_version": FEATURE_VERSION,
        }))
    return output


def build_cross_sectional_features(
    bars_by_symbol: dict[str, list[PreparedPriceBar]],
    *,
    symbols: Iterable[str],
    symbols_by_date: dict[date, set[str]] | None = None,
) -> dict[str, dict[date, dict[str, float]]]:
    """Return market breadth and per-symbol percentile features by trade date.

    ``symbols_by_date`` is the point-in-time universe for breadth. A caller may
    omit it only for isolated fixtures; production rebuilds must pass the
    historical membership map rather than reusing today's cohort.
    """
    latest_by_date: dict[date, list[tuple[str, PreparedPriceBar, float | None]]] = defaultdict(list)
    for symbol in sorted(set(symbols)):
        ordered = sorted(bars_by_symbol.get(symbol, []), key=lambda item: item.trade_date)
        previous_close: float | None = None
        for bar in ordered:
            daily_return = None
            if previous_close is not None and previous_close > 0 and bar.close_normalized > 0:
                daily_return = bar.close_normalized / previous_close - 1.0
            if bar.close_normalized > 0:
                previous_close = bar.close_normalized
            # Membership controls whether a row contributes to the
            # cross-section, not which prior close defines the stock's daily
            # return.  Updating ``previous_close`` above prevents a re-entering
            # symbol from contributing a multi-session jump after a period out
            # of the historical universe.
            if symbols_by_date is not None and symbol not in symbols_by_date.get(bar.trade_date, set()):
                continue
            latest_by_date[bar.trade_date].append((symbol, bar, daily_return))

    output: dict[str, dict[date, dict[str, float]]] = defaultdict(dict)
    advance_ratio_by_date: dict[date, float] = {}
    for trade_date in sorted(latest_by_date):
        rows = latest_by_date[trade_date]
        valid_returns = [value for _symbol, _bar, value in rows if value is not None]
        if not valid_returns:
            continue
        mean = sum(valid_returns) / len(valid_returns)
        dispersion = sqrt(sum((value - mean) ** 2 for value in valid_returns) / len(valid_returns))
        advance_ratio = sum(value > 0 for value in valid_returns) / len(valid_returns)
        advance_ratio_by_date[trade_date] = advance_ratio
        limit_up_ratio = sum(bar.is_limit_up for _symbol, bar, _value in rows) / len(rows)
        limit_down_ratio = sum(bar.is_limit_down for _symbol, bar, _value in rows) / len(rows)
        amounts = sorted(bar.amount for _symbol, bar, _value in rows if bar.amount is not None and bar.amount >= 0)
        turnovers = sorted(bar.turnover_rate for _symbol, bar, _value in rows if bar.turnover_rate is not None)
        market_values = {
            "market_advance_ratio_1d": advance_ratio,
            "market_median_return_1d": median(valid_returns),
            "market_return_dispersion_1d": dispersion,
            "market_limit_up_ratio_1d": limit_up_ratio,
            "market_limit_down_ratio_1d": limit_down_ratio,
            "market_cross_section_coverage": len(valid_returns) / max(1, len(rows)),
            "market_amount_total_log": _safe_log1p(sum(amounts)),
        }
        # Market breadth is a five-session, point-in-time rolling advance
        # ratio.  The prior implementation produced only the one-day advance
        # ratio, while the V2 contract explicitly requires
        # ``market_breadth_5d``.  Keep the value derived solely from dates at
        # or before the current trade date so it remains PIT-safe.
        prior_dates = sorted(
            item for item in advance_ratio_by_date if item <= trade_date
        )[-5:]
        if len(prior_dates) == 5:
            market_values["market_breadth_5d"] = sum(
                advance_ratio_by_date[item] for item in prior_dates
            ) / len(prior_dates)
        else:
            market_values["market_breadth_5d"] = None
        for symbol, bar, _value in rows:
            values = dict(market_values)
            if bar.amount is not None and amounts:
                values["amount_cross_section_percentile"] = _percentile_rank(amounts, bar.amount)
            if bar.turnover_rate is not None and turnovers:
                values["turnover_cross_section_percentile"] = _percentile_rank(turnovers, bar.turnover_rate)
            output[symbol][trade_date] = values
    return dict(output)


def build_reference_return_features(
    reference_bars: list[PreparedPriceBar],
) -> dict[date, dict[str, float]]:
    ordered = sorted(reference_bars, key=lambda item: item.trade_date)
    output: dict[date, dict[str, float]] = {}
    closes: list[float] = []
    for bar in ordered:
        closes.append(bar.close_normalized)
        values: dict[str, float] = {}
        for horizon in (1, 5, 20):
            if len(closes) > horizon and closes[-horizon - 1] > 0:
                values[f"benchmark_ret_{horizon}d"] = closes[-1] / closes[-horizon - 1] - 1.0
        output[bar.trade_date] = values
    return output


def build_industry_reference_bars(
    bars_by_symbol: dict[str, list[PreparedPriceBar]],
    industry_by_symbol: dict[str, str],
) -> dict[str, list[PreparedPriceBar]]:
    members: dict[str, list[str]] = defaultdict(list)
    for symbol, industry in industry_by_symbol.items():
        if industry:
            members[industry].append(symbol)
    return {
        industry: build_equal_weight_reference_bars(
            bars_by_symbol, symbols=symbols, reference_symbol=f"INDUSTRY:{industry}"
        )
        for industry, symbols in members.items()
        # Keep singleton groups in the frozen reference map.  The caller can
        # mark them as ``industry_reference_insufficient`` instead of silently
        # dropping the industry and turning the feature into an unexplained
        # zero/missing value.  A singleton reference is still useful for
        # provenance and coverage diagnostics, but must not be interpreted as
        # independent cross-sectional evidence.
        if symbols
    }


def _percentile_rank(values: list[float], value: float) -> float:
    return sum(item <= value for item in values) / len(values)


def _safe_log1p(value: float) -> float:
    from math import log1p

    return log1p(max(0.0, value))
