#!/usr/bin/env python3
"""Fetch quickRatio/cashRatio from akshare stock_financial_analysis_indicator
for symbols missing these ratios, and persist to the catalog as a new
research dataset.

This is a public source (Sina financial analysis indicators) that provides
速动比率(quickRatio) and 现金比率(cashRatio) directly.  Banks and financial
stocks will have nan values (they genuinely don't have these ratios).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

import akshare as ak
from hashlib import sha256

CATALOG = PROJECT / "var/cn-research/catalog.db"
RAW_ROOT = PROJECT / "var/cn-research/raw/raw-market"

# Chinese → English field mapping, grouped by family
FIELD_MAP = {
    "balance": {
        "速动比率": "quickRatio",
        "现金比率(%)": "cashRatio",
        "流动比率": "currentRatio",
    },
    "growth": {
        "总资产增长率(%)": "YOYAsset",
        "净资产增长率(%)": "YOYEquity",
        "净利润增长率(%)": "YOYNI",
    },
}


def _find_missing_symbols(limit: int = 200) -> list[tuple[str, int]]:
    """Find symbols with the most *unique* missing quick-ratio periods.

    The catalog can contain several provider/family rows for the same
    symbol-period.  Counting every null row over-prioritised symbols with
    duplicated records even when another row already supplied the ratio.
    """
    conn = sqlite3.connect(CATALOG)
    from collections import defaultdict
    periods: dict[str, dict[str, dict[str, bool]]] = defaultdict(dict)
    # Inspect every canonical financial source, not only the backfill dataset.
    # The main Eastmoney/fundamentals feeds may already contain a ratio for a
    # symbol-period; ignoring them causes repeated downloads that do not move
    # coverage.  Values are still read-only here and provider rows are never
    # overwritten by the collector.
    for (pj,) in conn.execute(
        "SELECT payload_json FROM raw_data_batches WHERE dataset IN ("
        "'cn_fundamentals_research',"
        "'cn_financial_eastmoney_research',"
        "'cn_financial_ratios_akshare_research',"
        "'cn_financial_analysis_indicator_research')"
    ).fetchall():
        if not pj:
            continue
        p = json.loads(pj)
        ref = p.get("payload_ref", "").replace("file-object://", "")
        fpath = PROJECT / "var/cn-research/raw" / ref
        if not fpath.is_file():
            continue
        data = json.loads(fpath.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("rows", data.get("data", []))
        for r in rows:
            if not isinstance(r, dict) or r.get("feature_family") != "balance":
                continue
            sym = str(r.get("code") or r.get("symbol") or "").replace("sz.", "").replace("sh.", "").upper()
            period = str(r.get("statDate") or r.get("report_period") or "")[:10]
            if not sym or not period:
                continue
            state = periods[sym].setdefault(period, {"quick": False, "cash": False})
            state["quick"] = state["quick"] or r.get("quickRatio") is not None
            state["cash"] = state["cash"] or r.get("cashRatio") is not None
    conn.close()
    missing = {
        symbol: sum(not values["quick"] for values in period_map.values())
        for symbol, period_map in periods.items()
    }
    return sorted(missing.items(), key=lambda x: (-x[1], x[0]))[:limit]


def _persist(
    symbol: str,
    records: list[dict],
    *,
    provider: str = "akshare_fai",
    request_prefix: str = "fai",
) -> int:
    """Persist fetched records to catalog."""
    if not records:
        return 0
    conn = sqlite3.connect(CATALOG)
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for rec in records:
        # Store as a list so the coverage script's isinstance(payload, list)
        # check correctly extracts the record.
        blob = json.dumps([rec], ensure_ascii=False, default=str).encode("utf-8")
        h = sha256(blob).hexdigest()
        opath = RAW_ROOT / "sha256" / h[:2] / f"{h}.json"
        opath.parent.mkdir(parents=True, exist_ok=True)
        opath.write_bytes(blob)
        pj = json.dumps({
            "payload_ref": f"file-object://raw-market/sha256/{h[:2]}/{h}.json",
            "symbol": symbol, "dataset": "cn_financial_analysis_indicator_research",
            "coverage_end": rec.get("statDate", "") + "T23:59:59.999999Z" if rec.get("statDate") else None,
            "coverage_start": rec.get("statDate", "") + "T00:00:00.000000Z" if rec.get("statDate") else None,
        }, ensure_ascii=False)
        family = rec.get("feature_family", "unknown")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO raw_data_batches (id, provider, request_id, dataset, fetched_at, available_at, quality_status, payload_json, data_tier, time_semantics) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), provider, f"{request_prefix}-{symbol}-{family}-{rec.get('statDate','')}",
             "cn_financial_analysis_indicator_research", now, now, "complete",
             pj, "research_pit", "research_collection_time_semantics"),
        )
        # The collector is intentionally restartable.  A previous partial
        # run may already have persisted the same symbol/family/period; the
        # unique provider/request_id constraint then makes this row a no-op
        # rather than aborting the entire batch.
        count += int(cursor.rowcount > 0)
    conn.commit()
    conn.close()
    return count


def fetch_symbol(symbol: str, start_year: str = "2018") -> list[dict]:
    """Fetch financial analysis indicators for one symbol."""
    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year=start_year)
        records = []
        prefix = "sh" if symbol.startswith("6") else "sz"
        for _, row in df.iterrows():
            date_str = str(row.get("日期", ""))[:10]
            if not date_str:
                continue
            # Split into balance and growth records so the coverage script
            # checks each family's fields under the correct family name.
            for family, field_map in FIELD_MAP.items():
                rec = {
                    "code": f"{prefix}.{symbol.lower()}",
                    "symbol": symbol,
                    "statDate": date_str,
                    "feature_family": family,
                    "source_provider": "akshare_fai",
                    "source_metric_label": "financial_analysis_indicator",
                }
                has_value = False
                for cn, en in field_map.items():
                    val = row.get(cn)
                    if val is not None and str(val).strip() not in ("", "nan", "None"):
                        try:
                            rec[en] = float(val)
                            has_value = True
                        except (TypeError, ValueError):
                            pass
                if has_value:
                    records.append(rec)
        return records
    except Exception as e:
        print(f"  {symbol} FAIL: {str(e)[:60]}", file=sys.stderr)
        return []


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--start-year", type=str, default="2018")
    args = parser.parse_args()

    symbols = _find_missing_symbols(args.limit)
    print(f"[fai] fetching {len(symbols)} symbols (top missing quickRatio)")

    total = 0
    for i, (sym, missing_count) in enumerate(symbols):
        records = fetch_symbol(sym, args.start_year)
        if records:
            count = _persist(sym, records)
            total += count
        if (i + 1) % 20 == 0:
            print(f"[fai] progress: {i+1}/{len(symbols)} symbols, {total} records", file=sys.stderr)
        time.sleep(0.5)  # rate limit

    print(f"[fai] done: {total} records from {len(symbols)} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
