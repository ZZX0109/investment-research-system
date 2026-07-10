from __future__ import annotations

import sqlite3

from backend.db_bootstrap import bootstrap_database, refresh_seed_data
from backend.report_settings_service import ensure_default_settings
from backend.tool_service import register_standard_tools


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_bootstrap_database_creates_schema_and_seed_data(test_db_path):
    connect = make_connect(test_db_path)
    register_tools = lambda conn: register_standard_tools(conn, updated_at="2026-07-07T09:00:00Z")

    bootstrap_database(
        connect=connect,
        updated_at="2026-07-07T09:00:00Z",
        ensure_default_report_settings=ensure_default_settings,
        register_standard_tools=register_tools,
        ensure_developer_account=lambda conn: None,
    )
    bootstrap_database(
        connect=connect,
        updated_at="2026-07-07T09:00:00Z",
        ensure_default_report_settings=ensure_default_settings,
        register_standard_tools=register_tools,
        ensure_developer_account=lambda conn: None,
    )

    with connect() as conn:
        holdings = conn.execute("select count(*) as count from holdings").fetchone()["count"]
        preference = conn.execute("select preference from user_preferences where id = 1").fetchone()["preference"]
        report = conn.execute("select frequency, updated_at from report_settings where id = 1").fetchone()
        tools = conn.execute("select count(*) as count from tool_registry").fetchone()["count"]
        research_columns = {row["name"] for row in conn.execute("pragma table_info(research_runs)").fetchall()}

    assert holdings == 6
    assert preference == "balanced"
    assert report["frequency"] == "weekly"
    assert report["updated_at"] == "2026-07-07T09:00:00Z"
    assert tools >= 15
    assert "input_snapshot_hash" in research_columns


def test_refresh_seed_data_runs_price_and_evidence_seed_for_default_holdings(test_db_path):
    connect = make_connect(test_db_path)
    calls = {"price": 0, "evidence": 0, "archive": 0}
    register_tools = lambda conn: register_standard_tools(conn, updated_at="2026-07-07T09:00:00Z")

    bootstrap_database(
        connect=connect,
        updated_at="2026-07-07T09:00:00Z",
        ensure_default_report_settings=ensure_default_settings,
        register_standard_tools=register_tools,
        ensure_developer_account=lambda conn: None,
    )

    def ensure_price_history(conn, symbol, market):
        calls["price"] += 1
        return {"ok": True}

    def ensure_evidence(conn, holding):
        calls["evidence"] += 1

    def archive_expired_evidence(conn):
        calls["archive"] += 1

    refresh_seed_data(
        connect=connect,
        ensure_price_history=ensure_price_history,
        ensure_evidence=ensure_evidence,
        archive_expired_evidence=archive_expired_evidence,
    )

    assert calls == {"price": 6, "evidence": 6, "archive": 1}
