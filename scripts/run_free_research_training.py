#!/usr/bin/env python3
"""Evaluate independent public-data research tasks without formal publication.

The command reads only a free-research sample Parquet manifest.  It uses the
same purged walk-forward, OOF calibration and single-use final-holdout guards
as the formal runners, while permanently emitting non-deployable manifests.
It is therefore useful for evidence accumulation without claiming that public
historical backfills constitute formal PIT data.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_TIER_REASONS
from investment_research.training.formal_direction_runner import FormalDirectionTrainingRunner
from investment_research.training.formal_return_runner import FormalReturnTrainingRunner
from investment_research.training.formal_risk_runner import FormalRiskTrainingRunner
from investment_research.training.formal_training import FinalHoldoutLedger
from investment_research.training.models import TrainingSample
from investment_research.training.numeric_safety import guarded_model_math
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.research_evaluation import (
    research_scope_reports,
    select_research_roster_candidates,
    write_research_reports,
)
from investment_research.pipeline.research_roster import build_research_roster
from investment_research.service.object_store import LocalObjectStore


TASKS = ("drawdown_20d", "direction_1d", "direction_5d", "return_20d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run research-only public-data model comparisons")
    parser.add_argument(
        "--sample-manifest", type=Path, nargs="+", required=True,
        help="One or more per-symbol sample manifests from the same CN cohort and decision context",
    )
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts" / "free_research_models")
    parser.add_argument("--training-run-id", default=None)
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--cohort", choices=("cn_equity_core", "cn_etf_benchmark"), default=None)
    parser.add_argument("--minimum-cohort-symbols", type=int, default=80, help="Research-only override for a deliberately small fixture/cohort; formal-sized runs keep the default 80-symbol gate.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = [json.loads(path.read_text(encoding="utf-8")) for path in args.sample_manifest]
    for source in sources:
        if source.get("data_tier") != DataTier.RESEARCH_PIT.value or source.get("formal_pit_eligible"):
            raise SystemExit("free research training requires research_pit, non-formal sample manifests")
    market = _single_value(sources, "market")
    context = _single_value(sources, "decision_context")
    cohort = args.cohort or _single_value(sources, "cohort", default="cn_equity_core")
    cohort_version = _single_value(sources, "cohort_version", default=f"legacy-{cohort}")
    feature_contract_version = _single_value(sources, "feature_version", default="investment-risk-features-v2")
    label_version = _single_value(sources, "label_version", default="four-market-tradeable-label-v1")
    if any(source.get("cohort", "cn_equity_core") != cohort for source in sources):
        raise SystemExit("all sample manifests must belong to the selected cohort")
    store = PITParquetStore(LocalObjectStore(args.object_store))
    samples_by_key: dict[tuple[str, str, str], TrainingSample] = {}
    snapshot_refs: set[tuple[str | None, str | None]] = set()
    for source in sources:
        rows = store.read_partition(source["sample_parquet_ref"])
        expected_snapshot = (source.get("market_snapshot_id"), source.get("market_snapshot_hash"))
        if not isinstance(expected_snapshot[0], str) or not expected_snapshot[0]:
            raise SystemExit("sample manifest lacks market_snapshot_id")
        if not isinstance(expected_snapshot[1], str) or len(expected_snapshot[1]) != 64:
            raise SystemExit("sample manifest lacks a valid market_snapshot_hash")
        for row in rows:
            sample = TrainingSample.model_validate(_restore_maps(row))
            if sample.data_tier != DataTier.RESEARCH_PIT.value:
                raise SystemExit(
                    f"sample row is not research_pit for {sample.symbol}:{sample.as_of_date}"
                )
            if (sample.market_snapshot_id, sample.market_snapshot_hash) != expected_snapshot:
                raise SystemExit(
                    f"sample row snapshot differs from manifest for {sample.symbol}:{sample.as_of_date}"
                )
            key = (sample.symbol, sample.as_of_time.isoformat(), sample.decision_context)
            if key in samples_by_key and samples_by_key[key].model_dump(mode="json") != sample.model_dump(mode="json"):
                raise SystemExit(f"conflicting duplicate research sample: {key}")
            samples_by_key[key] = sample
        snapshot_refs.add((source.get("market_snapshot_id"), source.get("market_snapshot_hash")))
    if len(snapshot_refs) != 1:
        raise SystemExit("one scope training run cannot mix different market snapshots")
    samples = sorted(samples_by_key.values(), key=lambda item: (item.as_of_time, item.symbol))
    if not samples:
        raise SystemExit("research sample partitions have no samples")
    if market != "cn":
        raise SystemExit("the zero-budget competition workflow trains CN research scopes only")
    if any(sample.market.value != market or sample.decision_context != context for sample in samples):
        raise SystemExit("sample rows do not match their manifest market/decision context")
    symbol_count = len({sample.symbol for sample in samples})
    if cohort == "cn_equity_core" and symbol_count < args.minimum_cohort_symbols:
        raise SystemExit(f"cn_equity_core training requires at least {args.minimum_cohort_symbols} fixed-cohort symbols")
    if cohort == "cn_etf_benchmark" and symbol_count != 5:
        raise SystemExit("cn_etf_benchmark training requires all five fixed ETFs")
    dataset_hash = _dataset_hash(args.sample_manifest, sources)
    run_id = args.training_run_id or f"research-{market}-{context}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    root = args.output_root / market / context / cohort
    ledger = FinalHoldoutLedger(root / "audits" / f"{run_id}-final_holdout_ledger.json")
    outcomes: list[dict] = []
    for task in args.tasks:
        scope = root / task
        scope.mkdir(parents=True, exist_ok=True)
        try:
            # Public backfills include the newest rows whose future window is
            # not observable yet.  Exclude those rows before the formal
            # walk-forward planner; do not let an unavailable label become a
            # training failure for otherwise usable research history.
            task_samples = _eligible_samples(
                task,
                [item for item in samples if item.labels.label_available and item.labels.label_end is not None],
            )
            task_samples = _recent_task_history(task_samples, maximum_dates=1260)
            distinct_dates = len({item.as_of_date for item in task_samples})
            required_dates = _minimum_task_dates(task)
            if distinct_dates < required_dates:
                raise ValueError(
                    f"insufficient_training_history:{distinct_dates}<{required_dates}:{task}"
                )
            result = _run(task, samples=task_samples, market=market, context=context,
                          dataset_hash=dataset_hash, ledger=ledger)
            result_payload = _jsonable(result)
            primary_candidate, fallback_candidate, challenger_candidates, research_ready = select_research_roster_candidates(
                task, result, cohort=cohort,
            )
            research_status = "research_ready" if research_ready else "exploratory"
            evaluation_path = scope / "evaluation.json"
            evaluation_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            evaluation_hash = sha256(evaluation_path.read_bytes()).hexdigest()
            artifact_hashes = _freeze_research_artifacts(
                task=task, result=result, samples=task_samples, scope=scope,
                primary_candidate=primary_candidate, fallback_candidate=fallback_candidate,
            )
            snapshot_hash = next(iter(snapshot_refs))[1]
            assert snapshot_hash is not None
            reports = research_scope_reports(
                task=task, result=result, samples=task_samples, dataset_hash=dataset_hash,
                snapshot_hash=snapshot_hash, cohort=cohort,
            )
            report_hashes = write_research_reports(scope / "reports", reports)
            manifest = {
                "schema_version": "free-research-task-manifest-v2",
                "data_tier": DataTier.RESEARCH_PIT.value,
                "status": "research_only",
                "deployment_ready": False,
                "market": market,
                "decision_context": context,
                "cohort": cohort,
                "cohort_version": cohort_version,
                "task": task,
                "model_version": f"{run_id}:{task}:{result_payload['fold_hash'][:12]}",
                "label_version": f"{label_version}:{task}",
                "feature_contract_version": feature_contract_version,
                "research_ready": research_ready,
                "research_status": research_status,
                "training_run_id": run_id,
                "dataset_manifest_refs": [_portable_ref(path) for path in args.sample_manifest],
                "dataset_hash": dataset_hash,
                "sample_count": len(task_samples),
                "symbol_count": len({sample.symbol for sample in task_samples}),
                "training_date_range": {
                    "start": min(item.as_of_date for item in task_samples).isoformat(),
                    "end": max(item.as_of_date for item in task_samples).isoformat(),
                    "distinct_dates": len({item.as_of_date for item in task_samples}),
                },
                "market_snapshot_refs": [
                    {"market_snapshot_id": item[0], "market_snapshot_hash": item[1]}
                    for item in sorted(snapshot_refs, key=lambda value: (value[0] or "", value[1] or ""))
                ],
                "market_snapshot_hash": snapshot_hash,
                "fold_hash": result_payload["fold_hash"],
                # The manifest's selected candidate is the roster primary,
                # after the research Gate has decided whether the raw
                # evaluation winner is eligible.  The raw winner remains in
                # evaluation.json for audit.
                "selected_candidate": primary_candidate,
                "roster_primary_candidate": primary_candidate,
                "roster_fallback_candidate": fallback_candidate,
                "evaluation_ref": _portable_ref(evaluation_path),
                "artifact_hashes": {"evaluation.json": evaluation_hash, **artifact_hashes},
                "report_hashes": report_hashes,
                "code_hash": _code_hash(),
                "artifact_state": "frozen_research_only",
                "validation_policy": {
                    "purged_walk_forward": True,
                    "embargo_sessions": 1 if task == "direction_1d" else 5 if task == "direction_5d" else 20,
                    "holdout_sessions": 252,
                    "stress_sessions": 126,
                    "calibration_source": "time_oof_only",
                },
                "deep_challenger_policy": {
                    "families": ["mlp", "patchtst", "tcn", "itransformer"],
                    "primary_models": ["lightgbm", "random-forest", "xgboost"],
                    "classification_minimum_auroc_delta": 0.03,
                    "return_minimum_pinball_improvement_ratio": 0.05,
                    "minimum_qualifying_regimes": 2,
                    "automatic_primary_replacement": False,
                },
                "research_gate": {
                    "passed": research_ready,
                    "status": "passed" if research_ready else "failed",
                    "reasons": _research_gate_reasons(task, result, research_ready, cohort),
                    "primary_selection": "best_eligible_candidate" if research_ready else "simple_baseline_retained",
                },
                "sequence_challenger_artifacts": [],
                "blocking_reasons": list(RESEARCH_TIER_REASONS),
            }
            manifest_path = scope / "task_manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            dependency_hash = sha256((PROJECT / "pyproject.toml").read_bytes()).hexdigest()
            roster = build_research_roster(
                task_manifest=manifest, primary_candidate=primary_candidate,
                fallback_candidate=fallback_candidate, challenger_candidates=[],
                cohort_version=cohort_version, dependency_hash=dependency_hash,
            )
            roster_path = scope / "research_model_roster.json"
            roster_path.write_text(roster.model_dump_json(indent=2), encoding="utf-8")
            outcomes.append({
                "task": task, "status": "research_only", "research_status": research_status,
                "manifest": _portable_ref(manifest_path), "roster": _portable_ref(roster_path),
                # These candidates were evaluated on the same folds but were
                # not selected as primary/fallback.  The former field name
                # `unevaluated_challengers` incorrectly implied missing work.
                "evaluated_challengers": challenger_candidates,
            })
        except Exception as exc:
            outcomes.append({"task": task, "status": "blocked", "reason": f"{type(exc).__name__}:{exc}"})
    summary = {
        "schema_version": "free-research-training-run-v1", "data_tier": "research_pit",
        "status": "research_only", "deployment_ready": False, "training_run_id": run_id,
        "market": market, "decision_context": context, "outcomes": outcomes,
        "cohort": cohort, "sample_count": len(samples),
        "symbol_count": len({sample.symbol for sample in samples}),
        "dataset_hash": dataset_hash,
        "feature_contract_version": feature_contract_version,
        "label_version": label_version,
    }
    summary_path = root / f"{run_id}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)
    return 0 if all(item["status"] == "research_only" for item in outcomes) else 2


def _run(task, *, samples, market, context, dataset_hash, ledger):
    if task == "drawdown_20d":
        return FormalRiskTrainingRunner().run(samples=samples, market=market, decision_context=context, dataset_hash=dataset_hash, holdout_ledger=ledger)
    if task.startswith("direction_"):
        return FormalDirectionTrainingRunner().run(samples=samples, market=market, decision_context=context, horizon=int(task.split("_")[1][:-1]), dataset_hash=dataset_hash, holdout_ledger=ledger)
    return FormalReturnTrainingRunner().run(samples=samples, market=market, decision_context=context, dataset_hash=dataset_hash, holdout_ledger=ledger)


def _minimum_task_dates(task: str) -> int:
    horizon = 1 if task == "direction_1d" else 5 if task == "direction_5d" else 20
    return 252 + 504 + 126 + (2 * horizon)


def _research_gate_reasons(task: str, result, research_ready: bool, cohort: str) -> list[str]:
    if research_ready:
        return []
    if cohort == "cn_etf_benchmark":
        return ["etf_baseline_and_shadow_only", "cross_sectional_sample_insufficient"]
    selected = next(item for item in result.candidates if item.name == result.selected_candidate)
    reasons = ["task_metric_gate_not_met"]
    regimes = getattr(selected, "regime_metrics", {})
    if len(regimes) < 2 or sum(float(value.get("sample_count", 0)) >= 30 for value in regimes.values()) < 2:
        reasons.append("regime_sample_insufficient")
    if task.startswith("direction_"):
        reasons.append("direction_calibration_or_macro_f1_gate_not_met")
    elif task == "return_20d":
        reasons.append("return_distribution_gate_not_met")
    else:
        reasons.append("risk_alert_or_regime_gate_not_met")
    return list(dict.fromkeys(reasons))


def _recent_task_history(samples: list[TrainingSample], *, maximum_dates: int) -> list[TrainingSample]:
    dates = sorted({item.as_of_date for item in samples})
    if len(dates) <= maximum_dates:
        return samples
    retained = set(dates[-maximum_dates:])
    return [item for item in samples if item.as_of_date in retained]


def _restore_maps(row: dict) -> dict:
    value = dict(row)
    for key in ("features", "labels", "data_quality_mask", "event_missing_mask"):
        if isinstance(value.get(key), str):
            value[key] = json.loads(value[key])
    return value


def _single_value(sources: list[dict], key: str, *, default: str | None = None) -> str:
    values = {source.get(key, default) for source in sources}
    if None in values or len(values) != 1:
        raise SystemExit(f"all sample manifests must share one {key}: {sorted(str(item) for item in values)}")
    return str(next(iter(values)))


def _dataset_hash(paths: list[Path], sources: list[dict]) -> str:
    evidence = []
    for path, source in zip(paths, sources, strict=True):
        payload_hash = source.get("payload_hash")
        if not isinstance(payload_hash, str) or len(payload_hash) != 64:
            raise SystemExit(f"sample manifest lacks a valid payload_hash: {path}")
        evidence.append({
            "market": source.get("market"), "symbol": source.get("symbol"),
            "decision_context": source.get("decision_context"),
            "trade_year": source.get("trade_year"), "payload_hash": payload_hash,
        })
    encoded = json.dumps(
        sorted(evidence, key=lambda item: (str(item["symbol"]), str(item["trade_year"]), item["payload_hash"])),
        sort_keys=True, separators=(",", ":"),
    )
    return sha256(encoded.encode()).hexdigest()


def _portable_ref(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT).as_posix()
    except ValueError:
        return resolved.as_uri()


def _code_hash() -> str:
    paths = [
        PROJECT / "pyproject.toml",
        PROJECT / "src/investment_research/training/formal_training.py",
        PROJECT / "src/investment_research/training/formal_direction_runner.py",
        PROJECT / "src/investment_research/training/formal_return_runner.py",
        PROJECT / "src/investment_research/training/formal_risk_runner.py",
        PROJECT / "src/investment_research/training/research_evaluation.py",
        PROJECT / "src/investment_research/training/labels.py",
    ]
    digest = sha256()
    for path in paths:
        digest.update(path.relative_to(PROJECT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _jsonable(value):
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _freeze_research_artifacts(
    *, task: str, result, samples: list[TrainingSample], scope: Path,
    primary_candidate: str, fallback_candidate: str,
) -> dict[str, str]:
    samples = _eligible_samples(task, samples)
    feature_order = sorted({name for sample in samples for name in sample.features})
    if not feature_order:
        raise ValueError("research artifact has no feature order")
    selected = primary_candidate
    matrix = _artifact_matrix(samples, feature_order)
    package = {
        "schema_version": "free-research-model-artifact-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "status": "research_only", "deployment_ready": False,
        "task": task, "selected_candidate": selected,
        "feature_order": feature_order,
        "feature_bounds": {
            name: [float(matrix[name].min()), float(matrix[name].max())]
            for name in feature_order
        },
    }
    if task == "drawdown_20d":
        from investment_research.training.calibration import compare_calibrators
        from investment_research.training.formal_risk_runner import _estimator, _label
        labels = [_label(sample, -0.08) for sample in samples]
        candidate = next(item for item in result.candidates if item.name == selected)
        calibrator, _ = compare_calibrators(
            calibration_scores=candidate.raw_oof_scores,
            calibration_labels=candidate.oof_labels,
            prediction_fold_ids=candidate.oof_fold_ids,
            training_fold_ids=["full_research_refit"],
        )
        if selected == "historical-distribution":
            package.update(kind="constant_risk", probability=sum(labels) / len(labels), calibrator=calibrator)
        else:
            estimator = _estimator(selected)
            with guarded_model_math():
                estimator.fit(matrix, labels)
            package.update(kind="risk_classifier", estimator=estimator, calibrator=calibrator)
        alternatives = [item for item in result.candidates if item.name == fallback_candidate]
        if alternatives:
            alternative = fallback_candidate
            if alternative == "historical-distribution":
                package["comparator"] = {"kind": "constant_risk", "probability": sum(labels) / len(labels), "name": alternative}
            else:
                comparator = _estimator(alternative)
                with guarded_model_math():
                    comparator.fit(matrix, labels)
                package["comparator"] = {"kind": "risk_classifier", "estimator": comparator, "name": alternative}
    elif task.startswith("direction_"):
        from investment_research.training.calibration import CalibrationMethod, TimeOutOfFoldCalibrator
        from investment_research.training.formal_direction_runner import CLASSES, _class_index, _direction, _estimator
        horizon = int(task.split("_")[1][:-1])
        labels = [_direction(sample, horizon) for sample in samples]
        frequencies = {label: (labels.count(label) + 1) / (len(labels) + len(CLASSES)) for label in CLASSES}
        candidate = next(item for item in result.candidates if item.name == selected)
        calibrators = {}
        ids = [f"time_oof:{index}" for index in range(len(candidate.labels))]
        for label in CLASSES:
            targets = [int(value == label) for value in candidate.labels]
            if len(set(targets)) > 1:
                calibrators[label] = TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit(
                    [row[label] for row in candidate.raw_probabilities], targets,
                    prediction_fold_ids=ids, training_fold_ids=["full_research_refit"],
                )
        if selected in {"constant-class", "random", "index-direction", "momentum"}:
            base_probabilities = ({label: 1 / len(CLASSES) for label in CLASSES} if selected == "random" else frequencies)
            package.update(kind=selected, class_probabilities=base_probabilities, calibrators=calibrators, horizon=horizon)
        else:
            estimator = _estimator(selected)
            with guarded_model_math():
                estimator.fit(matrix, [_class_index(value) for value in labels] if selected == "xgboost" else labels)
            package.update(kind="direction_classifier", estimator=estimator, calibrators=calibrators, horizon=horizon)
        alternatives = [item for item in result.candidates if item.name == fallback_candidate]
        if alternatives:
            alternative = fallback_candidate
            component = {
                "kind": alternative, "name": alternative,
                "class_probabilities": ({label: 1 / len(CLASSES) for label in CLASSES} if alternative == "random" else frequencies),
                "horizon": horizon,
            }
            if alternative not in {"constant-class", "random", "index-direction", "momentum"}:
                comparator = _estimator(alternative)
                with guarded_model_math():
                    comparator.fit(matrix, [_class_index(value) for value in labels] if alternative == "xgboost" else labels)
                component = {"kind": "direction_classifier", "name": alternative, "estimator": comparator, "horizon": horizon}
            package["comparator"] = component
    else:
        from investment_research.training.formal_return_runner import QUANTILES, _estimator, _quantile, _target
        targets = [_target(sample) for sample in samples]
        if selected == "historical-distribution":
            package.update(kind="constant_quantiles", quantiles=[_quantile(targets, value) for value in QUANTILES])
        else:
            estimators = []
            for quantile in QUANTILES:
                estimator = _estimator(selected, quantile)
                with guarded_model_math():
                    estimator.fit(matrix, targets)
                estimators.append(estimator)
            package.update(kind="return_quantile", estimators=estimators, quantiles=list(QUANTILES))
        fallback_estimators = []
        if fallback_candidate == "historical-distribution":
            package["comparator"] = {
                "kind": "constant_quantiles", "name": fallback_candidate,
                "quantiles": [_quantile(targets, value) for value in QUANTILES],
            }
        else:
            for quantile in QUANTILES:
                estimator = _estimator(fallback_candidate, quantile)
                with guarded_model_math():
                    estimator.fit(matrix, targets)
                fallback_estimators.append(estimator)
            package["comparator"] = {
                "kind": "return_quantile", "name": fallback_candidate,
                "estimators": fallback_estimators, "quantiles": list(QUANTILES),
            }
    model_path = scope / "research_model.joblib"
    feature_path = scope / "feature_order.json"
    joblib.dump(package, model_path)
    feature_path.write_text(json.dumps(feature_order, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        model_path.name: sha256(model_path.read_bytes()).hexdigest(),
        feature_path.name: sha256(feature_path.read_bytes()).hexdigest(),
    }


def _artifact_matrix(samples: list[TrainingSample], feature_order: list[str]):
    """Create the same finite, named matrix contract used by task runners."""
    import numpy as np
    import pandas as pd

    values = np.asarray([
        [float(sample.features.get(name, 0.0)) for name in feature_order]
        for sample in samples
    ], dtype=float)
    values = np.nan_to_num(values, nan=0.0, posinf=1e6, neginf=-1e6)
    return pd.DataFrame(np.clip(values, -1e6, 1e6), columns=feature_order)


def _eligible_samples(task: str, samples: list[TrainingSample]) -> list[TrainingSample]:
    if task == "drawdown_20d":
        result = [item for item in samples if item.labels.future_max_drawdown_20d is not None]
    elif task == "direction_1d":
        result = [item for item in samples if item.labels.direction_1d in {"up", "down", "flat"}]
    elif task == "direction_5d":
        result = [item for item in samples if item.labels.direction_5d in {"up", "down", "flat"}]
    else:
        result = [
            item for item in samples
            if item.labels.future_return_20d is not None or item.labels.future_return_20d_from_open is not None
        ]
    if not result:
        raise ValueError(f"no labeled samples available for {task} research artifact")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
