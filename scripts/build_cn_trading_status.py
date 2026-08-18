#!/usr/bin/env python3
"""Materialize an auditable trading-status dataset from standard CN bars.

The source standard bars are read-only.  The derived status file is marked
degraded when historical publication time is not independently proven; this
fills a missing data category without pretending to solve PIT availability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def build_status_rows(source_root: Path) -> list[dict]:
    import pyarrow.dataset as ds

    if not source_root.is_dir():
        raise ValueError(f"standard partition root missing: {source_root}")
    columns = [
        "symbol", "trade_date", "is_halted", "is_suspended", "is_limit_up",
        "is_limit_down", "is_one_price_limit", "is_tradeable", "published_at",
        "available_at", "revision", "provider", "raw_hash",
    ]
    table = ds.dataset(source_root, format="parquet", partitioning="hive").to_table(columns=columns)
    rows_by_key: dict[tuple[str, str], dict] = {}
    for row in table.to_pylist():
        symbol = str(row.get("symbol") or "").strip()
        trade_date = str(row.get("trade_date") or "")[:10]
        if not symbol or not trade_date:
            continue
        key = (symbol, trade_date)
        rows_by_key[key] = {
            "symbol": symbol,
            "trade_date": trade_date,
            "is_halted": bool(row.get("is_halted")),
            "is_suspended": bool(row.get("is_suspended")),
            "is_limit_up": bool(row.get("is_limit_up")),
            "is_limit_down": bool(row.get("is_limit_down")),
            "is_one_price_limit": bool(row.get("is_one_price_limit")),
            "is_tradeable": bool(row.get("is_tradeable")),
            "published_at": row.get("published_at"),
            "available_at": row.get("available_at"),
            "revision": int(row.get("revision") or 1),
            "provider": row.get("provider") or "derived_standard_daily_bars",
            "raw_hash": row.get("raw_hash"),
            "quality_status": "degraded",
            "missing_reason": "historical publication time is not independently proven for public backfill",
            "missing_reason_code": "published_time_unverified",
        }
    return [rows_by_key[key] for key in sorted(rows_by_key)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=PROJECT / "var/cn-research/parquet/pit/cn/standard_daily_bars_research/free-research-standard-v1")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_trading_status")
    args = parser.parse_args()
    rows = build_status_rows(args.source_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    output = args.output_root / "trading_status.parquet"
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows)
    temporary = output.with_suffix(".tmp.parquet")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True)
    os.replace(temporary, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    report = {
        "schema_version": "cn-trading-status-derived-v1",
        "dataset": "cn_trading_status",
        "provider": "derived_standard_daily_bars",
        "status": "degraded" if rows else "unavailable",
        "quality_status": "degraded" if rows else "unavailable",
        "row_count": len(rows),
        "symbol_count": len({row["symbol"] for row in rows}),
        "date_start": min((row["trade_date"] for row in rows), default=None),
        "date_end": max((row["trade_date"] for row in rows), default=None),
        "published_at_coverage": 0.0,
        "available_at_coverage": sum(bool(row.get("available_at")) for row in rows) / len(rows) if rows else 0.0,
        "revision_coverage": sum(bool(row.get("revision")) for row in rows) / len(rows) if rows else 0.0,
        "missing_reason": "historical publication time is not independently proven for public backfill",
        "missing_reason_code": "published_time_unverified",
        "output_path": str(output),
        "sha256": digest,
        "sha256_verified": True,
        "data_tier": "research_pit",
        "deployment_ready": False,
    }
    report_path = args.output_root / "latest.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
