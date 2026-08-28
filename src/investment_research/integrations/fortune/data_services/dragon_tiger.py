"""Dragon-tiger (龙虎榜) fetcher.

Mirrors fortune ``data_services/lhb_data.py``.  Recent dragon-tiger board
appearances for one A-share, fed to ``market_observation.dragon_tiger`` so
the LLM ``get_dragon_tiger`` tool + dashboard share one source.  The board
is date-keyed; the adapter probes the last ~10 calendar days for any
appearance of ``symbol``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from investment_research.integrations.base import (
    FetchResult,
    _NETWORK_SIGNALS,
    safe_fetch,
)

_PROVIDER = "fortune/akshare"


def fetch_dragon_tiger(symbol: str, *, lookback_days: int = 10) -> FetchResult:
    """Recent dragon-tiger appearances for ``symbol`` (list, newest first)."""

    def _fetch() -> Any:
        import akshare as ak

        today = date.today()
        appearances: list[dict] = []
        for back in range(0, lookback_days):
            asof = (today - timedelta(days=back)).strftime("%Y%m%d")
            try:
                df = ak.stock_lhb_detail_em(start_date=asof, end_date=asof)
            except Exception as exc:
                # Network outages must surface as network_unavailable (let
                # safe_fetch classify); only "no board for this date" continues.
                if any(sig in str(exc).lower() for sig in _NETWORK_SIGNALS):
                    raise
                continue
            if df is None or len(df) == 0:
                continue
            cols = {str(c) for c in df.columns}
            code_col = next((c for c in cols if "代码" in c), None)
            if code_col is None:
                continue
            rows = df[df[code_col].astype(str).str.zfill(6) == symbol]
            for rec in rows.to_dict("records"):
                appearances.append({
                    "symbol": symbol,
                    "date": asof,
                    "reason": rec.get(next((c for c in cols if "上榜" in c or "原因" in c), "")),
                    "net_buy": _f(rec.get(next((c for c in cols if "净买" in c), ""))),
                })
        return appearances  # may be empty -> no_data

    return safe_fetch(_PROVIDER, _fetch)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None
