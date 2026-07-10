from __future__ import annotations

import math


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous


def forward_return(closes: list[float], start_index: int, horizon: int) -> float:
    end = min(start_index + horizon, len(closes) - 1)
    return pct_change(closes[end], closes[start_index])


def forward_max_drawdown(closes: list[float], start_index: int, horizon: int) -> float:
    end = min(start_index + horizon, len(closes) - 1)
    window = closes[start_index : end + 1]
    if not window:
        return 0.0
    peak = window[0]
    worst = 0.0
    for price in window:
        peak = max(peak, price)
        worst = min(worst, pct_change(price, peak))
    return worst


def forward_volatility(closes: list[float], start_index: int, horizon: int) -> float:
    end = min(start_index + horizon, len(closes) - 1)
    returns = [pct_change(closes[i], closes[i - 1]) for i in range(start_index + 1, end + 1)]
    return population_std(returns) * math.sqrt(252) if len(returns) >= 2 else 0.0


def population_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def risk_regime(max_drawdown_1m: float, volatility_1m: float, historical_volatility_80p: float, historical_volatility_60p: float) -> str:
    if max_drawdown_1m <= -0.12 or volatility_1m >= historical_volatility_80p:
        return "high"
    if max_drawdown_1m <= -0.06 or volatility_1m >= historical_volatility_60p:
        return "medium"
    return "low"


def labels_for_index(closes: list[float], index: int, vol60: float, vol80: float) -> dict[str, float | str | bool]:
    drawdown_1w = forward_max_drawdown(closes, index, 5)
    drawdown_1m = forward_max_drawdown(closes, index, 21)
    drawdown_3m = forward_max_drawdown(closes, index, 63)
    vol_1m = forward_volatility(closes, index, 21)
    return_1m = forward_return(closes, index, 21)
    return {
        "future_return_1w": forward_return(closes, index, 5),
        "future_return_1m": return_1m,
        "future_return_3m": forward_return(closes, index, 63),
        "max_drawdown_1w": drawdown_1w,
        "max_drawdown_1m": drawdown_1m,
        "max_drawdown_3m": drawdown_3m,
        "future_volatility_1m": vol_1m,
        "risk_regime_1m": risk_regime(drawdown_1m, vol_1m, vol80, vol60),
        "event_reversal_1m": return_1m < -0.03,
    }
