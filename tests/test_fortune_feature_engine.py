from __future__ import annotations

import math
import json
from datetime import date, timedelta
from pathlib import Path

from investment_research.training.short_term.fortune_feature_engine import (
    CausalMarketContext,
    FortuneFeatureCache,
    fit_garch11,
    load_local_northbound_history,
    northbound_features_asof,
    symbol_feature_rows,
)


def _series(n: int = 120):
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(n)]
    closes = [100.0 * (1.0 + 0.08 * math.sin(index / 7.0) + 0.001 * index) for index in range(n)]
    return dates, closes


def test_garch_and_technical_rows_are_causal_and_finite_after_history() -> None:
    dates, closes = _series()
    features = symbol_feature_rows(
        "000001", dates, closes, [value * 1.01 for value in closes],
        [value * 0.99 for value in closes], [1_000_000 + index for index in range(len(closes))],
    )
    latest = features[dates[-1]]
    assert latest["symbol"] == "000001"
    assert float(latest["volatility_30d"]) > 0
    assert float(latest["garch_conditional_vol"]) > 0
    params = fit_garch11([(closes[index] / closes[index - 1]) - 1.0 for index in range(1, len(closes))])
    assert params is not None and 0 < params.persistence < 1


def test_market_context_and_content_addressed_cache(tmp_path: Path) -> None:
    dates, closes = _series()
    prices = {
        symbol: {day: close * scale for day, close in zip(dates, closes)}
        for symbol, scale in (("000001", 1.0), ("000002", 0.98), ("000003", 1.03))
    }
    context = CausalMarketContext(refresh_interval=10).build(prices)
    latest = context[("000001", dates[-1])]
    assert "hmm_bull_probability" in latest
    assert "network_cohesion" in latest
    assert latest["hmm_regime_duration"] >= 1
    cache = FortuneFeatureCache(tmp_path)
    key = cache.key(prices)
    cache.save(key, context)
    restored = cache.load(key)
    assert restored is not None
    assert restored[("000001", dates[-1])]["network_cohesion"] == latest["network_cohesion"]


def test_northbound_history_is_asof_aligned_not_live_backfilled(tmp_path: Path) -> None:
    root = tmp_path / "artifacts/cn_research_auxiliary"
    root.mkdir(parents=True)
    (root / "northbound_holdings.jsonl").write_text(
        "\n".join([
            json.dumps({"symbol": "000001", "trade_date": "2020-01-02", "holding_pct": 1.2, "holding_shares": 100}),
            json.dumps({"symbol": "000001", "trade_date": "2020-01-10", "holding_pct": 1.5, "holding_shares": 110}),
        ]) + "\n", encoding="utf-8",
    )
    history = load_local_northbound_history(tmp_path)
    before_second = northbound_features_asof(history["000001"], date(2020, 1, 5))
    after_second = northbound_features_asof(history["000001"], date(2020, 1, 10))
    assert before_second["northbound_holding_pct"] == 1.2
    assert after_second["northbound_holding_pct"] == 1.5
