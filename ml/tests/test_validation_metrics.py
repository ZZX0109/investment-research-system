from __future__ import annotations

from ml.models.tabular_baseline import train_tabular
from ml.training.evaluate import tabular_validation_report


def sample(idx: int) -> dict:
    drawdown = -0.03 if idx % 3 == 0 else -0.09 if idx % 3 == 1 else -0.16
    regime = "low" if drawdown > -0.06 else "medium" if drawdown > -0.12 else "high"
    return {
        "symbol": "TST",
        "market": "us",
        "asOfDate": f"2024-02-{(idx % 20) + 1:02d}",
        "split": "test" if idx % 2 else "validation",
        "tabular": [0.01 * idx, 0.02, -0.01 * idx, 0.03, 0.2, 0.25 + idx * 0.01, 0.3, drawdown, drawdown, 0.0, 0.0, 0.0, 0.0],
        "labels": {
            "risk_regime_1m": regime,
            "max_drawdown_1m": drawdown,
            "future_volatility_1m": 0.25 + idx * 0.01,
        },
    }


def run() -> None:
    samples = [sample(idx) for idx in range(12)]
    model, _ = train_tabular(samples)
    report = tabular_validation_report(model, samples)
    assert "calibration_ece" in report
    assert "pinball_loss" in report
    assert "crps" in report
    assert "var_breach_rate" in report
    assert report["walk_forward"]["windowCount"] >= 1
    assert report["purged_cv"]["foldCount"] >= 1


if __name__ == "__main__":
    run()
    print("test_validation_metrics ok")
