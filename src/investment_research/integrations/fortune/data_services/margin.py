"""Margin trading (融资融券) fetcher.

Mirrors fortune ``data_services/margin_data.py``.  Latest margin
balance / repayment for one A-share via the SSE/SZSE detail tables; the
exchange is derived from the symbol prefix.  Fed to
``market_observation.margin`` so the LLM ``get_margin_data`` tool shares
one source with the dashboard.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from investment_research.integrations.base import (
    FetchResult,
    _NETWORK_SIGNALS,
    safe_fetch,
    sh_or_sz,
)

_PROVIDER = "fortune/akshare"


def fetch_margin(symbol: str) -> FetchResult:
    """Latest margin balance for ``symbol`` (tries recent trade dates)."""

    def _fetch() -> Any:
        import akshare as ak

        exchange = sh_or_sz(symbol)
        # Margin detail tables are keyed by trade date; probe the last ~6
        # calendar days for the most recent report that includes this symbol.
        today = date.today()
        for back in range(0, 7):
            asof = (today - timedelta(days=back)).strftime("%Y%m%d")
            try:
                df = (
                    ak.stock_margin_detail_sse(date=asof)
                    if exchange == "sse"
                    else ak.stock_margin_detail_szse(date=asof)
                )
            except Exception as exc:
                # Network outages must surface as network_unavailable (let
                # safe_fetch classify); only "no data for this date" continues.
                if any(sig in str(exc).lower() for sig in _NETWORK_SIGNALS):
                    raise
                continue
            if df is None or len(df) == 0:
                continue
            cols = {str(c) for c in df.columns}
            code_col = next((c for c in cols if "代码" in c), None)
            if code_col is None:
                continue
            row = df[df[code_col].astype(str).str.zfill(6) == symbol]
            if len(row) == 0:
                continue
            rec = row.iloc[0].to_dict()
            return {
                "symbol": symbol,
                "exchange": exchange,
                "as_of": asof,
                "margin_balance": _f(rec.get(next((c for c in cols if "融资" in c and "余额" in c), ""))) or None,
                "margin_buy": _f(rec.get(next((c for c in cols if "融资" in c and "买入" in c), ""))) or None,
                "short_balance": _f(rec.get(next((c for c in cols if "融券" in c and "余额" in c), ""))) or None,
            }
        return {}

    return safe_fetch(_PROVIDER, _fetch)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None
