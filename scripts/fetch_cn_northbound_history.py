#!/usr/bin/env python3
"""Download resumable, dated A-share northbound holdings for model training.

The live Fortune adapter intentionally only fetches today's holding.  This
collector creates the separate historical panel required by the enhanced
CatBoost candidate, preserving each observation date instead of backfilling a
current value into the past.

Example:
    PYTHONPATH=src python scripts/fetch_cn_northbound_history.py --start 2015-01-01
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from pathlib import Path
from typing import Any

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path


PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "artifacts" / "cn_research_auxiliary" / "northbound_holdings.jsonl"
MANIFEST = PROJECT / "artifacts" / "cn_research_auxiliary" / "northbound_holdings_manifest.json"


def _date_chunks(start: date, end: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(end, date(current.year, 12, 31))
        chunks.append((current, chunk_end))
        current = date.fromordinal(chunk_end.toordinal() + 1)
    return chunks


def _parse_date(value: object) -> str | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _column(columns: list[str], *needles: str) -> str | None:
    return next((column for column in columns if all(needle in column for needle in needles)), None)


def _fetch_symbol(symbol: str, start: date, end: date) -> tuple[str, list[dict[str, Any]], list[str]]:
    import akshare as ak

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for begin, finish in _date_chunks(start, end):
        try:
            frame = ak.stock_hsgt_individual_detail_em(
                symbol=symbol, start_date=begin.strftime("%Y%m%d"), end_date=finish.strftime("%Y%m%d"),
            )
        except Exception as exc:  # network/provider failure stays visible in manifest
            errors.append(f"{begin}:{finish}:{type(exc).__name__}")
            continue
        if frame is None or len(frame) == 0:
            continue
        columns = [str(column) for column in frame.columns]
        date_col = _column(columns, "日期") or _column(columns, "持股", "日期") or _column(columns, "TRADE_DATE")
        pct_col = _column(columns, "持股", "占") or _column(columns, "持股", "比例")
        shares_col = _column(columns, "持股", "数量") or _column(columns, "持股", "数") or _column(columns, "持股", "量")
        if not date_col:
            errors.append(f"{begin}:{finish}:unrecognised_schema")
            continue
        grouped: dict[str, dict[str, float]] = {}
        value_change_1d_col = _column(columns, "持股市值变化", "1日")
        value_change_5d_col = _column(columns, "持股市值变化", "5日")
        for _, item in frame.iterrows():
            trade_date = _parse_date(item.get(date_col))
            if trade_date is None:
                continue
            bucket = grouped.setdefault(trade_date, {
                "holding_pct": 0.0, "holding_shares": 0.0,
                "northbound_value_change_1d": 0.0, "northbound_value_change_5d": 0.0,
            })
            for field, column in (
                ("holding_pct", pct_col), ("holding_shares", shares_col),
                ("northbound_value_change_1d", value_change_1d_col),
                ("northbound_value_change_5d", value_change_5d_col),
            ):
                value = _number(item.get(column)) if column else None
                if value is not None:
                    bucket[field] += value
        for trade_date, aggregate in grouped.items():
            records.append({
                "schema_version": "northbound-holdings-v1", "symbol": symbol,
                "trade_date": trade_date, **aggregate,
                "provider": "akshare/eastmoney", "source_dataset": "stock_hsgt_individual_detail_em",
            })
    return symbol, records, errors


def _existing_records() -> dict[tuple[str, str], dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        lines = OUTPUT.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        try:
            row = json.loads(line)
            records[(str(row["symbol"]).zfill(6), str(row["trade_date"])[:10])] = row
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=None, help="defaults to the latest local daily bar")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--symbols", nargs="*", default=None)
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    uow = SQLiteUnitOfWork(get_default_database_path())
    try:
        if args.symbols:
            symbols = sorted({str(symbol).zfill(6) for symbol in args.symbols})
        else:
            symbols = [row[0] for row in uow.connection.execute("SELECT DISTINCT symbol FROM versioned_market_bars WHERE interval='1d' ORDER BY symbol")]
        latest = uow.connection.execute("SELECT MAX(trade_date) FROM versioned_market_bars WHERE interval='1d'").fetchone()[0]
    finally:
        uow.close()
    end = date.fromisoformat(args.end) if args.end else date.fromisoformat(str(latest))
    existing = _existing_records()
    failures: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(_fetch_symbol, symbol, start, end) for symbol in symbols]
        for future in as_completed(futures):
            symbol, records, errors = future.result()
            for row in records:
                existing[(row["symbol"], row["trade_date"])] = row
            if errors:
                failures[symbol] = errors
            print(f"{symbol}: {len(records)} rows" + (f" ({len(errors)} failed chunks)" if errors else ""))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    ordered = [existing[key] for key in sorted(existing)]
    temp = OUTPUT.with_suffix(".jsonl.tmp")
    temp.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in ordered), encoding="utf-8")
    temp.replace(OUTPUT)
    observed_dates = sorted({str(row["trade_date"]) for row in ordered})
    coverage_complete = bool(observed_dates) and observed_dates[0] <= start.isoformat() and observed_dates[-1] >= end.isoformat()
    MANIFEST.write_text(json.dumps({
        "schema_version": "northbound-holdings-manifest-v1", "status": "complete" if not failures and coverage_complete else "partial",
        "row_count": len(ordered), "symbol_count": len({row["symbol"] for row in ordered}),
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "observed_start": observed_dates[0] if observed_dates else None,
        "observed_end": observed_dates[-1] if observed_dates else None,
        "failures": failures,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(ordered), "symbols": len(symbols), "failed_symbols": len(failures)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
