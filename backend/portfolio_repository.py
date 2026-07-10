from __future__ import annotations

import sqlite3


def fetch_user_holding_rows(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute("select * from user_holdings where user_id = ? order by id", (user_id,)).fetchall()


def fetch_default_holding_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("select * from holdings").fetchall()


def delete_user_holding_rows(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("delete from user_holdings where user_id = ?", (user_id,))


def insert_user_holding_rows(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    holdings: list[dict[str, object]],
    updated_at: str,
) -> None:
    conn.executemany(
        """
        insert into user_holdings(user_id, symbol, name, market, sector, shares, cost_price, updated_at)
        values(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                user_id,
                item["symbol"],
                item["name"],
                item["market"],
                item["sector"],
                item["shares"],
                item["cost_price"],
                updated_at,
            )
            for item in holdings
        ],
    )


def upsert_user_profile(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    preference: str,
    risk_answers_json: str,
    onboarding_completed: bool,
    updated_at: str,
) -> None:
    conn.execute(
        """
        insert or replace into user_profiles(user_id, preference, risk_answers, onboarding_completed, updated_at)
        values(?, ?, ?, ?, ?)
        """,
        (user_id, preference, risk_answers_json, 1 if onboarding_completed else 0, updated_at),
    )


def fetch_latest_user_holding_row(conn: sqlite3.Connection, *, user_id: int, symbol: str) -> sqlite3.Row | None:
    return conn.execute(
        "select * from user_holdings where user_id = ? and symbol = ? order by id desc limit 1",
        (user_id, symbol),
    ).fetchone()


def insert_user_holding_row(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    symbol: str,
    name: str,
    market: str,
    sector: str,
    shares: float,
    cost_price: float,
    updated_at: str,
) -> None:
    conn.execute(
        """
        insert into user_holdings(user_id, symbol, name, market, sector, shares, cost_price, updated_at)
        values(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, symbol, name, market, sector, shares, cost_price, updated_at),
    )
