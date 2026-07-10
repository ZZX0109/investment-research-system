from __future__ import annotations

import sqlite3


def fetch_report_settings(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("select * from report_settings where id = 1").fetchone()


def upsert_report_settings(conn: sqlite3.Connection, *, frequency: str, updated_at: str) -> None:
    conn.execute(
        "insert or replace into report_settings(id, frequency, updated_at) values(1, ?, ?)",
        (frequency, updated_at),
    )


def ensure_default_report_settings(conn: sqlite3.Connection, *, updated_at: str) -> None:
    row = conn.execute("select count(*) as count from report_settings").fetchone()
    if int(row["count"]) == 0:
        upsert_report_settings(conn, frequency="weekly", updated_at=updated_at)
