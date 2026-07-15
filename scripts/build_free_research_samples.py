#!/usr/bin/env python3
"""Build V2 research samples from free standard-layer Parquet.

This command is intentionally explicit about its non-PIT assumption: it uses a
bar's trade-date publication time as *research assumed availability* solely to
run feature and label experiments.  The generated samples are permanently
marked research-only and cannot be registered in the formal PIT catalog.
"""
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
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.models import CanonicalInstrument, CoverageGroup, InstrumentType, Market, PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build research-only V2 samples from free standard Parquet")
    parser.add_argument("--standard-manifest", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--object-store", type=Path, default=PROJECT / "data" / "free_research_standard")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-manifest", type=Path, required=True)
    parser.add_argument("--decision-context", choices=("close_confirmed", "pre_open"), default="close_confirmed")
    parser.add_argument("--cohort", choices=("cn_equity_core", "cn_etf_benchmark"), default="cn_equity_core")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    standard = json.loads(args.standard_manifest.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot_manifest.read_text(encoding="utf-8"))
    if standard.get("formal_pit_eligible"):
        raise SystemExit("free research builder only accepts explicitly non-formal manifests")
    market = Market(standard["market"])
    if snapshot.get("data_tier") != DataTier.RESEARCH_PIT.value or snapshot.get("market") != market.value:
        raise SystemExit("sample and snapshot manifests must share the CN research_pit scope")
    snapshot_hash = snapshot.get("market_snapshot_hash")
    if not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64:
        raise SystemExit("snapshot manifest lacks a valid market_snapshot_hash")
    store = PITParquetStore(LocalObjectStore(args.object_store))
    bars = [PreparedPriceBar.model_validate(row) for row in store.read_partition(standard["parquet_ref"])]
    # This is deliberately a research-only counterfactual.  The original
    # standard Parquet retains its true collection-time available_at.
    assumed = [bar.model_copy(update={"available_at": bar.published_at, "as_of": bar.published_at}) for bar in bars]
    instrument = CanonicalInstrument(
        symbol=standard["symbol"], name=args.name, market=market,
        instrument_type=InstrumentType.ETF if args.cohort == "cn_etf_benchmark" else InstrumentType.EQUITY,
        coverage_group=CoverageGroup.ETF if args.cohort == "cn_etf_benchmark" else _coverage(market),
        currency=bars[0].currency, exchange=bars[0].calendar_code,
    )
    samples = TrainingDatasetBuilder(
        feature_version="investment-risk-features-v2",
        data_version=f"free-research-assumed-availability:{standard['payload_hash'][:16]}",
    ).build_samples(
        instrument=instrument, price_bars=assumed, events=[],
        decision_context=args.decision_context, event_coverage_status="unsupported",
    )
    if not samples:
        raise SystemExit("no research samples could be built")
    samples = [item.model_copy(update={
        "market_snapshot_id": snapshot["market_snapshot_id"],
        "market_snapshot_hash": snapshot_hash,
    }) for item in samples]
    ref, payload_hash, schema_hash, row_count = store.write_partition(
        samples, market=market.value, dataset="research_samples",
        schema_version="free-research-samples-v1", trade_year=samples[-1].as_of_date.year,
        partition_id=uuid4().hex,
    )
    payload = {
        "schema_version": "free-research-sample-manifest-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "mode": "research_only", "formal_pit_eligible": False,
        "blocking_reasons": [
            RESEARCH_VISIBILITY_ASSUMPTION,
            "research_assumed_trade_date_availability",
        ],
        "standard_manifest_ref": str(args.standard_manifest),
        "market": market.value, "symbol": standard["symbol"],
        "cohort": args.cohort,
        "decision_context": args.decision_context, "feature_version": "investment-risk-features-v2",
        "market_snapshot_id": snapshot["market_snapshot_id"],
        "market_snapshot_hash": snapshot_hash,
        "sample_parquet_ref": ref, "payload_hash": payload_hash, "schema_hash": schema_hash,
        "row_count": row_count, "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


def _coverage(market: Market) -> CoverageGroup:
    return {
        Market.CN: CoverageGroup.CN_A_SHARE, Market.US: CoverageGroup.US_CORE,
        Market.HK: CoverageGroup.HK_PROXY, Market.JP: CoverageGroup.JP_PROXY,
    }[market]


if __name__ == "__main__":
    raise SystemExit(main())
