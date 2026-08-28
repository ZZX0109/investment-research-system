#!/usr/bin/env python3
"""Ingest official TongdaXin ``.day`` raw bars for current BJ symbols.

The downloaded ``hsjday.zip`` is a research-tier raw source.  It contains
OHLCV but no corporate-action factor file, so this script deliberately writes
only ``daily_bars_raw`` and never fabricates a qfq series.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from zipfile import ZipFile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.free_research_ledger import build_coverage_ledgers
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

RECORD_SIZE = 32


def _symbols(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload if isinstance(payload, list) else payload.get("cn", [])
    return sorted({str(item.get("code") if isinstance(item, dict) else item).rsplit(".", 1)[-1].zfill(6) for item in values})


def _parse_day_payload(blob: bytes, symbol: str) -> bytes:
    rows: list[dict] = []
    usable = len(blob) - (len(blob) % RECORD_SIZE)
    for offset in range(0, usable, RECORD_SIZE):
        raw_date, open_i, high_i, low_i, close_i, amount, volume, _reserved = struct.unpack(
            "<IIIIIfII", blob[offset:offset + RECORD_SIZE]
        )
        year, month = raw_date // 10000, (raw_date // 100) % 100
        day = raw_date % 100
        try:
            observed = date(year, month, day)
        except ValueError:
            continue
        prices = [value / 100.0 for value in (open_i, high_i, low_i, close_i)]
        if min(prices) <= 0 or prices[1] < max(prices[0], prices[3]) or prices[2] > min(prices[0], prices[3]):
            continue
        rows.append({
            "日期": observed.isoformat(), "代码": symbol,
            "开盘": prices[0], "最高": prices[1], "最低": prices[2], "收盘": prices[3],
            "成交量": float(volume), "成交额": float(amount),
        })
    if not rows:
        raise ValueError("tdx day file contains no valid rows")
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--symbols-file", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    targets = [symbol for symbol in _symbols(args.symbols_file) if symbol.startswith(("4", "8", "9"))]
    now = datetime.now(timezone.utc)
    records: list[dict] = []
    uow = SQLiteUnitOfWork(args.database)
    store = LocalObjectStore(args.object_store)
    service = RawPayloadIngestionService(uow, object_store=store)
    try:
        with ZipFile(args.zip) as archive:
            names = {name.replace("/", "\\"): name for name in archive.namelist()}
            for symbol in targets:
                name = names.get(f"bj\\lday\\bj{symbol}.day")
                if not name:
                    records.append({"market": "cn", "dataset": "daily_bars_raw", "provider": "tdx", "symbol": symbol, "status": "fetch_failed", "reason": "tdx_bj_day_file_missing"})
                    continue
                try:
                    payload = _parse_day_payload(archive.read(name), symbol)
                    rows = json.loads(payload)
                    observed_end = max(date.fromisoformat(row["日期"]) for row in rows)
                    digest = hashlib.sha256(payload).hexdigest()
                    batch = service.persist(
                        provider="tdx", request_id=f"tdx-bj-{symbol}-{digest}",
                        dataset="daily_bars_raw", payload=payload, schema_version="tdx-day-v1",
                        symbol=symbol, interval="1d", available_at=now, received_at=now,
                        market_session="research_tdx_backfill", data_tier=DataTier.RESEARCH_PIT,
                        coverage_start=None,
                        coverage_end=datetime.combine(observed_end, datetime.max.time(), timezone.utc),
                    )
                    records.append({"market": "cn", "dataset": "daily_bars_raw", "provider": "tdx", "provider_chain": ["tdx"], "symbol": symbol, "status": "backfilled", "rows_or_bytes": len(rows), "payload_hash": batch.payload_hash, "data_tier": DataTier.RESEARCH_PIT.value, "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION})
                except Exception as exc:
                    records.append({"market": "cn", "dataset": "daily_bars_raw", "provider": "tdx", "symbol": symbol, "status": "fetch_failed", "reason": f"tdx={type(exc).__name__}:{exc}"})
    finally:
        uow.close()
    ledgers = build_coverage_ledgers(records=records, targets={"cn": set(_symbols(args.symbols_file)), "us": set(), "hk": set(), "jp": set()}, generated_at=now)
    payload = {"schema_version": "free-research-coverage-v1", "data_tier": DataTier.RESEARCH_PIT.value, "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION, "generated_at": now.isoformat(), "mode": "research_only", "formal_deployment_allowed": False, "synthetic_count": 0, "records": records, "market_coverage": [item.model_dump(mode="json") for item in ledgers], "source": "https://data.tdx.com.cn/vipdoc/hsjday.zip", "qfq_available": False, "qfq_missing_reason": "tdx_day_bundle_has_no_adjustment_factor_file"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cn = next(item for item in payload["market_coverage"] if item["market"] == "cn")
    print(json.dumps({"status": "research_only", "target_bj_count": len(targets), "successful_raw_count": cn["successful_target_count"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
