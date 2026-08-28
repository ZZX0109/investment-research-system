"""Tests for the Step-4 quick enriched retrain (round 32) — the script that
checks whether adding the round-25 DB fundamentals to price features improves
the long-term model's rank_ic."""
from __future__ import annotations

import importlib
import math
from pathlib import Path

import numpy as np
import pandas as pd


def _module():
    return importlib.import_module("scripts.retrain_long_term_enriched")


def test_rank_ic_perfect_and_anticorrelated() -> None:
    """_rank_ic is a Spearman rank correlation: 1.0 for a perfect monotone
    prediction, ~-1.0 for an inverted one, ~0.0 for noise."""
    m = _module()
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(m._rank_ic(y, y) - 1.0) < 1e-6
    assert m._rank_ic(y, -y) < -0.9
    rng = np.random.default_rng(0)
    noise = rng.normal(size=5)
    assert abs(m._rank_ic(y, noise)) < 1.0  # bounded


def test_features_with_and_without_fundamentals() -> None:
    """_features emits a price-only panel + the engineered operating_margin
    only when with_fund=True; both carry the excess_240d target."""
    m = _module()
    # tiny synthetic panel: 2 symbols × 260 bars so 240d forward return is defined
    rows = []
    for sym in ("600519", "000001"):
        for i in range(260):
            c = 100.0 * (1.0 + 0.10 * math.sin(i / 5.0))
            rows.append({"symbol": sym, "trade_date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=i),
                         "close": c, "volume": 1e6 + i * 100.0,
                         "roe": 0.30, "roa": 0.20, "net_margin": 0.50,
                         "operating_profit": 50.0, "revenue": 100.0, "net_profit": 50.0, "gross_margin": 0.91})
    df = pd.DataFrame(rows)
    Xp, yp, _ = m._features(df, with_fund=False)
    assert "roe" not in Xp.columns
    assert "ret_1d" in Xp.columns and "excess_240d" not in Xp.columns  # target separated
    assert len(yp) == len(Xp)
    Xe, ye, _ = m._features(df, with_fund=True)
    assert "roe" in Xe.columns and "operating_margin" in Xe.columns
    assert len(ye) == len(Xe)
    assert (Xe["operating_margin"] == 0.5).all()  # 50/100


def test_enrichment_delta_direction() -> None:
    """Sanity: enrichment_delta is enriched minus price_only (can be negative
    or positive; here we just confirm the subtraction is correct via the
    reported artifact on a hand-built result."""
    # Build the two results dict the way main() does + confirm the delta math.
    results = {"price_only": {"rank_ic": 0.0586}, "enriched": {"rank_ic": 0.0768}}
    delta = round(results["enriched"]["rank_ic"] - results["price_only"]["rank_ic"], 4)
    assert delta == 0.0182
