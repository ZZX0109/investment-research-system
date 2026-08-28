#!/usr/bin/env python3
"""Train the causal Fortune-inspired 1/5/20-day CatBoost candidate.

The expensive market context is content-addressed cached under
``artifacts/feature_cache``.  Re-running with the same local bar snapshot
reuses GARCH/HMM/network features; each run still produces a fresh, explicit
walk-forward report and never replaces the lightweight deployed model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.training.short_term.fortune_enhanced_horizon_runner import FortuneEnhancedHorizonRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--feature-workers", type=int, default=None, help="parallel workers for per-stock GARCH/technical features")
    parser.add_argument("--folds", type=int, default=12)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--purge-sessions", type=int, default=20)
    parser.add_argument("--no-lstm-garch", action="store_true")
    parser.add_argument("--no-resume", action="store_true", help="ignore compatible completed fold checkpoints")
    parser.add_argument("--compare-price-baseline", action="store_true", help="run the exact same folds with the nine price-only features")
    parser.add_argument("--core-ablation", action="store_true", help="also run the Fortune Top-feature core ablation")
    parser.add_argument("--core-only", action="store_true", help="skip the already completed enhanced candidate and run only the core ablation")
    parser.add_argument("--calibrate-threshold", action="store_true", help="calibrate cutoff from each training fold prevalence")
    parser.add_argument("--horizons", nargs="+", choices=("1d", "5d", "20d"), default=("1d", "5d", "20d"))
    parser.add_argument("--candidate-suffix", default="", help="suffix for independent candidate artifact directories")
    args = parser.parse_args()
    uow = SQLiteUnitOfWork(get_default_database_path())
    try:
        if args.symbols:
            symbols = sorted({str(item).zfill(6) for item in args.symbols})
        else:
            symbols = [row[0] for row in uow.connection.execute("SELECT DISTINCT symbol FROM versioned_market_bars WHERE interval='1d' ORDER BY symbol")]
        if args.max_symbols is not None:
            symbols = symbols[:max(1, args.max_symbols)]
        root = Path(__file__).resolve().parent.parent
        runner = FortuneEnhancedHorizonRunner(root, candidate_name=f"fortune_enhanced{args.candidate_suffix}")
        rows = runner.build_dataset(uow.trusted_market, symbols, feature_workers=args.feature_workers)
        report = {"status": "skipped"}
        if not args.core_only:
            report = runner.train_walk_forward(
                rows, n_folds=args.folds, iterations=args.iterations,
                purge_sessions=args.purge_sessions, use_lstm_garch=not args.no_lstm_garch,
                resume=not args.no_resume, threshold_mode="train_quantile" if args.calibrate_threshold else "fixed",
                horizons=tuple(args.horizons),
            )
        baseline = None
        if args.compare_price_baseline and not args.core_only:
            baseline_runner = FortuneEnhancedHorizonRunner(
                Path(__file__).resolve().parent.parent,
                candidate_name=f"fortune_price_baseline{args.candidate_suffix}",
                feature_scope="price_baseline",
            )
            baseline = baseline_runner.train_walk_forward(
                rows, n_folds=args.folds, iterations=args.iterations,
                purge_sessions=args.purge_sessions, use_lstm_garch=False,
                resume=not args.no_resume, threshold_mode="train_quantile" if args.calibrate_threshold else "fixed",
                horizons=tuple(args.horizons),
            )
        core = None
        if args.core_ablation:
            core_runner = FortuneEnhancedHorizonRunner(
                Path(__file__).resolve().parent.parent,
                candidate_name=f"fortune_core_ablation{args.candidate_suffix}",
                feature_scope="fortune_core",
            )
            core = core_runner.train_walk_forward(
                rows, n_folds=args.folds, iterations=args.iterations,
                purge_sessions=args.purge_sessions, use_lstm_garch=not args.no_lstm_garch,
                resume=not args.no_resume, threshold_mode="train_quantile" if args.calibrate_threshold else "fixed",
                horizons=tuple(args.horizons),
            )
        print(json.dumps({
            "status": report.get("status"), "rows": report.get("n_rows"),
            "features": report.get("feature_count"), "folds": report.get("n_folds"),
            "aggregate": {name: value.get("aggregate") for name, value in report.get("horizons", {}).items()},
            "price_baseline_aggregate": {name: value.get("aggregate") for name, value in (baseline or {}).get("horizons", {}).items()},
            "fortune_core_aggregate": {name: value.get("aggregate") for name, value in (core or {}).get("horizons", {}).items()},
        }, ensure_ascii=False, indent=2, allow_nan=True))
        return 0 if report.get("status") == "ok" else 2
    finally:
        uow.close()


if __name__ == "__main__":
    raise SystemExit(main())
