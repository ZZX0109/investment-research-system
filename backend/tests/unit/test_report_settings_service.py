from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.report_settings_service import get_report_settings, update_report_settings


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_get_report_settings_returns_seeded_schema(app, test_db_path):
    settings = get_report_settings(connect=make_connect(test_db_path))

    assert settings["frequency"] == "weekly"
    assert settings["updatedAt"]
    assert settings["description"] == "每周生成一次投研巡检报告"


def test_update_report_settings_persists_frequency(app, test_db_path):
    fixed_now = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
    connect = make_connect(test_db_path)

    settings = update_report_settings(
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        frequency="daily",
    )

    assert settings == {
        "frequency": "daily",
        "updatedAt": "2026-07-07T10:00:00Z",
        "description": "每日生成一次巡检报告",
    }
    assert get_report_settings(connect=connect)["frequency"] == "daily"
