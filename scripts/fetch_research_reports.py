#!/usr/bin/env python3
"""Fetch dated analyst research reports (rating + coverage) for the 162-symbol universe.

stock_research_report_em(symbol) returns per-symbol reports dated 2017-2026 with
东财评级 (买入/增持/持有/中性/卖出) and 近一月个股研报数 (coverage intensity).  These are
PIT-honest (a report's rating is known on its 日期), full historical coverage, and capture
analyst ACTIONS the keyword-notice features miss.

NOTE: the "盈利预测-收益" columns are relabeled to current forward years on every fetch,
so old reports' forecast-EPS values are semantically suspect (possible current-snapshot).
We DO NOT use forecast-EPS for surprise (look-ahead risk) — only rating + report count.

Stored in var/investment_research.db table event_research_report.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import akshare as ak
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
DB = Path(PROJECT / "var/investment_research.db")
log = logging.getLogger("fetch_reports")
RATING_MAP = {"买入": 2, "增持": 1, "中性": 0, "持有": 0, "卖出": -1, "": 0}


def load_symbols() -> list[str]:
    cfg = json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text())
    return [str(x).zfill(6) for x in cfg["cn"] if not str(x).zfill(6).startswith(("1", "5"))]


def _create(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_research_report (
            symbol TEXT, report_date TEXT, rating TEXT, rating_score INT,
            report_count_1m REAL, fetched_at TEXT,
            PRIMARY KEY (symbol, report_date, rating));
        CREATE INDEX IF NOT EXISTS ix_rr_sym ON event_research_report(symbol);
        """
    )
    conn.commit()


def fetch(symbol: str) -> list[dict]:
    df = ak.stock_research_report_em(symbol=symbol)
    rows = []
    if df is None or df.empty:
        return rows
    for _, r in df.iterrows():
        rd = str(r.get("日期", "")).strip()
        rating = str(r.get("东财评级", "")).strip()
        cnt = r.get("近一月个股研报数")
        if not rd:
            continue
        try:
            cnt = float(cnt) if not pd.isna(cnt) else None
        except (TypeError, ValueError):
            cnt = None
        rows.append({
            "symbol": symbol, "report_date": rd[:10], "rating": rating,
            "rating_score": RATING_MAP.get(rating, 0), "report_count_1m": cnt,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    return rows


def _safe(symbol: str) -> dict:
    try:
        rows = fetch(symbol)
        conn = sqlite3.connect(str(DB), timeout=60.0)
        _create(conn)
        if rows:
            cols = list(rows[0].keys())
            ph = ",".join("?" for _ in cols)
            conn.executemany(f"INSERT OR REPLACE INTO event_research_report ({','.join(cols)}) VALUES ({ph})",
                             [[r[c] for c in cols] for r in rows])
            conn.commit()
        conn.close()
        return {"status": "complete", "rows": len(rows)}
    except Exception as e:
        log.warning("%s error: %s\n%s", symbol, e, traceback.format_exc()[:400])
        return {"status": "failed", "reason": f"{type(e).__name__}:{e}", "rows": 0}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=None)
    args = ap.parse_args()
    symbols = load_symbols()
    if args.max_symbols:
        symbols = symbols[:args.max_symbols]
    prog_path = PROJECT / "artifacts/event_sentiment_fetch/progress_reports.json"
    prog_path.parent.mkdir(parents=True, exist_ok=True)
    prog = {"symbols": {}} if args.no_resume else (json.loads(prog_path.read_text()) if prog_path.exists() else {"symbols": {}})
    prog.setdefault("symbols", {})
    pending = [s for s in symbols if prog["symbols"].get(s, {}).get("status") != "complete"]
    log.info("total=%d pending=%d", len(symbols), len(pending))
    done = 0
    t0 = time.time()
    conn = sqlite3.connect(str(DB), timeout=60.0)
    _create(conn)
    conn.close()
    with ThreadPoolExecutor(max_workers=min(args.workers, 6)) as pool:
        futs = {pool.submit(_safe, s): s for s in pending}
        for f in as_completed(futs):
            s = futs[f]
            try:
                prog["symbols"][s] = f.result()
            except Exception as e:
                prog["symbols"][s] = {"status": "failed", "reason": str(e)}
            done += 1
            if done % 10 == 0 or done == len(pending):
                prog_path.write_text(json.dumps(prog, ensure_ascii=False, indent=2))
                log.info("%d/%d (%.1f/s)", done, len(pending), done / max(1e-6, time.time() - t0))
    prog_path.write_text(json.dumps(prog, ensure_ascii=False, indent=2))
    complete = [s for s, v in prog["symbols"].items() if v.get("status") == "complete"]
    total_rows = sum(int(v.get("rows", 0)) for v in prog["symbols"].values())
    summary = {"total": len(symbols), "completed": len(complete), "total_rows": total_rows, "status": "complete" if len(complete) == len(symbols) else "partial"}
    print(json.dumps(summary, ensure_ascii=False))
    (prog_path.parent / "latest_reports.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
