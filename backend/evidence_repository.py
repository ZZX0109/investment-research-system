from __future__ import annotations

import sqlite3
from typing import Any


def count_active_evidence(conn: sqlite3.Connection, symbol: str) -> int:
    row = conn.execute(
        "select count(*) as count from evidence_records where symbol = ? and archived_at is null",
        (symbol,),
    ).fetchone()
    return int(row["count"])


def fetch_expired_evidence_rows(conn: sqlite3.Connection, now_iso: str) -> list[sqlite3.Row]:
    return conn.execute(
        "select * from evidence_records where archived_at is null and valid_until < ?",
        (now_iso,),
    ).fetchall()


def insert_experience_history(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    archived_claim: str,
    source_type: str,
    observed_at: str,
    archived_at: str,
    reason: str,
) -> None:
    conn.execute(
        """
        insert into experience_history(symbol, archived_claim, source_type, observed_at, archived_at, reason)
        values(?, ?, ?, ?, ?, ?)
        """,
        (symbol, archived_claim, source_type, observed_at, archived_at, reason),
    )


def mark_evidence_archived(conn: sqlite3.Connection, *, evidence_id: int, archived_at: str) -> None:
    conn.execute("update evidence_records set archived_at = ? where id = ?", (archived_at, evidence_id))


def insert_evidence_records(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    conn.executemany(
        """
        insert into evidence_records(symbol, claim, source_type, source_name, source_url, observed_at, valid_until, confidence, is_model_inferred)
        values(:symbol, :claim, :sourceType, :sourceName, :sourceUrl, :observedAt, :validUntil, :confidence, :isModelInferred)
        """,
        records,
    )


def insert_evidence_record(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    claim: str,
    source_type: str,
    source_name: str,
    source_url: str | None,
    observed_at: str,
    valid_until: str,
    confidence: float,
    is_model_inferred: bool,
) -> int:
    cursor = conn.execute(
        """
        insert into evidence_records(symbol, claim, source_type, source_name, source_url, observed_at, valid_until, confidence, is_model_inferred)
        values(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol,
            claim,
            source_type,
            source_name,
            source_url,
            observed_at,
            valid_until,
            confidence,
            int(is_model_inferred),
        ),
    )
    return int(cursor.lastrowid)


def fetch_active_evidence_rows(conn: sqlite3.Connection, symbol: str) -> list[sqlite3.Row]:
    return conn.execute(
        "select * from evidence_records where symbol = ? and archived_at is null and superseded_by is null order by observed_at desc",
        (symbol,),
    ).fetchall()


def fetch_active_evidence_ids_by_type(conn: sqlite3.Connection, *, symbol: str, source_type: str) -> list[int]:
    rows = conn.execute(
        "select id from evidence_records where symbol = ? and source_type = ? and archived_at is null",
        (symbol, source_type),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def mark_evidence_superseded(conn: sqlite3.Connection, *, evidence_ids: list[int], superseded_by: int) -> None:
    for evidence_id in evidence_ids:
        conn.execute("update evidence_records set superseded_by = ? where id = ?", (superseded_by, evidence_id))


def fetch_experience_history_rows(
    conn: sqlite3.Connection,
    *,
    symbol: str | None = None,
    limit: int = 12,
) -> list[sqlite3.Row]:
    if symbol:
        return conn.execute(
            "select * from experience_history where symbol = ? order by archived_at desc limit ?",
            (symbol, limit),
        ).fetchall()
    return conn.execute("select * from experience_history order by archived_at desc limit ?", (limit,)).fetchall()
