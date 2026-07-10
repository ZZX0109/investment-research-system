from __future__ import annotations

import sqlite3


def model_exists(conn: sqlite3.Connection, model_id: str) -> bool:
    return conn.execute("select 1 from model_registry where model_id = ?", (model_id,)).fetchone() is not None


def fetch_prediction_rows(conn: sqlite3.Connection, symbol: str, *, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "select * from risk_predictions where symbol = ? order by created_at desc limit ?",
        (symbol, limit),
    ).fetchall()


def fetch_latest_prediction_row(conn: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
    return conn.execute(
        "select * from risk_predictions where symbol = ? order by created_at desc limit 1",
        (symbol,),
    ).fetchone()


def fetch_similar_scenario_rows(conn: sqlite3.Connection, symbol: str, *, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "select * from similar_scenarios where query_symbol = ? order by created_at desc, similarity desc limit ?",
        (symbol, limit),
    ).fetchall()


def fetch_model_row(conn: sqlite3.Connection, model_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from model_registry where model_id = ?", (model_id,)).fetchone()


def fetch_historical_price_rows(conn: sqlite3.Connection, symbol: str, *, limit: int = 760) -> list[sqlite3.Row]:
    return conn.execute(
        "select trade_date, close_price, volume, source_name from historical_prices where symbol = ? order by trade_date desc limit ?",
        (symbol.upper(), limit),
    ).fetchall()
