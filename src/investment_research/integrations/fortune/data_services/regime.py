"""Market-regime detector.

Mirrors fortune ``data_services/regime_detector.py``: derive the current
trend + volatility regime from the symbol's recent daily closes, so the LLM
``get_current_regime`` tool + the dashboard confidence context share one
source.  Reuses the xystock kline fetch (no extra network call) and degrades
gracefully when price history is unavailable.

Regime labels (deterministic, no hidden state):
* trend: ``bull`` (20d return > +3%) / ``bear`` (< -3%) / ``sideways``.
* volatility: ``high`` (20d annualized vol > 40%) / ``normal`` / ``low`` (< 18%).
* ma_position: close vs MA20 (``above`` / ``below``).
"""
from __future__ import annotations

import math
from typing import Any

from investment_research.integrations.base import FetchResult
from investment_research.integrations.xystock.quote_fetcher import fetch_kline

_PROVIDER = "fortune/regime"


def detect_regime(symbol: str, *, days: int = 30) -> FetchResult:
    """Current trend/volatility regime for ``symbol`` from daily closes."""

    kline = fetch_kline(symbol, days=days)
    if not kline.available:
        # Pass through the underlying degradation (network_unavailable / no_data)
        return FetchResult(
            ok=kline.ok, status=kline.status, provider=_PROVIDER,
            data=None, error=kline.error, degraded=True,
        )
    bars = kline.data
    closes = [b["close"] for b in bars if b.get("close") is not None]
    if len(closes) < 20:
        return FetchResult(
            ok=True, status="no_data", provider=_PROVIDER, data=None,
            error="insufficient_history", degraded=True,
        )
    close_now = closes[-1]
    window = closes[-20:]
    ma20 = sum(window) / 20.0
    ret_20d = (close_now / window[0] - 1.0) if window[0] else 0.0
    vol_20d = _stdev(window) / (ma20 or 1.0)
    # Annualize daily std: ~16 trading days -> annualized vol proxy.
    ann_vol = vol_20d * math.sqrt(252 / 20.0) * 100.0
    trend = "bull" if ret_20d > 0.03 else ("bear" if ret_20d < -0.03 else "sideways")
    volatility = "high" if ann_vol > 40 else ("low" if ann_vol < 18 else "normal")
    return FetchResult(
        ok=True, status="ok", provider=_PROVIDER,
        data={
            "symbol": symbol,
            "trend": trend,
            "return_20d": round(ret_20d * 100, 2),
            "volatility": volatility,
            "annualized_vol_pct": round(ann_vol, 2),
            "ma_position": "above" if close_now > ma20 else "below",
            "ma20": round(ma20, 4),
            "latest_close": close_now,
        },
    )


def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)
