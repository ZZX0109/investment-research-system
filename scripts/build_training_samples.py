from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from investment_research.training.real_data import (
    AksharePriceFetcher,
    LocalJsonCache,
    OptionalDependencyError,
    RealDataSourceHub,
    YFinancePriceFetcher,
)
from investment_research.training.sources import build_instrument_from_symbol


def main() -> int:
    parser = argparse.ArgumentParser(description="Build cached real training samples for a covered symbol.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--feature-version", default="features-v1")
    parser.add_argument("--data-version", default="real-cache-v1")
    parser.add_argument("--cache-dir", default="var/training-cache")
    parser.add_argument("--output", default=None, help="Optional JSON output path for serialized samples.")
    args = parser.parse_args()

    instrument = build_instrument_from_symbol(args.symbol)
    hub = RealDataSourceHub(
        us_price_fetcher=YFinancePriceFetcher(),
        cn_price_fetcher=AksharePriceFetcher(),
        cache=LocalJsonCache(Path(args.cache_dir)),
    )
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    benchmark_bundle = None
    if instrument.benchmark_symbol:
        benchmark_bundle = hub.build_bundle(instrument.benchmark_symbol, start=start, end=end)
    samples = hub.build_training_samples(
        args.symbol,
        start=start,
        end=end,
        feature_version=args.feature_version,
        data_version=args.data_version,
        benchmark_bundle=benchmark_bundle,
    )

    print(json.dumps({"symbol": args.symbol, "sample_count": len(samples)}, ensure_ascii=True))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps([sample.model_dump(mode="json") for sample in samples], ensure_ascii=True, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OptionalDependencyError as exc:
        print(str(exc))
        raise SystemExit(2)
