from __future__ import annotations

import json
import sqlite3
from typing import Any


def fetch_default_holding_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("select * from holdings").fetchall()


def fetch_user_refresh_holding_rows(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute("select * from user_holdings where user_id = ? order by id", (user_id,)).fetchall()


def update_default_holding_market_values(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    market_value: float,
    day_change: float,
) -> None:
    conn.execute(
        "update holdings set market_value = ?, day_change = ? where symbol = ?",
        (market_value, day_change, symbol),
    )


def count_experience_history(conn: sqlite3.Connection, symbol: str) -> int:
    row = conn.execute("select count(*) as count from experience_history where symbol = ?", (symbol,)).fetchone()
    return int(row["count"])


def insert_refresh_run(
    conn: sqlite3.Connection,
    *,
    refresh_id: str,
    user_id: int,
    refreshed_at: str,
    symbol_count: int,
    archived_count: int,
    summary: str,
) -> None:
    conn.execute(
        """
        insert into evidence_refresh_runs(refresh_id, user_id, refreshed_at, symbol_count, archived_count, summary)
        values(?, ?, ?, ?, ?, ?)
        """,
        (refresh_id, user_id, refreshed_at, symbol_count, archived_count, summary),
    )


def insert_refresh_items(conn: sqlite3.Connection, *, refresh_id: str, items: list[dict[str, Any]]) -> None:
    conn.executemany(
        """
        insert into evidence_refresh_items(
          refresh_id, symbol, before_score, after_score, risk_score_delta,
          before_claim_summary, after_claim_summary, evidence_changes,
          conclusion_changes, snapshot_status
        )
        values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                refresh_id,
                item["symbol"],
                item["beforeScore"],
                item["afterScore"],
                item["riskScoreDelta"],
                item["beforeClaimSummary"],
                item["afterClaimSummary"],
                json.dumps(item["evidenceChanges"], ensure_ascii=False),
                json.dumps(item["conclusionChanges"], ensure_ascii=False),
                item["snapshotStatus"],
            )
            for item in items
        ],
    )
