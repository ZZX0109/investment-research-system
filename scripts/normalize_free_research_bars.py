#!/usr/bin/env python3
"""Write a public daily-bar payload to the research-only Parquet standard layer."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore
from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.training.free_research_adapter import normalize_free_daily_payload
from investment_research.training.parquet_store import PITParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize free daily bars to research-only Parquet")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--market", choices=("cn", "us", "hk", "jp"), required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--received-at", help="ISO timestamp; defaults to the raw file mtime in UTC")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "data" / "free_research_standard")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts" / "free_research_standard_manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    received_at = (
        datetime.fromisoformat(args.received_at.replace("Z", "+00:00"))
        if args.received_at
        else datetime.fromtimestamp(args.input.stat().st_mtime, tz=timezone.utc)
    )
    result = normalize_free_daily_payload(
        args.input.read_bytes(), market=args.market, symbol=args.symbol,
        provider=args.provider, received_at=received_at,
    )
    if not result.bars:
        raise SystemExit("no valid research bars were normalized")
    year = result.bars[-1].trade_date.year
    store = PITParquetStore(LocalObjectStore(args.object_store))
    ref, payload_hash, schema_hash, row_count = store.write_partition(
        result.bars, market=args.market, dataset="standard_daily_bars_research",
        schema_version="free-research-standard-v1", trade_year=year,
        partition_id=uuid4().hex,
    )
    payload = {
        "schema_version": "free-research-standard-manifest-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "mode": "research_only",
        "formal_pit_eligible": result.formal_pit_eligible,
        "blocking_reasons": result.blocking_reasons,
        "market": args.market,
        "symbol": args.symbol,
        "provider": args.provider,
        "input_ref": str(args.input),
        "received_at": received_at.isoformat(),
        "parquet_ref": ref,
        "payload_hash": payload_hash,
        "schema_hash": schema_hash,
        "row_count": row_count,
        "skipped_rows": result.skipped_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
