#!/usr/bin/env python3
"""Repair missing BSE qfq series through official 920-to-legacy identity maps.

Existing BSE listings migrated from legacy codes to the 920 range in 2025.
Some public K-line endpoints expose the adjusted history more reliably under
the legacy identity.  This job keeps the target 920 symbol in the catalog,
records the legacy source code inside the captured payload, and is fully
resumable: only raw-present/qfq-missing symbols are requested.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from investment_research.training.cn_free_providers import EastmoneyDailyResearchProvider


def _missing_qfq(database: Path) -> list[str]:
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            """
            SELECT DISTINCT json_extract(payload_json, '$.symbol')
            FROM raw_data_batches
            WHERE data_tier=? AND dataset='daily_bars_raw'
            EXCEPT
            SELECT DISTINCT json_extract(payload_json, '$.symbol')
            FROM raw_data_batches
            WHERE data_tier=? AND dataset='daily_bars_qfq'
            """,
            (DataTier.RESEARCH_PIT.value, DataTier.RESEARCH_PIT.value),
        )
        return sorted(str(row[0]) for row in rows if row[0])
    finally:
        connection.close()


def _latest_date(payload: bytes, fallback: date) -> date:
    try:
        rows = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    values: list[date] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            values.append(date.fromisoformat(str(row.get("日期") or "")[:10]))
        except (AttributeError, TypeError, ValueError):
            continue
    return max(values, default=fallback)


def _remap_payload(payload: bytes, *, target_symbol: str, source_symbol: str) -> bytes:
    rows = json.loads(payload)
    if not isinstance(rows, list):
        raise ValueError("eastmoney qfq payload is not a row list")
    for row in rows:
        if isinstance(row, dict):
            row["代码"] = target_symbol
            row["源证券代码"] = source_symbol
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--mapping", type=Path, default=PROJECT / "artifacts/cn_bse_code_mapping/mapping.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/free_research_coverage_bse_legacy_qfq.json")
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.timeout_seconds <= 0 or args.delay_seconds < 0 or (args.limit is not None and args.limit <= 0):
        raise SystemExit("timeout/limit must be positive and delay cannot be negative")
    mapping_rows = json.loads(args.mapping.read_text(encoding="utf-8"))
    mapping = {
        str(row["new_code"]).zfill(6): str(row["old_code"]).zfill(6)
        for row in mapping_rows if isinstance(row, dict) and row.get("new_code") and row.get("old_code")
    }
    missing = _missing_qfq(args.database)
    targets = [(symbol, mapping.get(symbol, symbol)) for symbol in missing if symbol.startswith("9")]
    if args.limit is not None:
        targets = targets[:args.limit]
    now = datetime.now(timezone.utc)
    output: list[dict[str, Any]] = []
    provider = EastmoneyDailyResearchProvider(timeout_seconds=args.timeout_seconds)
    uow = SQLiteUnitOfWork(args.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
    try:
        for index, (target_symbol, source_symbol) in enumerate(targets, 1):
            try:
                result = provider.fetch(
                    source_symbol, start=date(1990, 1, 1), end=args.end, adjustment_mode="qfq",
                )
                payload = _remap_payload(result.payload, target_symbol=target_symbol, source_symbol=source_symbol)
                observed_end = _latest_date(payload, args.end)
                batch = service.persist(
                    provider="eastmoney_bse_legacy_qfq",
                    request_id=f"bse-legacy-qfq-{target_symbol}-{source_symbol}-{uuid4()}",
                    dataset="daily_bars_qfq", payload=payload,
                    schema_version="free-research-bse-legacy-qfq-v1", symbol=target_symbol,
                    interval="1d", available_at=now, received_at=now,
                    market_session="research_bse_legacy_qfq", data_tier=DataTier.RESEARCH_PIT,
                    coverage_start=None,
                    coverage_end=datetime.combine(observed_end, datetime.max.time(), timezone.utc),
                )
                entry = {
                    "symbol": target_symbol, "source_symbol": source_symbol, "status": "backfilled",
                    "rows": result.row_count, "payload_hash": batch.payload_hash,
                }
            except Exception as exc:
                entry = {
                    "symbol": target_symbol, "source_symbol": source_symbol, "status": "fetch_failed",
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            output.append(entry)
            print(json.dumps({"completed": index, "target_count": len(targets), **entry}, ensure_ascii=False), flush=True)
            if args.delay_seconds and index < len(targets):
                time.sleep(args.delay_seconds)
    finally:
        uow.close()
    remaining = _missing_qfq(args.database)
    report = {
        "schema_version": "free-research-bse-legacy-qfq-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": output,
        "target_count": len(targets),
        "success_count": sum(item["status"] == "backfilled" for item in output),
        "remaining_qfq_symbol_count": len(remaining),
        "remaining_qfq_symbols": remaining,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
