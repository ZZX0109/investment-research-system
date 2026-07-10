from __future__ import annotations

import math
from typing import Any


def quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, q))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def drawdown_tail(values: list[float], confidence: float) -> float:
    return quantile(values, 1.0 - confidence)


def scenario_volatility(scenario: dict[str, Any]) -> float:
    if scenario.get("volatility1m") is not None:
        return float(scenario["volatility1m"])
    return abs(float(scenario.get("return1m", 0.0))) * math.sqrt(12)


def risk_regime(drawdown_p90: float, vol_p90: float, var_breach_probability: float) -> str:
    if drawdown_p90 <= -0.12 or vol_p90 >= 0.45 or var_breach_probability >= 0.25:
        return "high"
    if drawdown_p90 <= -0.06 or vol_p90 >= 0.32 or var_breach_probability >= 0.1:
        return "medium"
    return "low"


def build_risk_distribution(
    prediction: dict[str, Any] | None,
    scenarios: list[dict[str, Any]],
    *,
    var_threshold: float = -0.10,
) -> dict[str, Any]:
    prediction = prediction or {}
    drawdowns_1w = [float(item.get("maxDrawdown1w", 0.0)) for item in scenarios if item.get("maxDrawdown1w") is not None]
    drawdowns = [float(item.get("maxDrawdown1m", 0.0)) for item in scenarios if item.get("maxDrawdown1m") is not None]
    volatilities = [scenario_volatility(item) for item in scenarios]
    if not drawdowns:
        if prediction.get("drawdown_p50") is not None:
            drawdowns = [float(prediction["drawdown_p50"]), float(prediction.get("drawdown_p90", prediction["drawdown_p50"]))]
        else:
            drawdowns = [float(prediction.get("drawdownP50", -0.04)), float(prediction.get("drawdownP90", -0.08))]
    if not drawdowns_1w:
        drawdowns_1w = [item * 0.55 for item in drawdowns]
    if not volatilities:
        vol = prediction.get("volatility_p50", prediction.get("volatilityP50", 0.25))
        volatilities = [float(vol)]

    drawdown_p50 = quantile(drawdowns, 0.5)
    drawdown_p90 = drawdown_tail(drawdowns, 0.90)
    drawdown_p95 = drawdown_tail(drawdowns, 0.95)
    drawdown_1w_p50 = quantile(drawdowns_1w, 0.5)
    drawdown_1w_p90 = drawdown_tail(drawdowns_1w, 0.90)
    drawdown_1w_p95 = drawdown_tail(drawdowns_1w, 0.95)
    volatility_p50 = quantile(volatilities, 0.5)
    volatility_p90 = quantile(volatilities, 0.9)
    breach_count = len([item for item in drawdowns if item <= var_threshold])
    breach_probability = breach_count / len(drawdowns) if drawdowns else 0.0
    regime = risk_regime(drawdown_p90, volatility_p90, breach_probability)
    return {
        "horizon": "1m",
        "scenarioCount": len(scenarios),
        "drawdownQuantiles": {
            "p50": round(drawdown_p50, 4),
            "p90": round(drawdown_p90, 4),
            "p95": round(drawdown_p95, 4),
        },
        "drawdownQuantiles1w": {
            "p50": round(drawdown_1w_p50, 4),
            "p90": round(drawdown_1w_p90, 4),
            "p95": round(drawdown_1w_p95, 4),
        },
        "drawdownQuantiles1m": {
            "p50": round(drawdown_p50, 4),
            "p90": round(drawdown_p90, 4),
            "p95": round(drawdown_p95, 4),
        },
        "volatilityQuantiles": {
            "p50": round(volatility_p50, 4),
            "p90": round(volatility_p90, 4),
        },
        "varBreach": {
            "threshold": var_threshold,
            "breachCount": breach_count,
            "breachProbability": round(breach_probability, 4),
        },
        "riskRegime": regime,
        "highRiskRegime": regime == "high",
        "method": "historical_scenario_distribution" if scenarios else "model_point_distribution_fallback",
        "disclaimer": "风险分布来自历史相似情景和模型校准，不是涨跌方向预测。",
    }
