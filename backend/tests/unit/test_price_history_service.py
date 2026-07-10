from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.price_history_service import ensure_price_history, get_price_points


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_ensure_price_history_generates_labeled_synthetic_fallback(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, tzinfo=timezone.utc)

    with connect() as conn:
        result = ensure_price_history(
            conn,
            "UNIT",
            "us",
            now_utc=lambda: fixed_now,
            synthetic_history_source="synthetic_demo_price_path",
            fetcher=lambda symbol, market: {"ok": False, "sourceName": "test provider", "error": "offline"},
        )
        row_count = conn.execute("select count(*) as count from historical_prices where symbol = 'UNIT'").fetchone()["count"]
        source_count = conn.execute(
            "select count(*) as count from historical_prices where symbol = 'UNIT' and source_name = 'synthetic_demo_price_path'"
        ).fetchone()["count"]

    assert result["ok"] is False
    assert result["sourceName"] == "synthetic_demo_price_path"
    assert row_count >= 260
    assert source_count == row_count


def test_get_price_points_returns_source_meta(app, test_db_path):
    connect = make_connect(test_db_path)
    with connect() as conn:
        conn.executemany(
            "insert or replace into historical_prices(symbol, trade_date, close_price, volume, source_name) values(?, ?, ?, ?, ?)",
            [
                ("UNIT", "2026-07-01", 10.0, 1000.0, "synthetic_demo_price_path"),
                ("UNIT", "2026-07-02", 11.0, 1200.0, "synthetic_demo_price_path"),
            ],
        )
        conn.commit()

    def build_source_meta(**kwargs):
        return {
            "mode": "demo",
            "provider": kwargs["provider"],
            "as_of": kwargs["as_of"],
            "overrides": kwargs.get("overrides", []),
            "synthetic_ratio": kwargs.get("synthetic_ratio", 0.0),
        }

    points = get_price_points(
        "UNIT",
        connect=connect,
        build_source_meta=build_source_meta,
        synthetic_history_source="synthetic_demo_price_path",
        limit=2,
    )

    assert [item["date"] for item in points] == ["2026-07-01", "2026-07-02"]
    assert points[0]["sourceMeta"]["provider"] == "synthetic_demo_price_path"
    assert points[0]["sourceMeta"]["synthetic_ratio"] == 1.0
