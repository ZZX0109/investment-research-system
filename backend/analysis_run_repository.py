from __future__ import annotations

import sqlite3
from typing import Any


def insert_research_run(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    conn.execute(
        """
        insert into research_runs(
          run_id, symbol, preference, started_at, finished_at, data_status, risk_score, summary,
          input_snapshot_hash, input_snapshot_json, model_version, evidence_ids_json, reasoning_steps_json, judge_json,
          risk_conclusion_json, report_version, source_meta_json
        )
        values(
          :run_id, :symbol, :preference, :started_at, :finished_at, :data_status, :risk_score, :summary,
          :input_snapshot_hash, :input_snapshot_json, :model_version, :evidence_ids_json, :reasoning_steps_json, :judge_json,
          :risk_conclusion_json, :report_version, :source_meta_json
        )
        """,
        row,
    )


def fetch_recent_research_runs(conn: sqlite3.Connection, symbol: str, limit: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        "select * from research_runs where symbol = ? order by started_at desc limit ?",
        (symbol, limit),
    ).fetchall()


def fetch_research_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from research_runs where run_id = ?", (run_id,)).fetchone()


def upsert_report_snapshot(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    symbol: str,
    preference: str,
    report_version: str,
    markdown: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        insert or replace into report_snapshots(run_id, symbol, preference, report_version, markdown, created_at)
        values(?, ?, ?, ?, ?, ?)
        """,
        (run_id, symbol, preference, report_version, markdown, created_at),
    )


def fetch_report_snapshot(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from report_snapshots where run_id = ?", (run_id,)).fetchone()
