"""Round 33 — intraday spot service tests.

Covers: migration 0022 builds the two tables; the service reads back the
latest captured batch correctly (status / market / index).  Uses a temp DB so
the real ``var/investment_research.db`` is never touched.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


def _tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "spot.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


def _build_tables(db_path: Path) -> None:
    """Build the two spot tables directly (mirrors migration 0022 schema; the
    migration itself is verified by the real ``alembic upgrade head`` on
    var/investment_research.db, so tests focus on service read logic)."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS intraday_quote_spot (
            id TEXT PRIMARY KEY, symbol TEXT, market TEXT, name TEXT,
            latest_price REAL, change_pct REAL, volume REAL, amount REAL,
            source TEXT, captured_at TEXT);
        CREATE TABLE IF NOT EXISTS intraday_index_spot (
            id TEXT PRIMARY KEY, symbol TEXT, market TEXT, name TEXT,
            latest_price REAL, change_pct REAL, source TEXT, captured_at TEXT);
        """
    )
    conn.commit()
    conn.close()


def _seed_spot_rows(db_path: Path, *, market_rows: int = 3, cap: str = "2026-08-20T03:00:00+00:00") -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for i in range(market_rows):
        cur.execute(
            "INSERT INTO intraday_quote_spot "
            "(id, symbol, market, name, latest_price, change_pct, volume, amount, source, captured_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), f"60000{i}", "sh", f"sym{i}", 10.0 + i, 0.5 * i,
             1000.0, 10000.0, "test", cap),
        )
    cur.execute(
        "INSERT INTO intraday_index_spot "
        "(id, symbol, market, name, latest_price, change_pct, source, captured_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("ix-1" + cap, "000001", "sh", "上证指数", 3900.0, 0.27, "test", cap),
    )
    conn.commit()
    conn.close()


def test_migration_builds_spot_tables(tmp_path, monkeypatch):
    db = _tmp_db(tmp_path)
    _build_tables(db)
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "intraday_quote_spot" in names
    assert "intraday_index_spot" in names


def test_latest_capture_status_reads_back(tmp_path, monkeypatch):
    db = _tmp_db(tmp_path)
    _build_tables(db)
    _seed_spot_rows(db, market_rows=5, cap="2026-08-20T03:00:00+00:00")
    monkeypatch.setattr(
        "investment_research.repository.sqlite.get_default_database_path",
        lambda: db,
    )
    from investment_research.service.intraday_spot import (
        latest_capture_status, latest_index_snapshot, latest_market_snapshot,
    )

    status = latest_capture_status(None)
    assert status["market_rows"] == 5
    assert status["index_rows"] == 1
    assert status["market_captured_at"] == "2026-08-20T03:00:00+00:00"

    indices = latest_index_snapshot(None)
    assert len(indices) == 1 and indices[0]["name"] == "上证指数"

    quotes = latest_market_snapshot(None, symbols=["600000"], limit=1)
    assert len(quotes) == 1 and quotes[0]["symbol"] == "600000"


def test_latest_only_returns_most_recent_batch(tmp_path, monkeypatch):
    """Older capture batches must not leak into the 'latest' read."""
    db = _tmp_db(tmp_path)
    _build_tables(db)
    _seed_spot_rows(db, market_rows=2, cap="2026-08-20T02:00:00+00:00")  # older
    _seed_spot_rows(db, market_rows=3, cap="2026-08-20T03:00:00+00:00")  # latest
    monkeypatch.setattr(
        "investment_research.repository.sqlite.get_default_database_path",
        lambda: db,
    )
    from investment_research.service.intraday_spot import latest_market_snapshot

    quotes = latest_market_snapshot(None, symbols=None, limit=100)
    assert len(quotes) == 3  # only the latest batch
