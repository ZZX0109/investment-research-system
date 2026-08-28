"""Northbound (HSGT / 沪深股通) fund-flow fetcher.

Mirrors fortune ``data_services/main_fund_flow.py``.  Latest northbound
holding share / share-pct / market-value for one A-share, fed to
``market_observation.fund_flow`` so the LLM ``get_fund_flow`` tool + the
dashboard sentiment tile share one source.
"""
from __future__ import annotations

from typing import Any

from investment_research.integrations.base import FetchResult, safe_fetch

_PROVIDER = "fortune/akshare"


def fetch_northbound_flow(symbol: str) -> FetchResult:
    """Latest northbound holding snapshot for ``symbol``."""

    def _fetch() -> Any:
        import akshare as ak

        df = ak.stock_hsgt_individual_em(symbol=symbol)
        if df is None or len(df) == 0:
            return {}
        latest = df.iloc[0].to_dict()
        cols = {str(c) for c in df.columns}
        hold = next((c for c in cols if "持股" in c and "量" in c), None)
        pct = next((c for c in cols if "持股" in c and "比" in c), None)
        value = next((c for c in cols if "市值" in c), None)
        return {
            "symbol": symbol,
            "northbound_shares": _f(latest.get(hold)) if hold else None,
            "northbound_share_pct": _f(latest.get(pct)) if pct else None,
            "northbound_value_cny": _f(latest.get(value)) if value else None,
        }

    return safe_fetch(_PROVIDER, _fetch)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None
