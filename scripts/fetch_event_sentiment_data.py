#!/usr/bin/env python3
"""Fetch event-side + sentiment-side data for the 162-symbol CN research universe.

Data sources (akshare, verified working on the GPU pod):
  * event actuals   : stock_financial_abstract(symbol)        -> per-report EPS/net-profit/revenue/YoY (history back to ~2010)
  * event consensus : stock_profit_forecast_ths(symbol, indicator) -> annual consensus EPS / net-profit (mean = consensus)
  * event notices   : stock_individual_notice_report(security=code, symbol=type, begin_date, end_date) -> dated announcements (history)
  * sentiment news  : stock_news_em(symbol)                    -> ~10 recent news per symbol (title+content+time)

Stored in the production DB (var/investment_research.db) as four new tables so
the enriched panel builder (retrain_long_term_enriched + the new event/sentiment
extension) can join them PIT-correctly.  Resume via a per-endpoint progress JSON.

Usage:
    NODE_ENV=development python3 -m scripts.fetch_event_sentiment_data --endpoint all
    NODE_ENV=development python3 -m scripts.fetch_event_sentiment_data --endpoint actuals
    NODE_ENV=development python3 -m scripts.fetch_event_sentiment_data --endpoint consensus
    NODE_ENV=development python3 -m scripts.fetch_event_sentiment_data --endpoint notices
    NODE_ENV=development python3 -m scripts.fetch_event_sentiment_data --endpoint news
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
from typing import Any, Iterable

import akshare as ak
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
log = logging.getLogger("fetch_event_sentiment")

# metrics to extract from stock_financial_abstract (row label = 指标)
FA_METRICS = [
    "基本每股收益", "归母净利润", "营业总收入", "净利润", "扣非净利润",
    "归属母公司净利润增长率", "营业总收入增长率", "净资产收益率(ROE)",
    "每股净资产", "毛利率", "销售净利率",
]
FORECAST_INDICATORS = ["预测年报每股收益", "预测年报净利润"]
NOTICE_TYPES = ["全部"]  # one call per symbol returns all types; classify later by keyword
NOTICE_BEGIN = "2020-01-01"
NOTICE_END = datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_symbols() -> list[str]:
    cfg = json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text())
    syms = [str(x).zfill(6) for x in cfg["cn"] if not str(x).zfill(6).startswith(("1", "5"))]
    return syms


def _db_path() -> Path:
    p = Path(PROJECT / "var/investment_research.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _create_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_financial_actual (
            symbol TEXT, report_period TEXT, metric TEXT, value REAL, fetched_at TEXT,
            PRIMARY KEY (symbol, report_period, metric));
        CREATE TABLE IF NOT EXISTS event_consensus_forecast (
            symbol TEXT, fiscal_year TEXT, metric TEXT, n_institutions REAL,
            mean REAL, min REAL, max REAL, industry_avg REAL, fetched_at TEXT,
            PRIMARY KEY (symbol, fiscal_year, metric));
        CREATE TABLE IF NOT EXISTS event_notice (
            symbol TEXT, notice_date TEXT, title TEXT, notice_type TEXT,
            source TEXT, fetched_at TEXT,
            PRIMARY KEY (symbol, notice_date, title));
        CREATE TABLE IF NOT EXISTS sentiment_news (
            symbol TEXT, published_at TEXT, title TEXT, content TEXT,
            source TEXT, url TEXT, fetched_at TEXT,
            PRIMARY KEY (symbol, published_at, title));
        CREATE INDEX IF NOT EXISTS ix_fa_sym ON event_financial_actual(symbol);
        CREATE INDEX IF NOT EXISTS ix_cf_sym ON event_consensus_forecast(symbol);
        CREATE INDEX IF NOT EXISTS ix_en_sym ON event_notice(symbol);
        CREATE INDEX IF NOT EXISTS ix_sn_sym ON sentiment_news(symbol);
        """
    )
    conn.commit()


# ---------- per-endpoint fetchers (return list[dict]) ----------

def fetch_actuals(symbol: str) -> list[dict]:
    df = ak.stock_financial_abstract(symbol=symbol)
    rows: list[dict] = []
    if df is None or df.empty:
        return rows
    # columns after 选项/指标 are report periods (YYYYMMDD)
    period_cols = [c for c in df.columns if c not in ("选项", "指标")]
    for _, r in df.iterrows():
        metric = str(r["指标"]).strip()
        if metric not in FA_METRICS:
            continue
        for p in period_cols:
            try:
                v = r[p]
            except Exception:
                continue
            if pd.isna(v) or v in ("", None, "--"):
                continue
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            rows.append({"symbol": symbol, "report_period": str(p), "metric": metric, "value": val, "fetched_at": _now()})
    return rows


def fetch_consensus(symbol: str) -> list[dict]:
    rows: list[dict] = []
    for indicator in FORECAST_INDICATORS:
        try:
            df = ak.stock_profit_forecast_ths(symbol=symbol, indicator=indicator)
        except Exception as e:
            log.warning("consensus %s %s fail: %s", symbol, indicator, e)
            continue
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            try:
                rows.append({
                    "symbol": symbol, "fiscal_year": str(r["年度"]), "metric": indicator,
                    "n_institutions": _f(r.get("预测机构数")), "mean": _f(r.get("均值")),
                    "min": _f(r.get("最小值")), "max": _f(r.get("最大值")),
                    "industry_avg": _f(r.get("行业平均数")), "fetched_at": _now(),
                })
            except Exception:
                continue
    return rows


def fetch_notices(symbol: str) -> list[dict]:
    rows: list[dict] = []
    for ntype in NOTICE_TYPES:
        try:
            df = ak.stock_individual_notice_report(
                security=symbol, symbol=ntype, begin_date=NOTICE_BEGIN, end_date=NOTICE_END
            )
        except Exception as e:
            log.warning("notices %s %s fail: %s", symbol, ntype, e)
            continue
        if df is None or df.empty:
            continue
        cols = list(df.columns)
        # locate title / date / type columns defensively (eastmoney returns Chinese headers)
        title_col = _first(cols, ["公告标题", "标题", "title"])
        date_col = _first(cols, ["公告日期", "公告时间", "日期", "date"])
        type_col = _first(cols, ["公告类型", "类型", "报告类型"])
        src_col = _first(cols, ["文章来源", "来源", "source"])
        for _, r in df.iterrows():
            title = str(r.get(title_col, "")).strip() if title_col else ""
            ndate = str(r.get(date_col, "")).strip() if date_col else ""
            if not title or not ndate:
                continue
            rows.append({
                "symbol": symbol, "notice_date": ndate[:10], "title": title[:500],
                "notice_type": str(r.get(type_col, ntype)).strip() if type_col else ntype,
                "source": str(r.get(src_col, "")).strip() if src_col else "",
                "fetched_at": _now(),
            })
    return rows


def fetch_news(symbol: str) -> list[dict]:
    df = ak.stock_news_em(symbol=symbol)
    rows: list[dict] = []
    if df is None or df.empty:
        return rows
    for _, r in df.iterrows():
        title = str(r.get("新闻标题", "")).strip()
        published = str(r.get("发布时间", "")).strip()
        if not title or not published:
            continue
        rows.append({
            "symbol": symbol, "published_at": published, "title": title[:500],
            "content": str(r.get("新闻内容", ""))[:4000], "source": str(r.get("文章来源", "")).strip(),
            "url": str(r.get("新闻链接", "")), "fetched_at": _now(),
        })
    return rows


# ---------- helpers ----------

def _f(v: Any) -> float | None:
    try:
        if pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _first(cols: list[str], names: Iterable[str]) -> str | None:
    cmap = {c: c for c in cols}
    for n in names:
        if n in cmap:
            return n
    # fuzzy: contains
    for n in names:
        for c in cols:
            if n in c:
                return c
    return None


def _persist(conn: sqlite3.Connection, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, [[r[c] for c in cols] for r in rows])
    conn.commit()
    return len(rows)


def _progress_path(endpoint: str) -> Path:
    d = PROJECT / "artifacts/event_sentiment_fetch"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"progress_{endpoint}.json"


def _load_progress(endpoint: str) -> dict:
    p = _progress_path(endpoint)
    if p.exists():
        return json.loads(p.read_text())
    return {"symbols": {}}


def _save_progress(endpoint: str, prog: dict) -> None:
    _progress_path(endpoint).write_text(json.dumps(prog, ensure_ascii=False, indent=2))


ENDPOINTS = {
    "actuals": fetch_actuals,
    "consensus": fetch_consensus,
    "notices": fetch_notices,
    "news": fetch_news,
}
TABLES = {
    "actuals": "event_financial_actual",
    "consensus": "event_consensus_forecast",
    "notices": "event_notice",
    "news": "sentiment_news",
}


def run_endpoint(endpoint: str, symbols: list[str], workers: int, no_resume: bool, max_symbols: int | None) -> dict:
    fetcher = ENDPOINTS[endpoint]
    table = TABLES[endpoint]
    prog = {"symbols": {}} if no_resume else _load_progress(endpoint)
    prog.setdefault("symbols", {})
    pending = [s for s in symbols if prog["symbols"].get(s, {}).get("status") != "complete"]
    if max_symbols:
        pending = pending[:max_symbols]
    log.info("[%s] total=%d pending=%d workers=%d", endpoint, len(symbols), len(pending), workers)
    conn = sqlite3.connect(_db_path(), timeout=60.0)
    _create_tables(conn)
    conn.close()
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        futures = {pool.submit(_safe_fetch_persist, endpoint, fetcher, table, s): s for s in pending}
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"status": "failed", "reason": f"{type(e).__name__}:{e}"}
            prog["symbols"][s] = res
            done += 1
            if done % 10 == 0 or done == len(pending):
                _save_progress(endpoint, prog)
                rate = done / max(1e-6, time.time() - t0)
                log.info("[%s] %d/%d done (%.1f/s) last=%s %s", endpoint, done, len(pending), rate, s, res.get("status"))
    _save_progress(endpoint, prog)
    complete = [s for s, v in prog["symbols"].items() if v.get("status") == "complete"]
    failed = {s: v for s, v in prog["symbols"].items() if v.get("status") != "complete"}
    summary = {
        "endpoint": endpoint, "total": len(symbols), "pending": len(pending),
        "completed": len(complete), "failed": len(failed),
        "total_rows": sum(int(v.get("rows", 0)) for v in prog["symbols"].values()),
        "status": "complete" if not failed else "partial", "elapsed_s": round(time.time() - t0, 1),
    }
    log.info("[%s] SUMMARY: %s", endpoint, json.dumps(summary, ensure_ascii=False))
    out = _progress_path(endpoint).parent / f"latest_{endpoint}.json"
    out.write_text(json.dumps({**summary, "failed": failed}, ensure_ascii=False, indent=2))
    return summary


def _safe_fetch_persist(endpoint: str, fetcher, table: str, symbol: str) -> dict:
    try:
        rows = fetcher(symbol)
        conn = sqlite3.connect(_db_path(), timeout=60.0)
        _create_tables(conn)
        n = _persist(conn, table, rows)
        conn.close()
        return {"status": "complete", "rows": n}
    except Exception as e:
        log.warning("[%s] %s error: %s\n%s", endpoint, symbol, e, traceback.format_exc()[:600])
        return {"status": "failed", "reason": f"{type(e).__name__}:{e}", "rows": 0}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch event + sentiment data for CN universe")
    p.add_argument("--endpoint", choices=list(ENDPOINTS) + ["all"], default="all")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--max-symbols", type=int, default=None)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    symbols = load_symbols()
    log.info("universe: %d equity symbols", len(symbols))
    endpoints = list(ENDPOINTS) if args.endpoint == "all" else [args.endpoint]
    conn = sqlite3.connect(_db_path(), timeout=60.0)
    _create_tables(conn)
    conn.close()
    all_summary = {}
    for ep in endpoints:
        all_summary[ep] = run_endpoint(ep, symbols, args.workers, args.no_resume, args.max_symbols)
    (PROJECT / "artifacts/event_sentiment_fetch/latest_all.json").write_text(
        json.dumps(all_summary, ensure_ascii=False, indent=2))
    print(json.dumps(all_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
