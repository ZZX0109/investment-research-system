from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.refresh_service import build_default_refresh_data, build_refresh_user_data


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_build_default_refresh_data_updates_default_holdings(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)

    payload = build_default_refresh_data(
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        try_fetch_market_snapshot=lambda symbol, market: {
            "ok": True,
            "marketValueHint": 100.0,
            "dayChange": 1.5,
            "sourceName": "unit market",
        },
        ensure_price_history=lambda conn, symbol, market: {"ok": True},
        ensure_evidence=lambda conn, holding: None,
        archive_expired_evidence=lambda conn: None,
        get_experience_history=lambda symbol=None: [],
    )

    with connect() as conn:
        nvda = conn.execute("select shares, market_value, day_change from holdings where symbol = 'NVDA'").fetchone()

    assert payload["ok"] is True
    assert payload["count"] == 6
    assert payload["items"][0]["snapshot"]["sourceName"] == "unit market"
    assert nvda["market_value"] == nvda["shares"] * 100.0
    assert nvda["day_change"] == 1.5


def test_build_refresh_user_data_records_run_and_items(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
    with connect() as conn:
        conn.execute(
            """
            insert into user_holdings(user_id, symbol, name, market, sector, shares, cost_price, updated_at)
            values(42, 'UNIT', 'Unit Test Asset', 'us', '测试行业', 1, 100, '2026-07-07T09:00:00Z')
            """
        )
        conn.commit()

    def refresh_review_for_symbol(user_id, holding, snapshot):
        return {
            "symbol": holding["symbol"],
            "beforeScore": 10.0,
            "afterScore": 12.5,
            "riskScoreDelta": 2.5,
            "beforeClaimSummary": "before",
            "afterClaimSummary": "after",
            "evidenceChanges": {"archivedCount": 1, "newEvidenceIds": [1]},
            "conclusionChanges": ["claim changed"],
            "snapshotStatus": "live",
            "snapshot": snapshot,
        }

    payload = build_refresh_user_data(
        user_id=42,
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        try_fetch_market_snapshot=lambda symbol, market: {"ok": True, "sourceName": "unit market"},
        refresh_review_for_symbol=refresh_review_for_symbol,
        get_experience_history=lambda symbol=None: [],
    )

    with connect() as conn:
        run_count = conn.execute("select count(*) as count from evidence_refresh_runs where user_id = 42").fetchone()["count"]
        item = conn.execute("select * from evidence_refresh_items where symbol = 'UNIT'").fetchone()

    assert payload["ok"] is True
    assert payload["refreshId"].startswith("refresh-42-20260707100000")
    assert payload["summary"] == "刷新 1 个标的，归档 1 条过期证据。"
    assert run_count == 1
    assert item["risk_score_delta"] == 2.5
    assert item["snapshot_status"] == "live"
