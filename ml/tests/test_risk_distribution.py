from __future__ import annotations

from ml.risk.distribution import build_risk_distribution


def run() -> None:
    scenarios = [
        {"maxDrawdown1w": -0.01, "maxDrawdown1m": -0.02, "return1m": 0.04, "volatility1m": 0.18},
        {"maxDrawdown1w": -0.04, "maxDrawdown1m": -0.08, "return1m": -0.02, "volatility1m": 0.28},
        {"maxDrawdown1w": -0.10, "maxDrawdown1m": -0.18, "return1m": -0.12, "volatility1m": 0.62},
    ]
    distribution = build_risk_distribution({}, scenarios, var_threshold=-0.1)
    assert distribution["scenarioCount"] == 3
    assert distribution["drawdownQuantiles"]["p95"] <= distribution["drawdownQuantiles"]["p90"]
    assert distribution["drawdownQuantiles1w"]["p90"] < 0
    assert distribution["drawdownQuantiles1m"]["p90"] == distribution["drawdownQuantiles"]["p90"]
    assert distribution["varBreach"]["breachProbability"] > 0
    assert distribution["riskRegime"] == "high"


if __name__ == "__main__":
    run()
    print("test_risk_distribution ok")
