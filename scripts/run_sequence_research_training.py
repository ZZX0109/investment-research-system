#!/usr/bin/env python3
"""Train true sequence challengers from one frozen research sample scope.

This command never reads pickle caches and always emits research-only
artifacts.  It is intentionally separate from the tabular runner so a failed
deep experiment cannot alter the approved/fallback tabular roster.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import pickle
import sys

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.training.models import TrainingSample
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.active_snapshot_guard import (
    ActiveSnapshotInputError,
    assert_manifest_binding,
    require_active_snapshot,
    require_training_snapshot_gate,
)
from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.snapshot_landing import SnapshotGateConfig
from investment_research.training.sequence_dataset import build_sequence_examples
from investment_research.training.sequence_experiment import run_sequence_experiment, split_sequence_examples
from investment_research.service.object_store import LocalObjectStore


ARCHITECTURES = ("patchtst", "tcn", "itransformer", "deep_mlp")
TASKS = (
    "direction_1d", "direction_5d", "return_20d", "drawdown_20d",
    "excess_return_5d", "excess_return_20d",
    "excess_return_120d", "excess_return_240d",
    "future_max_drawdown_120d", "future_max_drawdown_240d",
)


def _feature_profile_names(names: list[str], profile: str) -> list[str]:
    """Return a deterministic feature contract for fast incremental screens.

    Profiles are deliberately prefix-based so the queue can run ablations on
    the frozen PIT rows without rebuilding the snapshot or changing labels.
    The full profile remains the default and is byte-for-byte compatible with
    the original sequence experiment.
    """
    if profile == "all":
        return list(names)
    groups = {
        "price_volume": ("market_", "benchmark", "industry", "sector", "style", "event_", "news_", "filing_", "earnings_", "announcement_", "fundamental_", "financial_", "macro_"),
        "market_industry": ("event_", "news_", "filing_", "earnings_", "announcement_", "fundamental_", "financial_", "macro_"),
        "market_industry_fundamental": ("event_", "news_", "filing_", "earnings_", "announcement_"),
        "market_industry_event": ("fundamental_", "financial_", "macro_"),
    }
    excluded = groups.get(profile)
    if excluded is None:
        raise ValueError(f"unknown feature profile:{profile}")
    selected = [name for name in names if not name.startswith(excluded)]
    if not selected:
        raise ValueError(f"feature profile has no features:{profile}")
    return selected


def _apply_feature_profile(examples, profile: str):
    if profile == "all" or not examples:
        return examples
    selected = _feature_profile_names(list(examples[0].feature_order), profile)
    indexes = [examples[0].feature_order.index(name) for name in selected]
    for example in examples:
        # Update one compact NumPy window at a time. Building nested Python
        # lists for every 60xN window temporarily doubled RAM and could restart
        # the 64 GiB training container during feature ablations.
        example.feature_order = selected
        example.values = np.asarray(example.values)[:, indexes]
        example.missing_mask = np.asarray(example.missing_mask)[:, indexes]
    return examples


def _prune_constant_features(examples):
    """Drop features with no development-period information.

    Selection uses only the pre-holdout dates and the final row of each
    sequence. That is sufficient to identify unavailable/constant channels,
    avoids touching final-test outcomes, and adds only a small temporary
    matrix instead of materialising every overlapping 60-session value.
    """
    if not examples:
        return examples, {"status": "empty", "dropped_features": []}
    dates = sorted({item.decision_time[:10] for item in examples})
    holdout_start = dates[-252] if len(dates) > 252 else dates[-1]
    development = [item for item in examples if item.decision_time[:10] < holdout_start]
    reference = development or examples
    values = np.stack([np.asarray(item.values)[-1] for item in reference]).astype(np.float32, copy=False)
    missing = np.stack([np.asarray(item.missing_mask)[-1] for item in reference]).astype(bool, copy=False)
    keep_indexes = []
    dropped = []
    names = list(examples[0].feature_order)
    for index, name in enumerate(names):
        observed = values[~missing[:, index], index]
        informative = observed.size > 0 and float(np.ptp(observed)) > 1e-12
        if informative:
            keep_indexes.append(index)
        else:
            dropped.append(name)
    if not keep_indexes:
        raise ValueError("development feature pruning removed every feature")
    selected = [names[index] for index in keep_indexes]
    del values, missing
    for example in examples:
        example.feature_order = selected
        example.values = np.asarray(example.values)[:, keep_indexes]
        example.missing_mask = np.asarray(example.missing_mask)[:, keep_indexes]
    return examples, {
        "status": "development_only_pruned",
        "holdout_start": holdout_start,
        "original_feature_count": len(names),
        "retained_feature_count": len(selected),
        "dropped_feature_count": len(dropped),
        "dropped_features": dropped,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train research-only CN sequence challengers")
    parser.add_argument("--sample-manifest", type=Path, nargs="+", default=[])
    parser.add_argument(
        "--sample-manifest-file", type=Path, action="append", default=[],
        help="JSON array or newline-delimited frozen manifest list for large cohorts.",
    )
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument(
        "--long-term-config", type=Path,
        default=PROJECT / "config/long_term_training.yaml",
        help="data-gate contract used before formal training starts",
    )
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/free_research_models")
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    parser.add_argument("--window", type=int, choices=(20, 60, 120), default=60)
    parser.add_argument("--cohort", choices=("cn_equity_core", "cn_etf_benchmark"), required=True)
    parser.add_argument("--training-run-id", default=None)
    parser.add_argument("--variant", default="default", help="isolates hyperparameter trials without overwriting artifacts")
    parser.add_argument(
        "--feature-profile",
        choices=("all", "price_volume", "market_industry", "market_industry_fundamental", "market_industry_event"),
        default="all",
        help="Frozen feature subset used by the automated ablation queue.",
    )
    parser.add_argument(
        "--keep-constant-features", action="store_true",
        help="Disable development-only constant/unavailable feature pruning.",
    )
    parser.add_argument("--screen-symbols", type=int, default=20)
    parser.add_argument("--allow-research-only", action="store_true")
    parser.add_argument("--rebuild-index", type=Path, default=None)
    parser.add_argument("--hidden-size", type=int, default=32)
    parser.add_argument("--layers", type=int, default=2)
    parser.add_argument("--max-epochs", type=int, default=8)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=0, help="0 uses the resource policy environment value")
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--dropout", type=float, default=0.15)
    parser.add_argument("--seeds", default="42,2026,3407", help="comma-separated deterministic seeds")
    parser.add_argument("--sequence-cache", type=Path, default=None, help="validated reusable sequence-example cache")
    # 1,260 sessions leave enough history after a 120-session input window,
    # task-label tail, 252-session holdout and 504/126 purged fold.  The former
    # 960 default could produce no valid fold even with otherwise complete CN
    # history.
    parser.add_argument("--maximum-dates", type=int, default=1260)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    active = None
    try:
        active = require_active_snapshot(args.data_root)
    except ActiveSnapshotInputError as exc:
        if not args.allow_research_only or args.rebuild_index is None:
            raise SystemExit(str(exc)) from exc
    if active is not None:
        contract = load_long_term_training_config(args.long_term_config)
        try:
            require_training_snapshot_gate(
                active,
                config=SnapshotGateConfig(
                    required_datasets=set(contract.required_snapshot_datasets),
                    minimum_financial_coverage=contract.minimum_financial_coverage,
                ),
                labels_mature=True,
                allow_research_only=args.allow_research_only,
            )
        except ActiveSnapshotInputError as exc:
            raise SystemExit(str(exc)) from exc
    output_root = args.output_root if args.output_root.is_absolute() else PROJECT / args.output_root
    early_scope = output_root / "cn" / "close_confirmed" / args.cohort / args.task / "sequence" / args.architecture
    if args.variant != "default":
        early_scope = early_scope / "variants" / args.variant
    if all((early_scope / name).is_file() and (early_scope / name).stat().st_size > 0 for name in ("sequence_evaluation.json", "sequence_manifest.json", "model.pt")):
        print(early_scope / "sequence_evaluation.json", flush=True)
        return 0
    manifest_paths = _sample_manifest_paths(args.sample_manifest, args.sample_manifest_file)
    # The manifest-list is intentionally broad, while this experiment is a
    # fixed-pool screen.  Select the same lexicographically first symbols that
    # the old post-load filter used before opening Parquet partitions; loading
    # every symbol first was the dominant memory and startup cost.
    cohort_paths = [path for path in manifest_paths if path.parent.parent.name == args.cohort]
    if not cohort_paths:
        raise SystemExit(f"no manifests found for cohort:{args.cohort}")
    # ETF benchmark rows provide features while the frozen equity samples are
    # built, but ETF labels must never enter the equity ranking objective.
    manifest_paths = cohort_paths
    if args.screen_symbols > 0:
        selected_symbols = sorted({path.parent.name for path in manifest_paths})[: args.screen_symbols]
        selected_set = set(selected_symbols)
        manifest_paths = [path for path in manifest_paths if path.parent.name in selected_set]
        print(f"MANIFEST_SYMBOL_FILTER {len(selected_symbols)} {selected_symbols}", flush=True)
    if args.maximum_dates > 0:
        # The experiment keeps only the latest ``maximum_dates`` decisions
        # after loading.  Avoid opening decades of yearly Parquet partitions
        # first: the 60-session window and purged folds need roughly two
        # hundred extra sessions, so the most recent ~200-session years plus
        # two safety years are sufficient.  This preserves the complete
        # symbol pool while keeping the full-pool run below the server cgroup
        # memory limit.
        years = sorted({
            int(path.name.split("-", 1)[0])
            for path in manifest_paths
            if path.name.split("-", 1)[0].isdigit()
        })
        keep_year_count = max(2, args.maximum_dates // 200 + 2)
        keep_years = set(years[-keep_year_count:])
        before = len(manifest_paths)
        manifest_paths = [
            path for path in manifest_paths
            if not path.name.split("-", 1)[0].isdigit()
            or int(path.name.split("-", 1)[0]) in keep_years
        ]
        print(
            f"MANIFEST_YEAR_FILTER {before} {len(manifest_paths)} years={sorted(keep_years)}",
            flush=True,
        )
    manifests = [json.loads(path.read_text(encoding="utf-8")) for path in manifest_paths]
    if not manifests or any(item.get("data_tier") != DataTier.RESEARCH_PIT.value for item in manifests):
        raise SystemExit("sequence training requires research_pit sample manifests")
    if active is not None:
        for item in manifests:
            try:
                assert_manifest_binding(active, item)
            except ActiveSnapshotInputError as exc:
                raise SystemExit(str(exc)) from exc
    if any("bundle_" in str(path) or "all_samples" in str(path) for path in manifest_paths):
        raise SystemExit("legacy pickle sample paths are forbidden")
    store = PITParquetStore(LocalObjectStore(args.object_store))
    rows: list[TrainingSample] = []
    snapshots = set()
    for manifest in manifests:
        snapshot = (manifest.get("market_snapshot_id"), manifest.get("market_snapshot_hash"))
        snapshots.add(snapshot)
        for row in store.read_partition(
            manifest["sample_parquet_ref"],
            expected_payload_hash=manifest.get("payload_hash"),
        ):
            value = dict(row)
            for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
                if isinstance(value.get(key), str):
                    value[key] = json.loads(value[key])
            sample = TrainingSample.model_validate(value)
            if (sample.market_snapshot_id, sample.market_snapshot_hash) != snapshot:
                raise SystemExit("sequence sample snapshot mismatch")
            rows.append(sample)
    print(f"LOADED_ROWS {len(rows)}", flush=True)
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
    print(f"FILTERED_ROWS {len(rows)} SYMBOLS {len({item.symbol for item in rows})} DATES {len({item.as_of_date for item in rows})}", flush=True)
    cache_key = _sequence_cache_key(manifests, target_name=_target(args.task), window=args.window)
    examples = _load_sequence_cache(args.sequence_cache, cache_key)
    if examples is None:
        print("BUILD_SEQUENCE_EXAMPLES_START", flush=True)
        examples = build_sequence_examples(rows, target_name=_target(args.task), window_sessions=args.window)
        _save_sequence_cache(args.sequence_cache, cache_key, examples)
    else:
        print(f"SEQUENCE_CACHE_HIT {len(examples)}", flush=True)
    if not examples:
        raise SystemExit("sequence scope has no valid windows")
    feature_pruning = {"status": "disabled", "dropped_features": []}
    if not args.keep_constant_features:
        examples, feature_pruning = _prune_constant_features(examples)
        print(
            f"FEATURE_PRUNING {feature_pruning['original_feature_count']} "
            f"{feature_pruning['retained_feature_count']} dropped={feature_pruning['dropped_feature_count']}",
            flush=True,
        )
    examples = _apply_feature_profile(examples, args.feature_profile)
    print(f"FEATURE_PROFILE {args.feature_profile} FEATURES {len(examples[0].feature_order)}", flush=True)
    print(f"BUILD_SEQUENCE_EXAMPLES_DONE {len(examples)}", flush=True)
    print("RUN_SEQUENCE_EXPERIMENT_START", flush=True)
    seeds = tuple(int(value.strip()) for value in args.seeds.split(",") if value.strip())
    if not seeds:
        raise SystemExit("--seeds must contain at least one integer")
    result = run_sequence_experiment(
        examples, task=args.task, architecture=args.architecture, window_sessions=args.window,
        config_overrides={
            "hidden_size": args.hidden_size,
            "layers": args.layers,
            "max_epochs": args.max_epochs,
            "patience": args.patience,
            "batch_size": args.batch_size or int(os.getenv("INVESTMENT_RESEARCH_SEQUENCE_BATCH_SIZE", "128")),
            "learning_rate": args.learning_rate,
            "dropout": args.dropout,
        },
        seeds=seeds,
    )
    print("RUN_SEQUENCE_EXPERIMENT_DONE", flush=True)
    date_ranges = _sequence_date_ranges(examples, task=args.task)
    run_id = args.training_run_id or f"sequence-{args.task}-{args.architecture}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    scope = output_root / "cn" / "close_confirmed" / args.cohort / args.task / "sequence" / args.architecture
    if args.variant != "default":
        scope = scope / "variants" / args.variant
    scope.mkdir(parents=True, exist_ok=True)
    # 断点续跑: skip a challenger whose evaluation + manifest already exist and are valid.
    seq_eval = scope / "sequence_evaluation.json"
    seq_manifest = scope / "sequence_manifest.json"
    if seq_eval.is_file() and seq_manifest.is_file():
        try:
            json.loads(seq_eval.read_text(encoding="utf-8"))
            json.loads(seq_manifest.read_text(encoding="utf-8"))
            print(seq_eval)
            return 0
        except (OSError, ValueError):
            pass  # corrupt -> retrain rather than trust it
    report = scope / "sequence_evaluation.json"
    model_path = scope / "model.pt"
    model_hash = result.final_runner.save(model_path) if result.final_runner is not None else None
    if result.final_runner is not None:
        (scope / "feature_order.json").write_text(
            json.dumps(result.final_runner.feature_order, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (scope / "normalizer.json").write_text(
            json.dumps(result.final_runner.stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (scope / "training_curve.json").write_text(
            json.dumps(result.final_runner.training_curve, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    result_payload = {key: value for key, value in asdict(result).items() if key != "final_runner"}
    dataset_hash = sha256(json.dumps(manifests, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot_id, snapshot_hash = next(iter(snapshots))
    feature_order_hash = sha256(json.dumps(examples[0].feature_order, separators=(",", ":")).encode()).hexdigest()
    normalizer_hash = sha256(json.dumps(result.final_runner.stats if result.final_runner else {}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = {"schema_version": "cn-sequence-evaluation-v1", "data_tier": "research_pit", "status": "research_only", "deployment_ready": False, "training_run_id": run_id, "task": args.task, "architecture": args.architecture, "variant": args.variant, "experiment_stage": "fixed_pool_screening", "training_symbol_count": len({item.symbol for item in rows}), "training_date_count": len({item.as_of_date for item in rows}), "training_date_range": date_ranges, "window_sessions": args.window, "input_shape": [args.window, len(examples[0].feature_order) * 2 + 9], "feature_contract_version": "cn-research-feature-v4.2-sequence-pruned", "feature_profile": args.feature_profile, "feature_pruning": feature_pruning, "dataset_hash": dataset_hash, "market_snapshot_id": snapshot_id, "market_snapshot_hash": snapshot_hash, "feature_order_hash": feature_order_hash, "normalizer_hash": normalizer_hash, "quality_mask_schema": ["quality_passed", "coverage", "no_data_issues"], "event_mask_schema": ["event_missing", "event_source_available"], "historical_visibility_assumption": "historical_available_at_unproven_public_backfill", "result": result_payload, "model_hash": model_hash}
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    artifact_hash = sha256(report.read_bytes()).hexdigest()
    summary = {"task": args.task, "architecture": args.architecture, "experiment_stage": "fixed_pool_screening", "training_symbol_count": len({item.symbol for item in rows}), "training_date_count": len({item.as_of_date for item in rows}), "training_date_range": date_ranges, "window_sessions": args.window, "input_shape": [args.window, len(examples[0].feature_order) * 2 + 9], "feature_contract_version": "cn-research-feature-v4.2-sequence-pruned", "feature_profile": args.feature_profile, "feature_pruning": feature_pruning, "label_version": "cn-direction-volatility-label-v3-task-specific", "dataset_hash": dataset_hash, "market_snapshot_id": snapshot_id, "market_snapshot_hash": snapshot_hash, "feature_order_hash": feature_order_hash, "normalizer_hash": normalizer_hash, "artifact_ref": _artifact_ref(model_path), "report_ref": _artifact_ref(report), "artifact_hash": model_hash, "report_hash": artifact_hash, "fold_hash": result.fold_hash, "quality_mask_schema": ["quality_passed", "coverage", "no_data_issues"], "event_mask_schema": ["event_missing", "event_source_available"], "status": "research_only", "research_status": "exploratory", "research_ready": False, "eligible_for_ensemble": False, "ensemble_exclusion_reason": "deep_regime_promotion_gate_not_met", "deployment_ready": False}
    (scope / "sequence_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (scope / "artifact_hash.json").write_text(
        json.dumps(
            {
                "model_hash": model_hash,
                "report_hash": artifact_hash,
                "feature_order_hash": feature_order_hash,
                "normalizer_hash": normalizer_hash,
                "fold_hash": result.fold_hash,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(report)
    return 0


def _target(task: str) -> str:
    return {
        "direction_1d": "direction_1d",
        "direction_5d": "direction_5d",
        "return_20d": "future_return_20d",
        "drawdown_20d": "future_max_drawdown_20d",
        "excess_return_5d": "excess_return_5d",
        "excess_return_20d": "excess_return_20d",
        "excess_return_120d": "excess_return_120d",
        "excess_return_240d": "excess_return_240d",
        "future_max_drawdown_120d": "future_max_drawdown_120d",
        "future_max_drawdown_240d": "future_max_drawdown_240d",
    }[task]


def _sequence_date_ranges(examples, *, task: str) -> dict[str, object]:
    """Record the exact date scopes used by the walk-forward experiment.

    ``run_sequence_experiment`` owns the split logic, so reusing the same
    helper here prevents the artifact metadata from drifting from the actual
    development/holdout/Shadow partitions.  Empty partitions are explicit
    rather than silently represented as a fabricated date.
    """
    development, _folds, holdout, stress, _fold_hash = split_sequence_examples(
        examples, horizon=_task_horizon_for_metadata(task)
    )
    development_dates = sorted({item.decision_time[:10] for item in development})
    holdout_dates = sorted({item.decision_time[:10] for item in holdout})
    stress_dates = sorted({item.decision_time[:10] for item in stress})
    dev_validation_start = date.fromisoformat(development_dates[-min(126, len(development_dates))]) if development_dates else None
    development_fit_dates = sorted({
        item.decision_time[:10]
        for item in development
        if dev_validation_start is not None
        and date.fromisoformat(item.decision_time[:10]) < dev_validation_start
        and (item.label_end is None or date.fromisoformat(item.label_end[:10]) < dev_validation_start)
    })

    def scope(dates: list[str], *, source: str) -> dict[str, object]:
        if not dates:
            return {"status": "empty", "start": None, "end": None, "count": 0, "source": source}
        return {"status": "recorded", "start": dates[0], "end": dates[-1], "count": len(dates), "source": source}

    return {
        "development": scope(development_dates, source="sequence_experiment_development_split"),
        "final_fit": scope(development_fit_dates, source="development_before_early_stopping_tail"),
        "holdout": scope(holdout_dates, source="immutable_final_holdout"),
        "shadow": scope(stress_dates, source="holdout_recent_stress_slice"),
    }


def _task_horizon_for_metadata(task: str) -> int:
    if task.endswith("120d"):
        return 120
    if task.endswith("240d"):
        return 240
    if task in {"direction_1d"}:
        return 1
    if task in {"direction_5d", "excess_return_5d"}:
        return 5
    return 20


def _artifact_ref(path: Path) -> str:
    """Use project-relative refs when possible, absolute refs for system-disk runs."""
    try:
        return str(path.relative_to(PROJECT))
    except ValueError:
        return str(path)


def _sample_manifest_paths(direct: list[Path], list_files: list[Path]) -> list[Path]:
    resolved = list(direct)
    for list_file in list_files:
        try:
            payload = json.loads(list_file.read_text(encoding="utf-8"))
            values = payload if isinstance(payload, list) else payload.get("sample_manifests")
        except (OSError, ValueError, AttributeError) as exc:
            raise SystemExit(f"invalid sample manifest file {list_file}: {type(exc).__name__}:{exc}") from exc
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise SystemExit(f"sample manifest file must contain a JSON string array: {list_file}")
        resolved.extend(Path(item) for item in values)
    unique = list(dict.fromkeys(path.resolve() for path in resolved))
    if not unique:
        raise SystemExit("one or more --sample-manifest or --sample-manifest-file values are required")
    missing = [str(path) for path in unique if not path.is_file()]
    if missing:
        raise SystemExit(f"sample manifest file is missing: {missing[0]}")
    return unique


def _sequence_cache_key(manifests: list[dict], *, target_name: str, window: int) -> str:
    payload = {"schema_version": "sequence-example-cache-v1", "target_name": target_name, "window": window, "manifests": manifests}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load_sequence_cache(path: Path | None, key: str):
    if path is None or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
        if payload.get("schema_version") != "sequence-example-cache-v1" or payload.get("key") != key:
            return None
        examples = payload.get("examples")
        return examples if isinstance(examples, list) and examples else None
    except (OSError, ValueError, TypeError, pickle.PickleError):
        return None


def _save_sequence_cache(path: Path | None, key: str, examples) -> None:
    if path is None or not examples:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("wb") as handle:
            pickle.dump({"schema_version": "sequence-example-cache-v1", "key": key, "examples": examples}, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(path)
        print(f"SEQUENCE_CACHE_WRITTEN {path}", flush=True)
    except OSError:
        temporary.unlink(missing_ok=True)
        print("SEQUENCE_CACHE_SKIPPED disk_or_io_error", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
