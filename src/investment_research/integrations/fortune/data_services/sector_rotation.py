"""Market sector-rotation readout (fortune/akshare adapter).

Mirrors fortune ``data_services`` structure (§1 row 1) + feeds the §3 row-2
``get_sector_rotation`` LLM tool.  Fetches the A-share sector fund-flow ranking
via akshare so the assistant can cite *which sectors* are gaining/losing
capital (the rotation readout), not just a single stock's flow.  Market-wide —
takes no symbol.  Graceful degrade to ``status="network_unavailable"`` when
akshare is gated (research-only environments stay non-fatal).
"""
from __future__ import annotations

from typing import Any

from investment_research.integrations.base import FetchResult, safe_fetch

_PROVIDER = "fortune/akshare"


def fetch_sector_rotation(*, top_n: int = 5) -> FetchResult:
    """Latest A-share sector fund-flow ranking (top gaining + losing sectors).

    Returns ``{as_of, gainers: [{sector, net_flow}], losers: [...]}`` ranked by
    net fund flow.  ``top_n`` caps each side (default 5).
    """

    def _fetch() -> Any:
        import akshare as ak

        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        if df is None or len(df) == 0:
            return {}
        cols = {str(c) for c in df.columns}
        # Sector-name column varies (名称/行业); net-flow column carries 净额.
        name_col = next((c for c in cols if "名称" in c or "行业" in c), None)
        net_col = next((c for c in cols if "净额" in c and "今日" in c), None) or next(
            (c for c in cols if "净额" in c), None
        )
        if not name_col or not net_col:
            return {}
        rows = []
        for _, item in df.iterrows():
            sector = item.get(name_col)
            net = _f(item.get(net_col))
            if not isinstance(sector, str) or not sector or net is None:
                continue
            rows.append({"sector": sector, "net_flow": net})
        if not rows:
            return {}
        # Gainers = most-positive net flow; losers = most-negative.
        gainers = sorted(rows, key=lambda r: r["net_flow"], reverse=True)[:top_n]
        losers = sorted(rows, key=lambda r: r["net_flow"])[:top_n]
        return {
            "as_of": str(df.index[0]) if len(df.index) else None,
            "gainers": gainers,
            "losers": losers,
        }

    return safe_fetch(_PROVIDER, _fetch)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").rstrip("%")
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None
