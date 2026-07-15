#!/usr/bin/env python3
"""Create hash-verified, research-only CN predictions for Shadow freezing."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import joblib

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.object_store import LocalObjectStore
from investment_research.training.models import PreparedPriceBar, TrainingSample
from investment_research.training.parquet_store import PITParquetStore
from investment_research.training.sequence_dataset import build_sequence_examples
from investment_research.training.sequence_models import SequenceTaskRunner
from investment_research.pipeline.research_roster import load_verified_research_roster

TASKS = ("drawdown_20d", "direction_1d", "direction_5d", "return_20d")
CLASSES = ("up", "down", "flat")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run zero-budget CN research inference")
    parser.add_argument("--rebuild-index", type=Path, required=True)
    parser.add_argument("--roster-root", type=Path, default=PROJECT / "artifacts/free_research_models")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--decision-context", choices=("close_confirmed",), default="close_confirmed")
    parser.add_argument("--cohort", choices=("cn_equity_core", "cn_etf_benchmark"), required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/predictions/cn-research.json")
    parser.add_argument("--cache-state", choices=("fresh", "stale_usable", "expired", "unavailable"), default="fresh")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = json.loads(args.rebuild_index.read_text(encoding="utf-8"))
    if index.get("data_tier") != "research_pit" or index.get("deployment_ready"):
        raise SystemExit("inference requires a non-deployable research_pit rebuild index")
    context = index["contexts"][args.decision_context]
    cohort_manifest = json.loads(Path(index["cohort_refs"][args.cohort]).read_text(encoding="utf-8"))
    cohort_version = cohort_manifest["cohort_version"]
    store = PITParquetStore(LocalObjectStore(args.object_store))
    standard = _standard_by_symbol(index)
    predictions = []
    for symbol in args.symbols:
        symbol_samples = _samples_for_symbol(context, args.cohort, symbol, store)
        sample = max(symbol_samples, key=lambda item: item.as_of_time)
        reference_price = _latest_price(standard[symbol], store)
        influence = [
            f"{name}={sample.features[name]:.4g}"
            for name in sorted(sample.features, key=lambda key: abs(float(sample.features[key])), reverse=True)[:5]
        ]
        for task in TASKS:
            scope = args.roster_root / "cn" / args.decision_context / args.cohort / task
            roster_path = scope / "research_model_roster.json"
            record = {
                "decision_context": args.decision_context, "cohort": args.cohort,
                "task": task, "symbol": symbol,
                "trade_date": sample.as_of_date.isoformat(),
                "frozen_at": datetime.now(timezone.utc).isoformat(),
                "market_snapshot_id": context["snapshot_id"],
                "market_snapshot_hash": context["snapshot_hash"],
                "prediction_price": reference_price,
                "coverage_ratio": sample.feature_coverage,
                "event_coverage_status": sample.event_coverage_status,
                "provider_chain": [sample.provider] if sample.provider else [],
                "evidence_coverage": sample.feature_coverage,
                "influence_facts": influence,
                "cache_state": args.cache_state,
                "data_quality_mask": dict(sample.data_quality_mask),
                "event_missing_mask": dict(sample.event_missing_mask),
                "provider_id": sample.provider_id or sample.provider,
                "revision_id": sample.revision_id,
                "source_delay_seconds": sample.source_delay_seconds,
                "candidate_predictions": _sequence_challenger_predictions(scope, symbol_samples, task),
                "ensemble_weights": {},
            }
            if not roster_path.is_file():
                record.update(
                    status="unavailable", prediction_status="unavailable", prediction={},
                    model_artifact_hashes={}, abstained=True,
                    abstain_reasons=["research_roster_missing"],
                    gating_reasons=["research_roster_missing"],
                )
                predictions.append(record)
                continue
            try:
                roster = load_verified_research_roster(
                    roster_path, market="cn", decision_context=args.decision_context,
                    cohort_version=cohort_version, task=task, project_root=PROJECT,
                )
                if roster.market_snapshot_hash != context["snapshot_hash"]:
                    raise ValueError("research roster snapshot hash mismatch")
                package_path = (PROJECT / roster.primary.artifact_ref).resolve()
                package = joblib.load(package_path)
                if package.get("selected_candidate") != roster.primary.candidate_name:
                    raise ValueError("research roster primary differs from model package")
                role = "primary"
                try:
                    prediction, disagreement = _predict(package, sample)
                except Exception as primary_exc:
                    if package.get("comparator", {}).get("name") != roster.fallback.candidate_name:
                        raise ValueError("research fallback component mismatch") from primary_exc
                    prediction, disagreement = _predict_fallback(package, sample)
                    role = "fallback"
                ensemble_prediction, ensemble_weights, sequence_disagreement = _ensemble_with_sequence_challengers(
                    task, prediction, record["candidate_predictions"]
                )
                if ensemble_prediction is not None:
                    prediction = {**prediction, "ensemble": ensemble_prediction}
                    record["ensemble_weights"] = ensemble_weights
                    disagreement = max(float(disagreement or 0.0), sequence_disagreement)
                reasons = _abstain_reasons(
                    task=task, sample=sample, package=package, disagreement=disagreement,
                    cache_state=args.cache_state,
                    provider_conflict=_has_provider_conflict(index, symbol),
                )
                record.update(
                    prediction={} if reasons else prediction,
                    status="abstain" if reasons else "research_only",
                    prediction_status="abstain" if reasons else "research_only",
                    gating_reasons=reasons,
                    model_artifact_hashes=dict(roster.primary.artifact_hashes),
                    model_disagreement=disagreement,
                    model_role=role, model_candidate=(roster.primary if role == "primary" else roster.fallback).candidate_name,
                    roster_hash=roster.roster_hash,
                    abstained=bool(reasons), abstain_reasons=reasons,
                )
            except Exception as exc:
                record.update(
                    status="unavailable" if isinstance(exc, FileNotFoundError) else "abstain",
                    prediction_status="unavailable" if isinstance(exc, FileNotFoundError) else "abstain",
                    prediction={}, model_artifact_hashes={},
                    inference_blocking_reason=f"{type(exc).__name__}:{exc}",
                    abstained=True, abstain_reasons=["roster_or_artifact_validation_failed"],
                    gating_reasons=["roster_or_artifact_validation_failed"],
                )
            predictions.append(record)
    payload = {
        "schema_version": "cn-free-research-predictions-v1",
        "data_tier": "research_pit", "status": "research_only",
        "deployment_ready": False, "predictions": predictions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


def _latest_sample(context: dict, cohort: str, symbol: str, store: PITParquetStore) -> TrainingSample:
    """Compatibility helper for callers that need one frozen latest row."""
    return max(_samples_for_symbol(context, cohort, symbol, store), key=lambda item: item.as_of_time)


def _samples_for_symbol(context: dict, cohort: str, symbol: str, store: PITParquetStore) -> list[TrainingSample]:
    paths = [Path(path) for path in context["sample_manifests"].get(cohort, [])]
    matches = [path for path in paths if json.loads(path.read_text(encoding="utf-8"))["symbol"] == symbol]
    if not matches:
        raise ValueError(f"symbol is absent from frozen cohort snapshot:{symbol}")
    rows = []
    for path in matches:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (manifest["market_snapshot_id"], manifest["market_snapshot_hash"]) != (context["snapshot_id"], context["snapshot_hash"]):
            raise ValueError("sample manifest snapshot mismatch")
        rows.extend(store.read_partition(manifest["sample_parquet_ref"]))
    samples = [TrainingSample.model_validate(_restore_maps(row)) for row in rows]
    if not samples:
        raise ValueError(f"symbol has no frozen samples:{symbol}")
    if any((item.market_snapshot_id, item.market_snapshot_hash) != (context["snapshot_id"], context["snapshot_hash"]) for item in samples):
        raise ValueError("sample row snapshot mismatch")
    return samples


def _latest_price(manifest: dict, store: PITParquetStore) -> float:
    rows = []
    for partition in manifest["partitions"]:
        rows.extend(store.read_partition(partition["parquet_ref"]))
    bars = [PreparedPriceBar.model_validate(row) for row in rows]
    return float(max(bars, key=lambda item: item.trade_date).close_native)


def _standard_by_symbol(index: dict) -> dict[str, dict]:
    output = {}
    for ref in index.get("standard_manifest_refs", []):
        manifest = json.loads(Path(ref).read_text(encoding="utf-8"))
        output[manifest["symbol"]] = manifest
    return output


def _sequence_challenger_evidence(scope: Path) -> dict[str, dict]:
    """Expose frozen sequence challenger evidence without bypassing roster.

    A challenger is never promoted by this helper.  It only reports the
    independently hashed sequence artifacts that can later be evaluated by a
    dedicated sequence inference runner.
    """
    root = scope / "sequence"
    output: dict[str, dict] = {}
    if not root.is_dir():
        return output
    for manifest_path in root.glob("*/sequence_manifest.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        output[str(payload.get("architecture", manifest_path.parent.name))] = {
            "status": payload.get("status", "research_only"),
            "artifact_ref": payload.get("artifact_ref"),
            "artifact_hash": payload.get("artifact_hash"),
            "report_ref": payload.get("report_ref"),
            "report_hash": payload.get("report_hash"),
            "fold_hash": payload.get("fold_hash"),
        }
    return output


def _sequence_challenger_predictions(scope: Path, samples: list[TrainingSample], task: str) -> dict[str, dict]:
    root = scope / "sequence"
    output: dict[str, dict] = {}
    if not root.is_dir():
        return output
    target = {"direction_1d": "direction_1d", "direction_5d": "direction_5d", "return_20d": "future_return_20d", "drawdown_20d": "future_max_drawdown_20d"}[task]
    for manifest_path in root.glob("*/sequence_manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact = (PROJECT / manifest["artifact_ref"]).resolve()
            if not artifact.is_file():
                continue
            examples = build_sequence_examples(samples, target_name=target, window_sessions=int(manifest["window_sessions"]))
            if not examples:
                continue
            runner = SequenceTaskRunner.load(artifact)
            latest = max(examples, key=lambda item: item.decision_time)
            output[str(manifest.get("architecture", manifest_path.parent.name))] = {
                "status": "research_only", "raw_prediction": runner.predict_raw([latest])[0],
                "artifact_ref": manifest.get("artifact_ref"), "artifact_hash": manifest.get("artifact_hash"),
                "fold_hash": manifest.get("fold_hash"),
            }
        except (OSError, ValueError, KeyError, RuntimeError, IndexError):
            continue
    return output


def _ensemble_with_sequence_challengers(task: str, base: dict, candidates: dict[str, dict]) -> tuple[dict | None, dict[str, float], float]:
    """Combine raw challenger outputs without promoting them or bypassing calibration.

    The base roster model remains the calibrated primary.  The returned
    ensemble is an explicitly labelled research diagnostic; disagreement is
    still fed into the normal abstain gate.
    """
    usable = {name: value for name, value in candidates.items() if isinstance(value, dict) and isinstance(value.get("raw_prediction"), list)}
    if not usable:
        return None, {}, 0.0
    weights = {"tabular_primary": 0.5}
    challenger_weight = 0.5 / len(usable)
    weights.update({name: challenger_weight for name in usable})
    if task.startswith("direction_"):
        base_values = (base.get("raw_probability") or base.get("calibrated_probability") or {})
        labels = ("up", "down", "flat")
        values = [float(base_values.get(label, 0.0)) for label in labels]
        challenger_values = [[float(row) for row in usable[name]["raw_prediction"][:3]] for name in usable]
        combined = [weights["tabular_primary"] * value + sum(challenger_weight * row[index] for row in challenger_values) for index, value in enumerate(values)]
        total = sum(combined) or 1.0
        combined = [value / total for value in combined]
        disagreement = max((max(row[index] for row in challenger_values) - min(row[index] for row in challenger_values) for index in range(3)), default=0.0)
        return {label: value for label, value in zip(labels, combined)}, weights, min(1.0, disagreement)
    if task == "return_20d":
        base_values = [float(base.get(key, 0.0)) for key in ("p10", "p50", "p90")]
        challenger_values = [[float(row[index]) for index in range(3)] for name in usable for row in [usable[name]["raw_prediction"]]]
        combined = [weights["tabular_primary"] * value + sum(challenger_weight * row[index] for row in challenger_values) for index, value in enumerate(base_values)]
        disagreement = max((max(row[index] for row in challenger_values) - min(row[index] for row in challenger_values) for index in range(3)), default=0.0)
        return {key: value for key, value in zip(("p10", "p50", "p90"), combined)}, weights, min(1.0, disagreement)
    base_value = float((base.get("calibrated_probability") or base.get("raw_probability") or 0.0))
    challenger_values = [float(usable[name]["raw_prediction"][0]) for name in usable]
    combined = weights["tabular_primary"] * base_value + sum(challenger_weight * value for value in challenger_values)
    disagreement = max(challenger_values) - min(challenger_values) if challenger_values else 0.0
    return {"probability": combined}, weights, min(1.0, disagreement)


def _predict(package: dict, sample: TrainingSample) -> tuple[dict, float | None]:
    if package.get("data_tier") != "research_pit" or package.get("deployment_ready"):
        raise ValueError("model package is not research-only")
    vector = [[float(sample.features.get(name, 0.0)) for name in package["feature_order"]]]
    kind = package["kind"]
    if kind == "constant_risk":
        raw = float(package["probability"])
        calibrated = package["calibrator"].predict_many([raw])[0]
        return _risk_payload(raw, calibrated), _risk_disagreement(package.get("comparator"), vector, raw)
    if kind == "risk_classifier":
        estimator = package["estimator"]
        classes = list(estimator.classes_)
        row = estimator.predict_proba(vector)[0]
        raw = float(row[classes.index(1)] if 1 in classes else row[0])
        calibrated = package["calibrator"].predict_many([raw])[0]
        return _risk_payload(raw, calibrated), _risk_disagreement(package.get("comparator"), vector, raw)
    if kind in {"constant-class", "random"}:
        raw = dict(package["class_probabilities"])
        return {"raw_probability": raw, "calibrated_probability": _calibrate_direction(raw, package["calibrators"])}, _direction_disagreement(package.get("comparator"), sample, vector, raw)
    if kind in {"index-direction", "momentum"}:
        feature = "benchmark_ret_20d" if kind == "index-direction" else "ret_5d"
        value = float(sample.features.get(feature, 0.0))
        target = "up" if value > 0.002 else "down" if value < -0.002 else "flat"
        raw = {label: 0.8 if label == target else 0.1 for label in CLASSES}
        return {"raw_probability": raw, "calibrated_probability": _calibrate_direction(raw, package["calibrators"])}, _direction_disagreement(package.get("comparator"), sample, vector, raw)
    if kind == "direction_classifier":
        estimator = package["estimator"]
        values = estimator.predict_proba(vector)[0]
        classes = [str(value) if str(value) in CLASSES else CLASSES[int(value)] for value in estimator.classes_]
        raw = {label: 0.0 for label in CLASSES}
        raw.update({label: float(value) for label, value in zip(classes, values)})
        return {"raw_probability": raw, "calibrated_probability": _calibrate_direction(raw, package["calibrators"])}, _direction_disagreement(package.get("comparator"), sample, vector, raw)
    if kind == "constant_quantiles":
        values = package["quantiles"]
    elif kind == "return_quantile":
        values = sorted(float(model.predict(vector)[0]) for model in package["estimators"])
    else:
        raise ValueError(f"unsupported research artifact kind:{kind}")
    return {
        "p10": values[0], "p50": values[1], "p90": values[2]
    }, _return_disagreement(package.get("comparator"), vector, float(values[1]))


def _predict_fallback(package: dict, sample: TrainingSample) -> tuple[dict, float | None]:
    component = package.get("comparator")
    if not component:
        raise ValueError("research fallback component unavailable")
    vector = [[float(sample.features.get(name, 0.0)) for name in package["feature_order"]]]
    kind = component["kind"]
    if kind == "constant_risk":
        probability = float(component["probability"])
        return _risk_payload(probability, probability), None
    if kind == "risk_classifier":
        estimator = component["estimator"]
        classes = list(estimator.classes_)
        row = estimator.predict_proba(vector)[0]
        probability = float(row[classes.index(1)] if 1 in classes else row[0])
        return _risk_payload(probability, probability), None
    if kind in {"constant-class", "random"}:
        values = dict(component["class_probabilities"])
        return {"raw_probability": values, "calibrated_probability": values}, None
    if kind in {"index-direction", "momentum"}:
        feature = "benchmark_ret_20d" if kind == "index-direction" else "ret_5d"
        value = float(sample.features.get(feature, 0.0))
        target = "up" if value > 0.002 else "down" if value < -0.002 else "flat"
        values = {label: 0.8 if label == target else 0.1 for label in CLASSES}
        return {"raw_probability": values, "calibrated_probability": values}, None
    if kind == "direction_classifier":
        estimator = component["estimator"]
        values = estimator.predict_proba(vector)[0]
        classes = [str(value) if str(value) in CLASSES else CLASSES[int(value)] for value in estimator.classes_]
        probabilities = {label: 0.0 for label in CLASSES}
        probabilities.update({label: float(value) for label, value in zip(classes, values)})
        return {"raw_probability": probabilities, "calibrated_probability": probabilities}, None
    if kind == "constant_quantiles":
        values = component["quantiles"]
    elif kind == "return_quantile":
        values = sorted(float(model.predict(vector)[0]) for model in component["estimators"])
    else:
        raise ValueError(f"unsupported fallback component:{kind}")
    return {"p10": values[0], "p50": values[1], "p90": values[2]}, None


def _risk_payload(raw: float, calibrated: float) -> dict:
    level = "high" if calibrated >= 0.6 else "medium" if calibrated >= 0.35 else "low"
    return {"raw_probability": raw, "calibrated_probability": calibrated, "risk_level": level, "threshold_drawdown": -0.08}


def _calibrate_direction(raw: dict[str, float], calibrators: dict) -> dict[str, float]:
    adjusted = {
        label: calibrators[label].predict_many([raw[label]])[0] if label in calibrators else raw[label]
        for label in CLASSES
    }
    total = sum(max(0.0, value) for value in adjusted.values())
    return {label: max(0.0, adjusted[label]) / total for label in CLASSES}


def _risk_disagreement(component: dict | None, vector: list[list[float]], selected: float) -> float | None:
    if not component:
        return None
    if component["kind"] == "constant_risk":
        other = float(component["probability"])
    else:
        estimator = component["estimator"]
        classes = list(estimator.classes_)
        row = estimator.predict_proba(vector)[0]
        other = float(row[classes.index(1)] if 1 in classes else row[0])
    return min(1.0, abs(selected - other))


def _direction_disagreement(component: dict | None, sample: TrainingSample, vector: list[list[float]], selected: dict[str, float]) -> float | None:
    if not component:
        return None
    kind = component["kind"]
    if kind in {"constant-class", "random"}:
        other = dict(component["class_probabilities"])
    elif kind in {"index-direction", "momentum"}:
        feature = "benchmark_ret_20d" if kind == "index-direction" else "ret_5d"
        value = float(sample.features.get(feature, 0.0))
        target = "up" if value > 0.002 else "down" if value < -0.002 else "flat"
        other = {label: 0.8 if label == target else 0.1 for label in CLASSES}
    else:
        estimator = component["estimator"]
        values = estimator.predict_proba(vector)[0]
        classes = [str(value) if str(value) in CLASSES else CLASSES[int(value)] for value in estimator.classes_]
        other = {label: 0.0 for label in CLASSES}
        other.update({label: float(value) for label, value in zip(classes, values)})
    return min(1.0, 0.5 * sum(abs(selected[label] - other[label]) for label in CLASSES))


def _return_disagreement(component: dict | None, vector: list[list[float]], selected_p50: float) -> float | None:
    if not component:
        return None
    if component["kind"] == "constant_quantiles":
        other = float(component["quantiles"][1])
    elif component["kind"] == "return_quantile":
        values = sorted(float(model.predict(vector)[0]) for model in component["estimators"])
        other = values[1]
    else:
        return None
    return abs(selected_p50 - other)


def _abstain_reasons(
    *, task: str, sample: TrainingSample, package: dict, disagreement: float | None,
    cache_state: str, provider_conflict: bool,
) -> list[str]:
    reasons: list[str] = []
    if sample.feature_coverage < 0.85:
        reasons.append("feature_coverage_below_85pct")
    if cache_state in {"expired", "unavailable"}:
        reasons.append(f"cache_{cache_state}")
    if provider_conflict:
        reasons.append("provider_conflict")
    bounds = package.get("feature_bounds", {})
    if bounds:
        outside = sum(
            float(sample.features.get(name, 0.0)) < float(interval[0])
            or float(sample.features.get(name, 0.0)) > float(interval[1])
            for name, interval in bounds.items()
        )
        if outside / len(bounds) > 0.20:
            reasons.append("out_of_distribution_feature_ratio_above_20pct")
    if disagreement is not None:
        if task.startswith("direction_") and disagreement > 0.30:
            reasons.append("direction_total_variation_disagreement_above_0.30")
        elif task == "drawdown_20d" and disagreement > 0.25:
            reasons.append("risk_probability_disagreement_above_0.25")
        elif task == "return_20d" and disagreement > 0.05:
            reasons.append("return_p50_disagreement_above_0.05")
    return reasons


def _has_provider_conflict(index: dict, symbol: str) -> bool:
    return any(
        item.get("symbol") == symbol and item.get("provider_conflict")
        for item in index.get("quality_reports", [])
    )


def _restore_maps(row: dict) -> dict:
    value = dict(row)
    for key in ("features", "labels"):
        if isinstance(value.get(key), str):
            value[key] = json.loads(value[key])
    return value


if __name__ == "__main__":
    raise SystemExit(main())
