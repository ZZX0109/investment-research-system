from __future__ import annotations

import math

FEATURE_NAMES = [
    "return_1d",
    "return_5d",
    "return_21d",
    "return_63d",
    "rolling_vol_5d",
    "rolling_vol_21d",
    "rolling_vol_63d",
    "drawdown_from_21d_high",
    "drawdown_from_63d_high",
    "volume_zscore_21d",
    "volume_zscore_63d",
    "price_acceleration_5_21",
    "gap_return",
]


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous


def rolling_return(closes: list[float], index: int, days: int) -> float:
    if index - days < 0:
        return 0.0
    return pct_change(closes[index], closes[index - days])


def rolling_volatility(closes: list[float], index: int, days: int) -> float:
    start = max(1, index - days + 1)
    returns = [pct_change(closes[i], closes[i - 1]) for i in range(start, index + 1)]
    return population_std(returns) * math.sqrt(252) if len(returns) >= 2 else 0.0


def population_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def drawdown_from_high(closes: list[float], index: int, days: int) -> float:
    start = max(0, index - days + 1)
    high = max(closes[start : index + 1]) if index >= start else closes[index]
    return pct_change(closes[index], high)


def zscore(values: list[float], index: int, days: int) -> float:
    start = max(0, index - days + 1)
    window = values[start : index + 1]
    if len(window) < 2:
        return 0.0
    sigma = population_std([float(value) for value in window])
    if sigma == 0:
        return 0.0
    return (values[index] - (sum(window) / len(window))) / sigma


def feature_row(closes: list[float], volumes: list[float], index: int) -> list[float]:
    ret_5 = rolling_return(closes, index, 5)
    ret_21 = rolling_return(closes, index, 21)
    previous = closes[index - 1] if index > 0 else closes[index]
    return [
        rolling_return(closes, index, 1),
        ret_5,
        ret_21,
        rolling_return(closes, index, 63),
        rolling_volatility(closes, index, 5),
        rolling_volatility(closes, index, 21),
        rolling_volatility(closes, index, 63),
        drawdown_from_high(closes, index, 21),
        drawdown_from_high(closes, index, 63),
        zscore(volumes, index, 21),
        zscore(volumes, index, 63),
        ret_5 - ret_21,
        pct_change(closes[index], previous),
    ]


def window_features(closes: list[float], volumes: list[float], end_index: int, window: int) -> list[list[float]]:
    start = end_index - window + 1
    if start < 0:
        raise ValueError("not enough history for requested window")
    return [feature_row(closes, volumes, idx) for idx in range(start, end_index + 1)]


def tabular_snapshot(closes: list[float], volumes: list[float], end_index: int) -> list[float]:
    return feature_row(closes, volumes, end_index)
