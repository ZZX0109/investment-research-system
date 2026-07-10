from __future__ import annotations

import sqlite3
from typing import Any


def fetch_latest_document(conn: sqlite3.Connection, symbol: str) -> sqlite3.Row | None:
    return conn.execute(
        "select * from multimodal_documents where symbol = ? order by uploaded_at desc limit 1",
        (symbol,),
    ).fetchone()


def fetch_document_metrics(conn: sqlite3.Connection, document_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "select metric_name, metric_value, period, source_block from financial_metrics where document_id = ?",
        (document_id,),
    ).fetchall()


def fetch_document_blocks(conn: sqlite3.Connection, document_id: str, *, limit: int = 12) -> list[sqlite3.Row]:
    return conn.execute(
        "select block_type, label, locator, content_preview from document_blocks where document_id = ? order by id limit ?",
        (document_id, limit),
    ).fetchall()


def upsert_multimodal_document(conn: sqlite3.Connection, payload: dict[str, Any], *, source_type: str) -> None:
    conn.execute(
        """
        insert or replace into multimodal_documents(document_id, symbol, filename, uploaded_at, source_type, text_blocks, table_blocks, chart_blocks, footnote_blocks, summary)
        values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["document_id"],
            payload["symbol"],
            payload["filename"],
            payload["uploaded_at"],
            source_type,
            payload["text_blocks"],
            payload["table_blocks"],
            payload["chart_blocks"],
            payload["footnote_blocks"],
            payload["summary"],
        ),
    )


def replace_financial_metrics(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    conn.execute("delete from financial_metrics where document_id = ?", (payload["document_id"],))
    conn.executemany(
        """
        insert into financial_metrics(document_id, symbol, metric_name, metric_value, period, source_block)
        values(?, ?, ?, ?, ?, ?)
        """,
        [
            (payload["document_id"], payload["symbol"], name, value, period, block)
            for name, value, period, block in payload["metrics"]
        ],
    )


def replace_document_blocks(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    conn.execute("delete from document_blocks where document_id = ?", (payload["document_id"],))
    conn.executemany(
        """
        insert into document_blocks(document_id, symbol, block_type, label, locator, content_preview, created_at)
        values(?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                payload["document_id"],
                payload["symbol"],
                block["block_type"],
                block["label"],
                block["locator"],
                block["content_preview"],
                payload["uploaded_at"],
            )
            for block in payload["blocks"]
        ],
    )
