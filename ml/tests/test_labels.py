from __future__ import annotations

from ml.features.labels import forward_max_drawdown, forward_return, risk_regime


def run() -> None:
    closes = [100, 110, 105, 90, 95]
    assert round(forward_return(closes, 0, 4), 4) == -0.05
    assert round(forward_max_drawdown(closes, 0, 4), 4) == -0.1818
    assert risk_regime(-0.13, 0.2, 0.5, 0.3) == "high"
    assert risk_regime(-0.07, 0.2, 0.5, 0.3) == "medium"
    assert risk_regime(-0.02, 0.2, 0.5, 0.3) == "low"


if __name__ == "__main__":
    run()
    print("test_labels ok")

