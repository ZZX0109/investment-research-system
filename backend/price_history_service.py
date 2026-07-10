from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Callable

from .price_history_repository import (
    count_price_rows,
    count_real_price_rows,
    fetch_curve_price_rows,
    fetch_distinct_price_sources,
    fetch_price_rows,
    upsert_price_rows,
)


def fetch_historical_prices(symbol: str, market: str | None) -> dict[str, Any]:
    if market == "us":
        try:
            import yfinance as yf  # type: ignore

            history = yf.Ticker(symbol).history(period="2y", auto_adjust=True)
            if not history.empty:
                rows = []
                for index, row in history.tail(520).iterrows():
                    rows.append(
                        (
                            symbol,
                            index.date().isoformat(),
                            round(float(row["Close"]), 4),
                            round(float(row.get("Volume", 0) or 0), 0),
                            "yfinance historical",
                        )
                    )
                return {"ok": True, "rows": rows, "sourceName": "yfinance historical", "count": len(rows)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sourceName": "yfinance historical"}
    if market == "cn":
        try:
            import akshare as ak  # type: ignore

            history = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
            if not history.empty:
                rows = []
                for _, row in history.tail(520).iterrows():
                    rows.append(
                        (
                            symbol,
                            str(row["日期"]),
                            round(float(row["收盘"]), 4),
                            round(float(row.get("成交量", 0) or 0), 0),
                            "AkShare stock_zh_a_hist",
                        )
                    )
                return {"ok": True, "rows": rows, "sourceName": "AkShare stock_zh_a_hist", "count": len(rows)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sourceName": "AkShare stock_zh_a_hist"}
    return {"ok": False, "error": "unsupported market for historical provider", "sourceName": "historical provider"}


def build_synthetic_price_rows(
    symbol: str,
    *,
    now_utc: Callable[[], datetime],
    synthetic_history_source: str,
) -> list[tuple[str, str, float, float, str]]:
    today = now_utc().date()
    seed = sum(ord(char) for char in symbol)
    base = 80 + (seed % 180)
    rows: list[tuple[str, str, float, float, str]] = []
    for offset in range(780):
        day = today - timedelta(days=779 - offset)
        if day.weekday() >= 5:
            continue
        wave = math.sin(offset / 24) * 0.018 + math.cos(offset / 51) * 0.011
        drift = 1 + offset * 0.00035
        event_jump = 1.08 if offset in (210, 430, 610) else 1
        close = max(5, base * drift * (1 + wave) * event_jump)
        volume = 1_000_000 + (seed % 9) * 130_000 + abs(math.sin(offset / 9)) * 800_000
        rows.append((symbol, day.isoformat(), round(close, 2), round(volume, 0), synthetic_history_source))
    return rows


def ensure_price_history(
    conn: sqlite3.Connection,
    symbol: str,
    market: str | None = None,
    *,
    now_utc: Callable[[], datetime],
    synthetic_history_source: str,
    fetcher: Callable[[str, str | None], dict[str, Any]] = fetch_historical_prices,
) -> dict[str, Any]:
    real_existing = count_real_price_rows(conn, symbol, synthetic_history_source)
    if real_existing >= 120:
        return {"ok": True, "sourceName": "existing real historical cache", "count": real_existing}

    fetched = fetcher(symbol, market)
    if fetched.get("ok") and fetched.get("rows"):
        upsert_price_rows(conn, fetched["rows"])
        return fetched

    existing = count_price_rows(conn, symbol)
    if existing >= 260:
        return {
            "ok": False,
            "sourceName": synthetic_history_source,
            "count": existing,
            "error": fetched.get("error", "real historical provider unavailable; existing fallback retained"),
        }
    rows = build_synthetic_price_rows(symbol, now_utc=now_utc, synthetic_history_source=synthetic_history_source)
    upsert_price_rows(conn, rows)
    return {
        "ok": False,
        "sourceName": synthetic_history_source,
        "count": len(rows),
        "error": fetched.get("error", "real historical provider unavailable; synthetic fallback generated"),
    }


def get_price_points(
    symbol: str,
    *,
    connect: Callable[[], sqlite3.Connection],
    build_source_meta: Callable[..., dict[str, Any]],
    synthetic_history_source: str,
    limit: int = 90,
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_price_rows(conn, symbol, limit)
    return [
        {
            "date": row["trade_date"],
            "close": row["close_price"],
            "volume": row["volume"],
            "sourceName": row["source_name"],
            "sourceMeta": build_source_meta(
                provider=row["source_name"],
                as_of=row["trade_date"],
                overrides=["synthetic"] if row["source_name"] == synthetic_history_source else [],
                synthetic_ratio=1.0 if row["source_name"] == synthetic_history_source else 0.0,
            ),
        }
        for row in reversed(rows)
    ]


def portfolio_curve_from_history(
    holdings: list[dict[str, Any]],
    *,
    connect: Callable[[], sqlite3.Connection],
    point_count: int = 12,
) -> list[float]:
    symbols = [item["symbol"] for item in holdings]
    if not symbols:
        return []
    with closing(connect()) as conn:
        rows = fetch_curve_price_rows(conn, symbols)
    prices: dict[str, dict[str, float]] = {symbol: {} for symbol in symbols}
    for row in rows:
        prices[row["symbol"]][row["trade_date"]] = float(row["close_price"])
    date_sets = [set(prices[symbol]) for symbol in symbols if prices.get(symbol)]
    if len(date_sets) != len(symbols):
        return []
    common_dates = sorted(set.intersection(*date_sets))
    if not common_dates:
        return []
    window = common_dates[-min(252, len(common_dates)) :]
    sample_count = min(point_count, len(window))
    if sample_count <= 1:
        return [100.0]
    indexes = sorted({round(index * (len(window) - 1) / (sample_count - 1)) for index in range(sample_count)})
    values: list[float] = []
    for index in indexes:
        date = window[index]
        total_value = sum(prices[item["symbol"]][date] * float(item.get("shares") or 0) for item in holdings)
        if total_value > 0:
            values.append(total_value)
    if not values:
        return []
    base = values[0]
    return [round((value / base) * 100, 2) for value in values]


def portfolio_curve_source_label(
    holdings: list[dict[str, Any]],
    *,
    connect: Callable[[], sqlite3.Connection],
    synthetic_history_source: str,
) -> str:
    symbols = [item["symbol"] for item in holdings]
    if not symbols:
        return "no holdings"
    with closing(connect()) as conn:
        sources = fetch_distinct_price_sources(conn, symbols)
    if not sources:
        return "no historical price source"
    if sources == [synthetic_history_source]:
        return f"history-derived from {synthetic_history_source}"
    return "history-derived from " + ", ".join(sources)
