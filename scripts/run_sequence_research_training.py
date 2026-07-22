#!/usr/bin/env python3
"""Train true sequence challengers from one frozen research sample scope.

This command never reads pickle caches and always emits research-only
artifacts.  It is intentionally separate from the tabular runner so a failed
deep experiment cannot alter the approved/fallback tabular roster.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.training.models import TrainingSample
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.sequence_dataset import build_sequence_examples
from investment_research.training.sequence_experiment import run_sequence_experiment
from investment_research.service.object_store import LocalObjectStore


ARCHITECTURES = ("patchtst", "tcn", "itransformer", "deep_mlp")
TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train research-only CN sequence challengers")
    parser.add_argument("--sample-manifest", type=Path, nargs="+", required=True)
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/free_research_models")
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    parser.add_argument("--window", type=int, choices=(20, 60, 120), default=60)
    parser.add_argument("--cohort", choices=("cn_equity_core", "cn_etf_benchmark"), required=True)
    parser.add_argument("--training-run-id", default=None)
    parser.add_argument("--screen-symbols", type=int, default=20)
    # 1,260 sessions leave enough history after a 120-session input window,
    # task-label tail, 252-session holdout and 504/126 purged fold.  The former
    # 960 default could produce no valid fold even with otherwise complete CN
    # history.
    parser.add_argument("--maximum-dates", type=int, default=1260)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.output_root if args.output_root.is_absolute() else PROJECT / args.output_root
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in args.sample_manifest]
    if not manifests or any(item.get("data_tier") != DataTier.RESEARCH_PIT.value for item in manifests):
        raise SystemExit("sequence training requires research_pit sample manifests")
    if any("bundle_" in str(path) or "all_samples" in str(path) for path in args.sample_manifest):
        raise SystemExit("legacy pickle sample paths are forbidden")
    store = PITParquetStore(LocalObjectStore(args.object_store))
    rows: list[TrainingSample] = []
    snapshots = set()
    for manifest in manifests:
        snapshot = (manifest.get("market_snapshot_id"), manifest.get("market_snapshot_hash"))
        snapshots.add(snapshot)
        for row in store.read_partition(manifest["sample_parquet_ref"]):
            value = dict(row)
            for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
                if isinstance(value.get(key), str):
                    value[key] = json.loads(value[key])
            sample = TrainingSample.model_validate(value)
            if (sample.market_snapshot_id, sample.market_snapshot_hash) != snapshot:
                raise SystemExit("sequence sample snapshot mismatch")
            rows.append(sample)
    if len(snapshots) != 1:
        raise SystemExit("sequence training cannot mix market snapshots")
    symbols = sorted({item.symbol for item in rows})
    if args.screen_symbols > 0 and len(symbols) > args.screen_symbols:
        retained_symbols = set(symbols[: args.screen_symbols])
        rows = [item for item in rows if item.symbol in retained_symbols]
    dates = sorted({item.as_of_date for item in rows})
    if len(dates) > args.maximum_dates:
        retained_dates = set(dates[-args.maximum_dates:])
        rows = [item for item in rows if item.as_of_date in retained_dates]
    examples = build_sequence_examples(rows, target_name=_target(args.task), window_sessions=args.window)
    if not examples:
        raise SystemExit("sequence scope has no valid windows")
    result = run_sequence_experiment(
        examples, task=args.task, architecture=args.architecture, window_sessions=args.window,
        config_overrides={"hidden_size": 32, "max_epochs": 8, "patience": 3},
    )
    run_id = args.training_run_id or f"sequence-{args.task}-{args.architecture}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    scope = output_root / "cn" / "close_confirmed" / args.cohort / args.task / "sequence" / args.architecture
    scope.mkdir(parents=True, exist_ok=True)
    report = scope / "sequence_evaluation.json"
    model_path = scope / "model.pt"
    model_hash = result.final_runner.save(model_path) if result.final_runner is not None else None
    result_payload = {key: value for key, value in asdict(result).items() if key != "final_runner"}
    dataset_hash = sha256(json.dumps(manifests, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot_id, snapshot_hash = next(iter(snapshots))
    feature_order_hash = sha256(json.dumps(examples[0].feature_order, separators=(",", ":")).encode()).hexdigest()
    normalizer_hash = sha256(json.dumps(result.final_runner.stats if result.final_runner else {}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {"schema_version": "cn-sequence-evaluation-v1", "data_tier": "research_pit", "status": "research_only", "deployment_ready": False, "training_run_id": run_id, "task": args.task, "architecture": args.architecture, "experiment_stage": "fixed_pool_screening", "training_symbol_count": len({item.symbol for item in rows}), "training_date_count": len({item.as_of_date for item in rows}), "window_sessions": args.window, "input_shape": [args.window, len(examples[0].feature_order) * 2 + 9], "feature_contract_version": "investment-risk-features-v3-sequence", "dataset_hash": dataset_hash, "market_snapshot_id": snapshot_id, "market_snapshot_hash": snapshot_hash, "feature_order_hash": feature_order_hash, "normalizer_hash": normalizer_hash, "quality_mask_schema": ["quality_passed", "coverage", "no_data_issues"], "event_mask_schema": ["event_missing", "event_source_available"], "historical_visibility_assumption": "historical_available_at_unproven_public_backfill", "result": result_payload, "model_hash": model_hash}
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    artifact_hash = sha256(report.read_bytes()).hexdigest()
    summary = {"task": args.task, "architecture": args.architecture, "experiment_stage": "fixed_pool_screening", "training_symbol_count": len({item.symbol for item in rows}), "training_date_count": len({item.as_of_date for item in rows}), "window_sessions": args.window, "input_shape": [args.window, len(examples[0].feature_order) * 2 + 9], "feature_contract_version": "cn-research-feature-v3-sequence", "label_version": "cn-direction-volatility-label-v2", "dataset_hash": dataset_hash, "market_snapshot_id": snapshot_id, "market_snapshot_hash": snapshot_hash, "feature_order_hash": feature_order_hash, "normalizer_hash": normalizer_hash, "artifact_ref": str(model_path.relative_to(PROJECT)), "report_ref": str(report.relative_to(PROJECT)), "artifact_hash": model_hash, "report_hash": artifact_hash, "fold_hash": result.fold_hash, "quality_mask_schema": ["quality_passed", "coverage", "no_data_issues"], "event_mask_schema": ["event_missing", "event_source_available"], "status": "research_only", "research_status": "exploratory", "research_ready": False, "eligible_for_ensemble": False, "ensemble_exclusion_reason": "deep_regime_promotion_gate_not_met", "deployment_ready": False}
    (scope / "sequence_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report)
    return 0


def _target(task: str) -> str:
    return {"direction_1d": "direction_1d", "direction_5d": "direction_5d", "return_20d": "future_return_20d", "drawdown_20d": "future_max_drawdown_20d"}[task]


if __name__ == "__main__":
    raise SystemExit(main())
