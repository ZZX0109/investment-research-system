#!/usr/bin/env python3
"""Backfill a positive historical qfq series from AKShare's SINA endpoint.

Some Eastmoney qfq responses contain negative pre-adjustment prices.  This
repair uses the independent ``stock_zh_a_daily`` endpoint, validates every
OHLC row before persistence, and writes a new immutable research-PIT batch.
The malformed source batch is not overwritten; it is handled separately by
the quarantine audit.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]


def repair(symbol: str, start: str, end: str, database: Path, object_store: Path) -> dict:
    import akshare as ak
    from investment_research.domain.data_tier import DataTier
    from investment_research.repository.sqlite import SQLiteUnitOfWork
    from investment_research.service.object_store import LocalObjectStore
    from investment_research.service.trusted_ingestion import RawPayloadIngestionService

    prefix = "sz" if symbol.startswith(("0", "3")) else "sh"
    frame = ak.stock_zh_a_daily(symbol=f"{prefix}{symbol}", start_date=start, end_date=end, adjust="qfq")
    if frame is None or len(frame) == 0:
        raise RuntimeError(f"SINA returned no qfq rows for {symbol}")
    required = {"date", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"SINA qfq payload missing columns: {sorted(missing)}")
    numeric = frame[["open", "high", "low", "close"]].astype(float)
    invalid = numeric.isna().any(axis=1) | (numeric <= 0).any(axis=1)
    invalid |= numeric["high"] < numeric[["open", "close"]].max(axis=1)
    invalid |= numeric["low"] > numeric[["open", "close"]].min(axis=1)
    if bool(invalid.any()):
        raise RuntimeError(f"SINA qfq OHLC validation failed: {int(invalid.sum())} rows")
    rows = json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    dates = [date.fromisoformat(str(value)[:10]) for value in frame["date"].tolist()]
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(database)
    try:
        service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(object_store))
        batch = service.persist(
            provider="akshare_sina",
            request_id=f"qfq-repair-{symbol}-{start}-{end}-{uuid4()}",
            dataset="daily_bars_qfq",
            payload=payload,
            schema_version="free-research-v1",
            symbol=symbol,
            interval="1d",
            available_at=now,
            received_at=now,
            market_session="research_backfill_repair",
            data_tier=DataTier.RESEARCH_PIT,
            coverage_start=datetime.combine(min(dates), datetime.min.time(), timezone.utc),
            coverage_end=datetime.combine(max(dates), datetime.max.time(), timezone.utc),
        )
    finally:
        uow.close()
    report = {
        "schema_version": "qfq-repair-v1",
        "status": "complete",
        "symbol": symbol,
        "provider": "akshare_sina",
        "dataset": "daily_bars_qfq",
        "row_count": len(rows),
        "coverage_start": min(dates).isoformat(),
        "coverage_end": max(dates).isoformat(),
        "payload_hash": batch.payload_hash,
        "payload_ref": batch.payload_ref,
        "data_tier": DataTier.RESEARCH_PIT.value,
        "raw_source_unchanged": True,
    }
    print(json.dumps(report, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="000001")
    parser.add_argument("--start", default="19910403")
    parser.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    args = parser.parse_args()
    repair(args.symbol, args.start, args.end, args.database, args.object_store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
