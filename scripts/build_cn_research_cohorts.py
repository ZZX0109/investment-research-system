#!/usr/bin/env python3
"""Freeze reproducible CN equity and ETF research cohorts from standard Parquet."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore
from investment_research.training.cn_research_universe import (
    build_cn_equity_core,
    build_cn_etf_benchmark,
)
from investment_research.training.models import PreparedPriceBar
from investment_research.training.parquet_store import PITParquetStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build zero-budget A-share research cohorts")
    parser.add_argument("--standard-manifests", nargs="+", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, default=PROJECT / "data" / "free_research_standard")
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output-directory", type=Path, default=PROJECT / "artifacts" / "cn_research_cohorts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = PITParquetStore(LocalObjectStore(args.object_store))
    bars: list[PreparedPriceBar] = []
    for path in args.standard_manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("market") != "cn" or manifest.get("data_tier") != "research_pit":
            raise SystemExit(f"non-CN or non-research standard manifest: {path}")
        bars.extend(PreparedPriceBar.model_validate(row) for row in store.read_partition(manifest["parquet_ref"]))
    manifests = (
        build_cn_equity_core(bars, as_of=args.as_of),
        build_cn_etf_benchmark(bars, as_of=args.as_of),
    )
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        output = args.output_directory / f"{manifest.cohort}-{args.as_of.isoformat()}.json"
        output.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
