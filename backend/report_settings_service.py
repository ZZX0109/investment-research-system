from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Callable

from .report_settings_repository import ensure_default_report_settings, fetch_report_settings, upsert_report_settings
from .schemas import ReportSettingsRecord


REPORT_FREQUENCY_DESCRIPTIONS = {
    "daily": "每日生成一次巡检报告",
    "weekly": "每周生成一次投研巡检报告",
    "monthly": "每月生成一次组合复盘报告",
    "trigger_only": "仅在触发器命中时生成报告",
}


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def ensure_default_settings(conn: sqlite3.Connection, *, updated_at: str) -> None:
    ensure_default_report_settings(conn, updated_at=updated_at)


def _settings_payload(row: sqlite3.Row) -> dict[str, Any]:
    frequency = row["frequency"]
    return dump_model(
        ReportSettingsRecord(
            frequency=frequency,
            updatedAt=row["updated_at"],
            description=REPORT_FREQUENCY_DESCRIPTIONS.get(frequency, REPORT_FREQUENCY_DESCRIPTIONS["weekly"]),
        )
    )


def get_report_settings(*, connect: Callable[[], sqlite3.Connection]) -> dict[str, Any]:
    with closing(connect()) as conn:
        row = fetch_report_settings(conn)
    if row is None:
        return {
            "frequency": "weekly",
            "updatedAt": None,
            "description": REPORT_FREQUENCY_DESCRIPTIONS["weekly"],
        }
    return _settings_payload(row)


def update_report_settings(
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    frequency: str,
) -> dict[str, Any]:
    updated_at = iso(now_utc())
    with closing(connect()) as conn:
        upsert_report_settings(conn, frequency=frequency, updated_at=updated_at)
        row = fetch_report_settings(conn)
        conn.commit()
    return _settings_payload(row)
