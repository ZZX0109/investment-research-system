from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.tool_service import get_tool_invocations, log_tool_invocation, register_standard_tools


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_register_standard_tools_upserts_registry(app, test_db_path):
    connect = make_connect(test_db_path)
    with connect() as conn:
        register_standard_tools(conn, updated_at="2026-07-07T09:00:00Z")
        conn.commit()
        count = conn.execute("select count(*) as count from tool_registry").fetchone()["count"]
        row = conn.execute("select * from tool_registry where tool_id = 'market_snapshot'").fetchone()

    assert count >= 15
    assert row["name"] == "实时行情快照"
    assert row["updated_at"] == "2026-07-07T09:00:00Z"


def test_log_and_get_tool_invocations_returns_schema(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 9, 30, tzinfo=timezone.utc)

    with connect() as conn:
        register_standard_tools(conn, updated_at=iso(fixed_now))
        conn.commit()

    log_tool_invocation(
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        run_id="UNIT-balanced-run",
        tool_id="market_snapshot",
        symbol="UNIT",
        input_payload={"symbol": "UNIT", "market": "us"},
        output_summary="market snapshot degraded",
        source_name="synthetic_demo_market_snapshot",
        status="degraded",
        failure_reason="provider unavailable",
        evidence_id=7,
    )

    rows = get_tool_invocations("UNIT-balanced-run", connect=connect)

    assert len(rows) == 1
    assert rows[0]["runId"] == "UNIT-balanced-run"
    assert rows[0]["toolId"] == "market_snapshot"
    assert rows[0]["input"] == {"market": "us", "symbol": "UNIT"}
    assert rows[0]["status"] == "degraded"
    assert rows[0]["failureReason"] == "provider unavailable"
    assert rows[0]["evidenceId"] == 7
