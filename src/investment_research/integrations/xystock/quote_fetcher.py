"""xystock-compatible realtime quote / kline / dividend fetcher.

Lands the data the workbench ``market_observation`` tile needs so
``latest_close`` / ``sessions`` are no longer null once a networked
environment runs this adapter.  Each call returns a ``FetchResult``; callers
fill ``market_observation`` only when ``result.available`` is true.

akshare call shapes (verified against the installed akshare API surface):
* ``stock_zh_a_spot_em`` -> latest quote table, one row per symbol.
* ``stock_zh_a_hist`` -> daily OHLCV history.
* ``stock_history_dividend_detail`` -> per-share dividend history.
"""
from __future__ import annotations

from typing import Any

from investment_research.integrations.base import FetchResult, safe_fetch

_PROVIDER = "xystock/akshare"


def _require_akshare():
    import akshare as ak  # local import: keep akshare out of cold paths

    return ak


def fetch_realtime_quote(symbol: str) -> FetchResult:
    """Latest close / change / volume for one A-share symbol."""

    def _fetch() -> Any:
        ak = _require_akshare()
        # stock_zh_a_spot_em takes no symbol arg: it returns the full A-share
        # spot table; filter by the 6-digit code (xystock's approach).
        df = ak.stock_zh_a_spot_em()
        if df is None or len(df) == 0:
            return None
        cols = {str(c) for c in df.columns}
        code_col = next((c for c in cols if "代码" in c), None)
        if code_col is None:
            return None
        rows = df[df[code_col].astype(str).str.zfill(6) == symbol]
        if len(rows) == 0:
            return None
        row = rows.iloc[0].to_dict()
        return {
            "symbol": symbol,
            "latest_close": _f(row.get("最新价")),
            "change_pct": _f(row.get("涨跌幅")),
            "volume": _f(row.get("成交量")),
            "amount": _f(row.get("成交额")),
        }

    return safe_fetch(_PROVIDER, _fetch)


def fetch_kline(symbol: str, *, days: int = 90) -> FetchResult:
    """Up to ``days`` daily OHLCV bars for ``symbol``."""

    def _fetch() -> Any:
        ak = _require_akshare()
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", adjust="qfq",
        )
        if df is None or len(df) == 0:
            return []
        df = df.tail(days)
        return [
            {
                "date": str(r.get("日期")),
                "open": _f(r.get("开盘")),
                "high": _f(r.get("最高")),
                "low": _f(r.get("最低")),
                "close": _f(r.get("收盘")),
                "volume": _f(r.get("成交量")),
            }
            for r in df.to_dict("records")
        ]

    return safe_fetch(_PROVIDER, _fetch)


def fetch_dividend(symbol: str) -> FetchResult:
    """Per-share dividend history for ``symbol`` (feeds ``line_items``)."""

    def _fetch() -> Any:
        ak = _require_akshare()
        df = ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")
        if df is None or len(df) == 0:
            return []
        return [
            {
                "date": str(r.get("公告日期") or r.get("除权除息日")),
                "cash": _f(r.get("每股派息(税前)(元)")),
                "shares": _f(r.get("送股比例(每10股)") or r.get("转增比例(每10股)")),
            }
            for r in df.to_dict("records")
        ]

    return safe_fetch(_PROVIDER, _fetch)


# --------------------------------------------------------------------------- #
# Intraday market spot (round 33) — full-A-share + index snapshot, polled
# every five minutes during CN trading sessions for the "盘中行情" board. NOT a tick
# push stream (akshare is request/response); it is the latest spot snapshot.
# --------------------------------------------------------------------------- #
def fetch_market_spot() -> FetchResult:
    """Full A-share spot snapshot (``stock_zh_a_spot``, SINA source — verified
    stable round 33; the east-money ``stock_zh_a_spot_em`` endpoint ProxyErrors
    on this network).  Returns a list of dicts: symbol / market / name /
    latest_price / change_pct / volume / amount / ts.  Network/error degrade via
    ``safe_fetch`` so a flaky akshare call never crashes the API.

    Note: SINA codes carry a market prefix (``sh600519`` / ``sz000001`` /
    ``bj920000``); we split it into ``symbol`` (6 digits) + ``market``
    (sh/sz/bj)."""

    def _fetch() -> Any:
        ak = _require_akshare()
        df = ak.stock_zh_a_spot()  # SINA source, 70-page batched, stable
        if df is None or len(df) == 0:
            return []
        cols = {str(c) for c in df.columns}
        code_col = next((c for c in cols if "代码" in c), None)
        name_col = next((c for c in cols if "名称" in c), None)
        price_col = next((c for c in cols if "最新价" in c), None)
        chg_col = next((c for c in cols if "涨跌幅" in c), None)
        vol_col = next((c for c in cols if "成交量" in c), None)
        amt_col = next((c for c in cols if "成交额" in c), None)
        ts_col = next((c for c in cols if "时间戳" in c or "时间" == c), None)
        if code_col is None or price_col is None:
            return []
        rows: list[dict] = []
        for _, r in df.iterrows():
            raw = str(r[code_col]).strip().lower()
            # split market prefix (sh/sz/bj) from the 6-digit code
            market = raw[:2] if raw[:2] in {"sh", "sz", "bj"} else None
            sym = raw[2:] if market else raw
            if not sym.isdigit() or len(sym) != 6:
                continue
            rows.append({
                "symbol": sym,
                "market": market,
                "name": str(r[name_col]) if name_col else None,
                "latest_price": _f(r.get(price_col) if price_col else None),
                "change_pct": _f(r.get(chg_col) if chg_col else None),
                "volume": _f(r.get(vol_col) if vol_col else None),
                "amount": _f(r.get(amt_col) if amt_col else None),
                "ts": str(r[ts_col]) if ts_col else None,
            })
        return rows

    return safe_fetch(_PROVIDER, _fetch, empty_ok=True)


def fetch_etf_spot(symbols: list[str] | None = None) -> FetchResult:
    """Latest ETF quotes, including the simulator-only gold ETF.

    The stock spot endpoint excludes funds, so ETF quotes are collected with
    the dedicated Eastmoney adapter and persisted in the same spot table.
    """
    wanted = {str(item).zfill(6) for item in (symbols or [])}

    def _fetch() -> Any:
        ak = _require_akshare()
        df = ak.fund_etf_spot_em()
        if df is None or len(df) == 0:
            return []
        cols = {str(c) for c in df.columns}
        code_col = next((c for c in cols if "代码" in c), None)
        name_col = next((c for c in cols if "名称" in c), None)
        price_col = next((c for c in cols if "最新价" in c), None)
        chg_col = next((c for c in cols if "涨跌幅" in c), None)
        vol_col = next((c for c in cols if "成交量" in c), None)
        amt_col = next((c for c in cols if "成交额" in c), None)
        if code_col is None or price_col is None:
            return []
        rows: list[dict] = []
        for _, r in df.iterrows():
            symbol = str(r[code_col]).strip().zfill(6)
            if wanted and symbol not in wanted:
                continue
            rows.append({
                "symbol": symbol,
                "market": "sh" if symbol.startswith("5") else "sz",
                "name": str(r[name_col]) if name_col else None,
                "latest_price": _f(r.get(price_col)),
                "change_pct": _f(r.get(chg_col)) if chg_col else None,
                "volume": _f(r.get(vol_col)) if vol_col else None,
                "amount": _f(r.get(amt_col)) if amt_col else None,
                "ts": None,
            })
        return rows

    return safe_fetch(_PROVIDER, _fetch, empty_ok=True)


def fetch_index_spot(symbols: list[str]) -> FetchResult:
    """Index spot snapshot (上证/深证/创业板).  ``stock_zh_index_spot_sina``
    (SINA source, verified stable round 33 — the east-money ``_em`` variant
    ProxyErrors).  Filters by the requested 6-digit codes (``000001`` Shanghai
    Composite, ``399001`` Shenzhen Component, ``399006`` ChiNext)."""

    def _fetch() -> Any:
        ak = _require_akshare()
        df = ak.stock_zh_index_spot_sina()
        if df is None or len(df) == 0:
            return []
        cols = {str(c) for c in df.columns}
        code_col = next((c for c in cols if "代码" in c), None)
        name_col = next((c for c in cols if "名称" in c), None)
        price_col = next((c for c in cols if "最新价" in c), None)
        chg_col = next((c for c in cols if "涨跌幅" in c), None)
        if code_col is None:
            return []
        wanted = {str(s).zfill(6) for s in symbols}
        rows: list[dict] = []
        for _, r in df.iterrows():
            raw = str(r[code_col]).strip().lower()
            # SINA index codes carry a market prefix (sh000001 / sz399001)
            market = raw[:2] if raw[:2] in {"sh", "sz"} else None
            sym = raw[2:] if market else raw
            if sym not in wanted:
                continue
            rows.append({
                "symbol": sym,
                "market": market,
                "name": str(r[name_col]) if name_col else None,
                "latest_price": _f(r.get(price_col) if price_col else None),
                "change_pct": _f(r.get(chg_col) if chg_col else None),
            })
        return rows

    return safe_fetch(_PROVIDER, _fetch, empty_ok=True)


def is_cn_trading_session(now=None) -> bool:
    """True if ``now`` is inside a CN A-share trading session
    (Mon–Fri 09:30–11:30 / 13:00–15:00), ignoring holidays (a holiday
    calendar cache can refine this later — ``tool_trade_date_hist_sina``).
    Used by the intraday spot poller to skip off-hours requests."""
    from datetime import datetime

    moment = now or datetime.now()
    if moment.weekday() >= 5:  # Sat/Sun
        return False
    t = moment.time()
    from datetime import time as _time

    return _time(9, 30) <= t <= _time(11, 30) or _time(13, 0) <= t <= _time(15, 0)


# --------------------------------------------------------------------------- #
# Per-asset news + notices (round 34) — so the LLM snapshot can cite same-day
# news and announcements alongside the intraday quote.  NOT persisted to a table
# (called on-demand when a snapshot is built for a selected asset); degrades
# gracefully via ``safe_fetch`` on a flaky akshare call.
# --------------------------------------------------------------------------- #
def fetch_stock_news(symbol: str, *, limit: int = 10) -> FetchResult:
    """Latest per-asset news (``stock_news_em``, SINA/eastmoney source).
    Returns a list of dicts: title / content / published_at / source / url."""

    def _fetch() -> Any:
        ak = _require_akshare()
        df = ak.stock_news_em(symbol=symbol)
        if df is None or len(df) == 0:
            return []
        cols = {str(c) for c in df.columns}
        title_col = next((c for c in cols if "标题" in c), None)
        content_col = next((c for c in cols if "内容" in c), None)
        time_col = next((c for c in cols if "时间" in c), None)
        src_col = next((c for c in cols if "来源" in c), None)
        url_col = next(
            (c for c in cols if "链接" in c or "网址" in c or str(c).lower() in {"url", "link"}),
            None,
        )
        if title_col is None:
            return []
        rows: list[dict] = []
        for _, r in df.head(limit).iterrows():
            rows.append({
                "title": str(r[title_col]) if title_col else None,
                "content": str(r[content_col])[:200] if content_col else None,
                "published_at": str(r[time_col]) if time_col else None,
                "source": str(r[src_col]) if src_col else None,
                "url": _text(r[url_col]) if url_col else None,
            })
        return rows

    return safe_fetch(_PROVIDER, _fetch, empty_ok=True)


def fetch_stock_notices(symbol: str, *, limit: int = 8, days: int = 7) -> FetchResult:
    """Latest per-asset official announcements (``stock_individual_notice_report``,
    cninfo source).  Returns a list of dicts: title / notice_type / date / url.
    ``days`` limits the query window (default 7) so a snapshot build never
    scans all ~1000 historical pages for a liquid name (10s+)."""

    def _fetch() -> Any:
        from datetime import date, timedelta

        ak = _require_akshare()
        end = date.today()
        begin = end - timedelta(days=days)
        df = ak.stock_individual_notice_report(
            symbol="全部", security=symbol,
            begin_date=begin.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
        )
        if df is None or len(df) == 0:
            return []
        cols = {str(c) for c in df.columns}
        title_col = next((c for c in cols if "标题" in c), None)
        type_col = next((c for c in cols if "类型" in c), None)
        date_col = next((c for c in cols if "日期" in c), None)
        url_col = next(
            (c for c in cols if "链接" in c or "网址" in c or str(c).lower() in {"url", "link"}),
            None,
        )
        if title_col is None:
            return []
        rows: list[dict] = []
        for _, r in df.head(limit).iterrows():
            rows.append({
                "title": str(r[title_col]) if title_col else None,
                "notice_type": str(r[type_col]) if type_col else None,
                "date": str(r[date_col]) if date_col else None,
                "url": _text(r[url_col]) if url_col else None,
            })
        return rows

    return safe_fetch(_PROVIDER, _fetch, empty_ok=True)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def _text(value: Any) -> str | None:
    """Normalize optional provider text fields without leaking NaN markers."""

    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none", "<na>"} else None
