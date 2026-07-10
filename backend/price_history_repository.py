from __future__ import annotations

import sqlite3
from typing import Any


PriceRow = tuple[str, str, float, float, str]


def count_real_price_rows(conn: sqlite3.Connection, symbol: str, synthetic_source: str) -> int:
    return conn.execute(
        "select count(*) as count from historical_prices where symbol = ? and source_name != ?",
        (symbol, synthetic_source),
    ).fetchone()["count"]


def count_price_rows(conn: sqlite3.Connection, symbol: str) -> int:
    return conn.execute("select count(*) as count from historical_prices where symbol = ?", (symbol,)).fetchone()["count"]


def upsert_price_rows(conn: sqlite3.Connection, rows: list[PriceRow]) -> None:
    conn.executemany(
        "insert or replace into historical_prices(symbol, trade_date, close_price, volume, source_name) values(?, ?, ?, ?, ?)",
        rows,
    )


def fetch_price_rows(conn: sqlite3.Connection, symbol: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "select trade_date, close_price, volume, source_name from historical_prices where symbol = ? order by trade_date desc limit ?",
        (symbol, limit),
    ).fetchall()


def fetch_curve_price_rows(conn: sqlite3.Connection, symbols: list[str]) -> list[sqlite3.Row]:
    if not symbols:
        return []
    placeholders = ",".join("?" for _ in symbols)
    return conn.execute(
        f"""
        select symbol, trade_date, close_price
        from historical_prices
        where symbol in ({placeholders})
        order by trade_date
        """,
        symbols,
    ).fetchall()


def fetch_distinct_price_sources(conn: sqlite3.Connection, symbols: list[str]) -> list[str]:
    if not symbols:
        return []
    placeholders = ",".join("?" for _ in symbols)
    rows = conn.execute(
        f"select distinct source_name from historical_prices where symbol in ({placeholders})",
        symbols,
    ).fetchall()
    return sorted({row["source_name"] for row in rows if row["source_name"]})
