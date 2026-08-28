"""Round 33 — intraday spot capture service.

Polls the full A-share spot snapshot + the three major indices hourly during
CN trading sessions and persists them to ``intraday_quote_spot`` /
``intraday_index_spot`` so the "盘中行情" board and the LLM snapshot can read
the latest spot without blocking on a live akshare call.

Design notes (honest about akshare limits):
* ``stock_zh_a_spot`` (SINA, 70-page batched) succeeds ~half the time on this
  network — a mid-batch page returns non-JSON and the whole batch raises.
  We do NOT bypass akshare's pagination; instead we retry the whole batch 2×
  (the failure is intermittent, a retry usually succeeds) and persist whatever
  succeeds.  On total failure we log + leave the previous snapshot in place;
  the async worker retries next tick.
* The async worker (``scripts/run_intraday_spot_worker.py``) runs out-of-process
  so a flaky/slow akshare call never blocks the API; the API only reads the
  latest persisted snapshot.
* NOT a tick push stream — this is the latest spot snapshot, normally polled
  every five minutes by the competition worker.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from investment_research.integrations.xystock.quote_fetcher import (
    fetch_etf_spot,
    fetch_index_spot,
    fetch_market_spot,
)

log = logging.getLogger("intraday_spot")

_INDEX_CODES = ["000001", "399001", "399006"]  # 上证综指 / 深证成指 / 创业板指
_PAPER_ETF_CODES = ["510050", "510300", "510500", "159915", "512100", "518880"]
_SOURCE = "xystock/akshare-sina"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture_market_spot(uow, *, retries: int = 2, retry_delay: float = 5.0) -> dict:
    """Fetch the full A-share spot snapshot (with ``retries`` whole-batch
    retries on failure) and persist every row that arrives.  Returns a summary
    dict (n_persisted / status / error).  Never raises — callers (the async
    worker) rely on this to log + move on."""

    captured_at = _now_iso()
    last_err: str | None = None
    result = None
    for attempt in range(retries + 1):
        result = fetch_market_spot()
        if result.available and result.data:
            break
        last_err = result.error or result.status
        log.warning(
            "market_spot attempt %d/%d failed: %s", attempt + 1, retries + 1, last_err
        )
        if attempt < retries:
            time.sleep(retry_delay)
    etf_result = fetch_etf_spot(_PAPER_ETF_CODES)
    stock_rows = result.data if result and result.available and result.data else []
    etf_rows = etf_result.data if etf_result.available and etf_result.data else []
    if not stock_rows and not etf_rows:
        return {"captured_at": captured_at, "n_persisted": 0, "status": "failed", "error": last_err}

    rows = [*stock_rows, *etf_rows]
    cur = uow.connection.cursor()
    inserted = 0
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        cur.execute(
            "INSERT INTO intraday_quote_spot "
            "(id, symbol, market, name, latest_price, change_pct, volume, amount, source, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), sym, r.get("market"), r.get("name"),
                r.get("latest_price"), r.get("change_pct"),
                r.get("volume"), r.get("amount"), _SOURCE, captured_at,
            ),
        )
        inserted += 1
    uow.connection.commit()
    log.info("market_spot persisted %d rows @ %s", inserted, captured_at)
    return {"captured_at": captured_at, "n_persisted": inserted, "status": "ok", "error": None}


def capture_index_spot(uow) -> dict:
    """Fetch the three major indices and persist.  Single attempt (index
    endpoint is stable, ~3/3 success rate); never raises."""

    captured_at = _now_iso()
    result = fetch_index_spot(_INDEX_CODES)
    if not result.available or not result.data:
        return {"captured_at": captured_at, "n_persisted": 0, "status": "failed", "error": result.error}
    cur = uow.connection.cursor()
    inserted = 0
    for r in result.data:
        cur.execute(
            "INSERT INTO intraday_index_spot "
            "(id, symbol, market, name, latest_price, change_pct, source, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), r.get("symbol"), r.get("market"), r.get("name"),
                r.get("latest_price"), r.get("change_pct"), _SOURCE, captured_at,
            ),
        )
        inserted += 1
    uow.connection.commit()
    log.info("index_spot persisted %d rows @ %s", inserted, captured_at)
    return {"captured_at": captured_at, "n_persisted": inserted, "status": "ok", "error": None}


def capture_now(uow) -> dict:
    """Capture market + index spot in one pass.  Each is independent — a
    market-spot failure does not block the (stable) index capture."""
    return {
        "market": capture_market_spot(uow),
        "index": capture_index_spot(uow),
    }


def _read_conn():
    """Independent read connection with ``sqlite3.Row`` (the uow's
    ``NamedTupleRow`` does not expose aggregate aliases like MAX(...), so reads
    use this instead).  Reads are short-lived point lookups."""
    import sqlite3

    from investment_research.repository.sqlite import get_default_database_path

    conn = sqlite3.connect(get_default_database_path())
    conn.row_factory = sqlite3.Row
    return conn


def _latest_captured_at(table: str) -> str | None:
    conn = _read_conn()
    try:
        row = conn.execute(f"SELECT MAX(captured_at) AS m FROM {table}").fetchone()
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()


def latest_market_snapshot(uow, *, symbols: list[str] | None = None, limit: int = 200) -> list[dict]:
    """Latest per-symbol spot rows (the most recent successful capture batch).
    If ``symbols`` given, filter to those; else the top ``limit`` by amount."""

    cap = _latest_captured_at("intraday_quote_spot")
    if not cap:
        return []
    conn = _read_conn()
    try:
        if symbols:
            placeholders = ",".join("?" * len(symbols))
            rows = conn.execute(
                f"SELECT symbol, market, name, latest_price, change_pct, volume, amount, captured_at "
                f"FROM intraday_quote_spot WHERE captured_at = ? AND symbol IN ({placeholders})",
                (cap, *symbols),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT symbol, market, name, latest_price, change_pct, volume, amount, captured_at "
                "FROM intraday_quote_spot WHERE captured_at = ? "
                "ORDER BY amount DESC LIMIT ?",
                (cap, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def latest_index_snapshot(uow) -> list[dict]:
    cap = _latest_captured_at("intraday_index_spot")
    if not cap:
        return []
    conn = _read_conn()
    try:
        rows = conn.execute(
            "SELECT symbol, market, name, latest_price, change_pct, captured_at "
            "FROM intraday_index_spot WHERE captured_at = ? ORDER BY symbol",
            (cap,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def latest_capture_status(uow) -> dict:
    """Summary for the API: latest captured_at + counts, so the board can show
    "最近更新 10:54 · 5547 标的 · 3 指数"."""
    conn = _read_conn()
    try:
        mk_cap = conn.execute("SELECT MAX(captured_at) AS m FROM intraday_quote_spot").fetchone()[0]
        ix_cap = conn.execute("SELECT MAX(captured_at) AS m FROM intraday_index_spot").fetchone()[0]
        mk_n = 0
        if mk_cap:
            mk_n = conn.execute(
                "SELECT COUNT(*) AS c FROM intraday_quote_spot WHERE captured_at = ?", (mk_cap,)
            ).fetchone()[0]
        ix_n = 0
        if ix_cap:
            ix_n = conn.execute(
                "SELECT COUNT(*) AS c FROM intraday_index_spot WHERE captured_at = ?", (ix_cap,)
            ).fetchone()[0]
    finally:
        conn.close()
    return {
        "market_captured_at": mk_cap, "market_rows": mk_n,
        "index_captured_at": ix_cap, "index_rows": ix_n,
    }
