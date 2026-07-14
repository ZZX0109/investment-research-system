from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from investment_research.training.artifacts import TrainingArtifactStore
from investment_research.training.experiments import TrainingExperimentRunner
from investment_research.training.real_data import (
    AksharePriceFetcher,
    LocalJsonCache,
    OptionalDependencyError,
    RealDataSourceHub,
    YFinancePriceFetcher,
)
from investment_research.training.data_quality import prepare_price_bars
from investment_research.training.models import DataQualityRuleSet
from investment_research.training.sources import build_instrument_from_symbol
from investment_research.training.trainers import default_trainer_specs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run walk-forward training experiments for a covered symbol.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--target", default="future_max_drawdown_20d")
    parser.add_argument("--feature-version", default="features-v1")
    parser.add_argument("--data-version", default="real-cache-v1")
    parser.add_argument("--cache-dir", default="var/training-cache")
    parser.add_argument("--train-window-days", type=int, default=120)
    parser.add_argument("--validation-window-days", type=int, default=20)
    parser.add_argument("--step-days", type=int, default=20)
    parser.add_argument("--output", default="var/training-experiment.json")
    args = parser.parse_args()

    hub = RealDataSourceHub(
        us_price_fetcher=YFinancePriceFetcher(),
        cn_price_fetcher=AksharePriceFetcher(),
        cache=LocalJsonCache(Path(args.cache_dir)),
    )
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    instrument = build_instrument_from_symbol(args.symbol)
    benchmark_bundle = None
    if instrument.benchmark_symbol:
        benchmark_bundle = hub.build_bundle(instrument.benchmark_symbol, start=start, end=end)
    regime_reference = None
    if benchmark_bundle is not None:
        regime_reference, benchmark_issues = prepare_price_bars(benchmark_bundle.price_bars, rules=DataQualityRuleSet())
        if benchmark_issues:
            print(
                json.dumps(
                    {
                        "benchmark_symbol": instrument.benchmark_symbol,
                        "benchmark_issue_count": len(benchmark_issues),
                        "benchmark_issue_codes": [issue.code for issue in benchmark_issues],
                    },
                    ensure_ascii=True,
                )
            )
    samples = hub.build_training_samples(
        args.symbol,
        start=start,
        end=end,
        feature_version=args.feature_version,
        data_version=args.data_version,
        benchmark_bundle=benchmark_bundle,
    )
    report = TrainingExperimentRunner(
        target_name=args.target,
        trainer_specs=default_trainer_specs(),
    ).run(
        samples=samples,
        train_window_days=args.train_window_days,
        validation_window_days=args.validation_window_days,
        step_days=args.step_days,
        regime_reference=regime_reference,
    )

    output_path = Path(args.output)
    store = TrainingArtifactStore(output_path.parent)
    report_path = store.write_experiment_report(report, name=output_path.stem)
    for result in report.results:
        store.write_model_card(result.model_card, name=result.model_card.model_id)
    print(json.dumps({"target": args.target, "result_count": len(report.results), "baseline_model_id": report.baseline_model_id}))
    print(json.dumps({"report_path": str(report_path)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OptionalDependencyError as exc:
        print(str(exc))
        raise SystemExit(2)
