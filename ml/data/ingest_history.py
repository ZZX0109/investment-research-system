from __future__ import annotations

from typing import Any

from ml.common import SYNTHETIC_HISTORY_SOURCE, connect, now_iso
from ml.data.providers import synthetic_history


def is_synthetic_source(source_name: str) -> bool:
    lowered = source_name.lower()
    return "synthetic" in lowered or "demo" in lowered or "fallback" in lowered


def history_count(symbol: str, *, real_only: bool = False) -> int:
    with connect() as conn:
        if real_only:
            row = conn.execute(
                "select count(*) as count from historical_prices where symbol = ? and lower(source_name) not like '%synthetic%' and lower(source_name) not like '%demo%' and lower(source_name) not like '%fallback%'",
                (symbol.upper(),),
            ).fetchone()
        else:
            row = conn.execute("select count(*) as count from historical_prices where symbol = ?", (symbol.upper(),)).fetchone()
    return int(row["count"]) if row else 0


def history_source_breakdown(symbol: str) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "select source_name, count(*) as count from historical_prices where symbol = ? group by source_name order by count desc",
            (symbol.upper(),),
        ).fetchall()
    return {str(row["source_name"]): int(row["count"]) for row in rows}


def purge_synthetic_history(symbol: str) -> int:
    with connect() as conn:
        row = conn.execute(
            """
            select count(*) as count
            from historical_prices
            where symbol = ?
              and (
                lower(source_name) like '%synthetic%'
                or lower(source_name) like '%demo%'
                or lower(source_name) like '%fallback%'
              )
            """,
            (symbol.upper(),),
        ).fetchone()
        count = int(row["count"]) if row else 0
        conn.execute(
            """
            delete from historical_prices
            where symbol = ?
              and (
                lower(source_name) like '%synthetic%'
                or lower(source_name) like '%demo%'
                or lower(source_name) like '%fallback%'
              )
            """,
            (symbol.upper(),),
        )
        conn.commit()
    return count


def persist_history(symbol: str, rows: list[dict[str, Any]]) -> int:
    symbol = symbol.upper()
    payload = [
        (
            symbol,
            str(row["trade_date"]),
            round(float(row["close_price"]), 4),
            round(float(row.get("volume", 0) or 0), 0),
            str(row.get("source_name") or "unknown"),
        )
        for row in rows
    ]
    if not payload:
        return 0
    with connect() as conn:
        conn.execute(
            """
            create table if not exists historical_prices (
              symbol text not null,
              trade_date text not null,
              close_price real not null,
              volume real not null,
              source_name text not null default 'synthetic_demo_price_path',
              primary key(symbol, trade_date)
            )
            """
        )
        conn.executemany(
            "insert or replace into historical_prices(symbol, trade_date, close_price, volume, source_name) values(?, ?, ?, ?, ?)",
            payload,
        )
        conn.commit()
    return len(payload)


def persist_corporate_actions(symbol: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    symbol = symbol.upper()
    with connect() as conn:
        conn.execute(
            """
            create table if not exists corporate_actions (
              symbol text not null,
              action_date text not null,
              action_type text not null,
              value real not null,
              source_name text not null,
              observed_at text not null,
              available_at text not null,
              revision_id text not null,
              primary key(symbol, action_date, action_type, revision_id)
            )
            """
        )
        conn.executemany(
            """
            insert or replace into corporate_actions(symbol, action_date, action_type, value, source_name, observed_at, available_at, revision_id)
            values(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    symbol,
                    str(row["action_date"]),
                    str(row["action_type"]),
                    float(row["value"]),
                    str(row.get("source_name", "unknown")),
                    str(row.get("observed_at", now_iso())),
                    str(row.get("available_at", row["action_date"])),
                    str(row.get("revision_id", f"{symbol}-{row['action_date']}-{row['action_type']}")),
                )
                for row in rows
            ],
        )
        conn.commit()
    return len(rows)


def fetch_yfinance_history(symbol: str, period: str = "8y", source_name: str = "yfinance historical") -> list[dict[str, Any]]:
    import yfinance as yf  # type: ignore

    history = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if history.empty:
        return []
    rows = []
    for index, row in history.iterrows():
        rows.append(
            {
                "trade_date": index.date().isoformat(),
                "close_price": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
                "source_name": source_name,
            }
        )
    return rows


def fetch_yfinance_actions(symbol: str) -> list[dict[str, Any]]:
    import yfinance as yf  # type: ignore

    ticker = yf.Ticker(symbol)
    actions = ticker.actions
    if actions is None or actions.empty:
        return []
    observed_at = now_iso()
    rows: list[dict[str, Any]] = []
    for index, row in actions.iterrows():
        action_date = index.date().isoformat()
        for column, action_type in [("Dividends", "dividend"), ("Stock Splits", "split")]:
            value = float(row.get(column, 0) or 0)
            if value:
                rows.append(
                    {
                        "action_date": action_date,
                        "action_type": action_type,
                        "value": value,
                        "source_name": "yfinance corporate_actions",
                        "observed_at": observed_at,
                        "available_at": action_date,
                        "revision_id": f"{symbol}-{action_date}-{action_type}-{value}",
                    }
                )
    return rows


def yahoo_symbol_for_cn(symbol: str) -> str:
    if symbol.startswith(("5", "6", "9")):
        return f"{symbol}.SS"
    return f"{symbol}.SZ"


def fetch_akshare_history(symbol: str) -> list[dict[str, Any]]:
    try:
        import akshare as ak  # type: ignore

        history = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
        if not history.empty:
            rows = []
            for _, row in history.iterrows():
                rows.append(
                    {
                        "trade_date": str(row["日期"]),
                        "close_price": float(row["收盘"]),
                        "volume": float(row.get("成交量", 0) or 0),
                        "source_name": "AkShare stock_zh_a_hist qfq",
                    }
                )
            return rows
    except Exception:
        pass
    yahoo_symbol = yahoo_symbol_for_cn(symbol)
    return fetch_yfinance_history(yahoo_symbol, source_name=f"yfinance historical cn yahoo {yahoo_symbol}")


def ensure_history(
    symbol: str,
    market: str = "us",
    *,
    min_rows: int = 520,
    fetch_real: bool = False,
    allow_synthetic: bool = False,
    synthetic_days: int = 2200,
    real_only: bool = False,
) -> dict[str, Any]:
    symbol = symbol.upper()
    existing = history_count(symbol, real_only=real_only)
    total_existing = history_count(symbol)
    if existing >= min_rows:
        return {
            "symbol": symbol,
            "ok": True,
            "sourceStatus": "existing_real" if real_only else "existing",
            "rowCount": existing,
            "totalRowCount": total_existing,
            "inserted": 0,
            "sourceBreakdown": history_source_breakdown(symbol),
        }

    errors: list[str] = []
    if fetch_real:
        try:
            rows = fetch_yfinance_history(symbol) if market == "us" else fetch_akshare_history(symbol)
            if rows:
                inserted = persist_history(symbol, rows)
                action_inserted = persist_corporate_actions(symbol, fetch_yfinance_actions(symbol)) if market == "us" else 0
                row_count = history_count(symbol, real_only=real_only)
                if row_count >= min_rows:
                    return {
                        "symbol": symbol,
                        "ok": True,
                        "sourceStatus": "live",
                        "rowCount": row_count,
                        "totalRowCount": history_count(symbol),
                        "inserted": inserted,
                        "corporateActionsInserted": action_inserted,
                        "sourceBreakdown": history_source_breakdown(symbol),
                    }
        except Exception as exc:
            errors.append(str(exc))

    if allow_synthetic:
        synthetic_rows = synthetic_history(symbol, days=synthetic_days)
        inserted = persist_history(symbol, synthetic_rows)
        row_count = history_count(symbol, real_only=real_only)
        return {
            "symbol": symbol,
            "ok": row_count >= min_rows,
            "sourceStatus": "degraded",
            "rowCount": row_count,
            "totalRowCount": history_count(symbol),
            "inserted": inserted,
            "sourceName": SYNTHETIC_HISTORY_SOURCE,
            "sourceBreakdown": history_source_breakdown(symbol),
            "errors": errors,
        }

    return {
        "symbol": symbol,
        "ok": False,
        "sourceStatus": "missing_real" if real_only else "missing",
        "rowCount": existing,
        "totalRowCount": total_existing,
        "inserted": 0,
        "sourceBreakdown": history_source_breakdown(symbol),
        "errors": errors,
    }
