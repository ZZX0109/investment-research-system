from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.portfolio_service import build_portfolio_payload, build_user_holdings


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def build_source_meta(**kwargs):
    return {
        "mode": kwargs.get("mode", "demo"),
        "provider": kwargs["provider"],
        "as_of": kwargs["as_of"],
        "overrides": kwargs.get("overrides", []),
        "synthetic_ratio": kwargs.get("synthetic_ratio", 0.0),
    }


def test_build_user_holdings_labels_synthetic_market_snapshot(app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)
    with connect() as conn:
        conn.execute(
            """
            insert into user_holdings(user_id, symbol, name, market, sector, shares, cost_price, updated_at)
            values(99, 'UNIT', 'Unit Test Asset', 'us', '测试行业', 2, 10, '2026-07-07T09:00:00Z')
            """
        )
        conn.commit()

    def snapshot(symbol: str, market: str):
        return {
            "ok": True,
            "marketValueHint": 12.5,
            "dayChange": 1.2,
            "sourceName": "synthetic_demo_market_snapshot",
            "observedAt": "2026-07-07T09:00:00Z",
            "sourceMeta": build_source_meta(
                provider="synthetic_demo_market_snapshot",
                as_of="2026-07-07T09:00:00Z",
                overrides=["synthetic"],
                synthetic_ratio=1.0,
            ),
        }

    holdings = build_user_holdings(
        99,
        connect=connect,
        try_fetch_market_snapshot=snapshot,
        build_source_meta=build_source_meta,
        now_utc=lambda: fixed_now,
        iso=iso,
    )

    assert len(holdings) == 1
    assert holdings[0]["marketValue"] == 25.0
    assert holdings[0]["dataStatus"] == "synthetic"
    assert holdings[0]["sourceMeta"]["synthetic_ratio"] == 1.0
    assert holdings[0]["weight"] == 100.0


def test_build_portfolio_payload_validates_schema_and_source_meta():
    holdings = [
        {
            "symbol": "UNIT",
            "name": "Unit Test Asset",
            "market": "us",
            "sector": "AI 算力",
            "shares": 2.0,
            "costValue": 20.0,
            "marketValue": 25.0,
            "weight": 100.0,
            "dayChange": 1.2,
            "dataSource": "synthetic_demo_market_snapshot",
            "dataStatus": "synthetic",
            "observedAt": "2026-07-07T09:00:00Z",
            "sourceMeta": build_source_meta(
                provider="synthetic_demo_market_snapshot",
                as_of="2026-07-07T09:00:00Z",
                overrides=["synthetic"],
                synthetic_ratio=1.0,
            ),
        }
    ]

    payload = build_portfolio_payload(
        "balanced",
        user_id=None,
        get_user_holdings=lambda user_id: holdings,
        get_default_holdings=lambda: holdings,
        portfolio_curve_from_history=lambda items: [100.0, 102.0],
        portfolio_curve_source_label=lambda items: "history-derived from synthetic_demo_price_path",
        build_source_meta=build_source_meta,
        current_data_mode=lambda: "demo",
        now_utc=lambda: datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc),
        iso=iso,
        synthetic_history_source="synthetic_demo_price_path",
        sector_colors={"AI 算力": "#2dbb88"},
    )

    assert payload["metrics"]["marketValue"] == 25.0
    assert payload["metrics"]["totalReturn"] == 25.0
    assert payload["portfolioCurve"] == [100.0, 102.0]
    assert payload["sourceMeta"]["mode"] == "demo"
    assert payload["sourceMeta"]["synthetic_ratio"] == 1.0
    assert payload["holdings"][0]["dataStatus"] == "synthetic"
