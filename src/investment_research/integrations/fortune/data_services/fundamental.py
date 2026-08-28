"""fortune-compatible fundamental data fetcher.

Fills the six fundamentals the v4.2 feature pipeline declares in
``training/dataset.py`` (gross_margin / current_ratio / quick_ratio /
cash_ratio / inventory_turnover, plus the ROA/ROE cohort) from akshare's
financial-analysis-indicator table.  Column matching is keyword-based so a
provider schema drift degrades the affected field to None instead of crashing.

This is the single highest-value adapter: it directly unblocks the long-term
model's missing-fundamentals gap (the ``missing_mask=1`` rows) once a
networked environment runs it.
"""
from __future__ import annotations

from typing import Any

from investment_research.integrations.base import FetchResult, safe_fetch

_PROVIDER = "fortune/akshare"

# Chinese keyword -> canonical feature key.  Keywords are matched against the
# raw column names so "毛利率(%)" / "销售毛利率" both resolve to gross_margin.
_FIELD_MAP = {
    "gross_margin": ("毛利率", "销售毛利率", "主营业务利润率"),
    "current_ratio": ("流动比率",),
    "quick_ratio": ("速动比率",),
    "cash_ratio": ("现金比率",),
    "inventory_turnover": ("存货周转率", "存货周转"),
    "roa": ("总资产报酬率", "总资产净利率", "总资产收益率", "资产报酬率", "ROA"),
    "roe": ("净资产收益率", "ROE", "加权净资产收益率"),
    "net_margin": ("销售净利率", "净利率", "净利润率"),
    "debt_ratio": ("资产负债率",),
    "revenue_growth": ("营业总收入增长率", "营业收入增长率", "主营收入增长率", "收入同比增长"),
    "profit_growth": ("归属母公司净利润增长率", "净利润增长率", "归属母公司股东净利润同比增长"),
}


def fetch_fundamentals(symbol: str) -> FetchResult:
    """Latest fundamental indicators for ``symbol`` as a feature-keyed dict."""

    def _fetch() -> Any:
        import akshare as ak

        df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2020")
        if df is None or len(df) == 0:
            return {}
        latest = df.iloc[0].to_dict()  # most-recent report first
        cols = {str(c) for c in df.columns}
        out: dict[str, float | None] = {}
        for key, keywords in _FIELD_MAP.items():
            col = next((c for c in cols if any(k in c for k in keywords)), None)
            out[key] = _f(latest.get(col)) if col else None
        out["symbol"] = symbol
        return out

    return safe_fetch(_PROVIDER, _fetch)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    # SINA returns many cells as "91.23%" / "1,234.5" strings; tolerate them.
    if isinstance(value, str):
        value = value.strip().rstrip("%").replace(",", "")
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None
