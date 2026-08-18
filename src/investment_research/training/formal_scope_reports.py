"""Derived approval evidence for one formal training scope.

The formal runner may only publish evidence it actually calculated from the
frozen PIT dataset.  When a prerequisite is absent (for example, a verified
cost schedule or a feature-ablation executor), this module records a concrete
``blocked`` reason instead of a misleading ``pending`` placeholder.
"""
from __future__ import annotations

from collections import Counter
from math import log
from statistics import mean
from typing import Any, Iterable, Mapping


def build_formal_scope_reports(
    *,
    dataset_manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    samples: Iterable[Any],
) -> dict[str, dict[str, Any]]:
    """Build every required formal approval report from immutable inputs.

    This intentionally does not manufacture data for the two evaluations that
    require separately governed inputs: feature ablation and trading-cost
    simulation.  They are explicit blockers until their own input contracts
    are supplied.
    """
    values = list(samples)
    task = str(plan["scope"]).split(":")[-1]
    selected = str(result.get("selected_candidate", "unavailable"))
    candidates = list(result.get("candidates", []))
    selected_payload = next(
        (item for item in candidates if isinstance(item, Mapping) and item.get("name") == selected),
        {},
    )
    feature_coverages = [float(getattr(item, "feature_coverage", 0.0) or 0.0) for item in values]
    core_coverages = [
        float(getattr(item, "core_feature_coverage", 0.0) or 0.0)
        for item in values
    ]
    data_issues = Counter(
        issue
        for item in values
        for issue in getattr(item, "data_issues", [])
    )
    event_states = Counter(str(getattr(item, "event_coverage_status", "unknown")) for item in values)
    holdout = _task_metrics(task, result, stage="holdout")
    stress = _task_metrics(task, result, stage="stress")
    industry_metrics = _industry_metrics(selected_payload, result)
    return {
        "dataset_manifest": dict(dataset_manifest),
        "leakage_audit": {
            "status": "catalog_verified",
            "dataset_hash": dataset_manifest["dataset_hash"],
            "manifest_leakage_report_hash": dataset_manifest["leakage_report_hash"],
            "passed": True,
        },
        "fold": {
            "status": "evaluated",
            "fold_hash": result["fold_hash"],
            "candidate_count": len(candidates),
            "purge_sessions": plan["embargo_sessions"],
            "embargo_sessions": plan["embargo_sessions"],
        },
        "feature_coverage": {
            "status": "evaluated",
            "sample_count": len(values),
            "mean_feature_coverage": _average(feature_coverages),
            "mean_core_feature_coverage": _average(core_coverages),
            "data_issue_counts": dict(sorted(data_issues.items())),
            "event_coverage_counts": dict(sorted(event_states.items())),
        },
        "ablation": {
            "status": "blocked",
            "reason": "formal_feature_group_ablation_requires_explicit_executor",
            "required_feature_groups": [
                "price", "volume", "volatility", "market_regime",
                "industry", "data_quality",
            ],
        },
        "calibration": {
            "status": "evaluated_time_oof_only",
            "selected_candidate": selected,
            "method": selected_payload.get("calibration_method"),
            "selected_oof_metrics": _candidate_summary(selected_payload),
        },
        "market_industry_regime": {
            "status": "evaluated" if industry_metrics is not None else "blocked",
            "market": dataset_manifest["market"],
            "regime_metrics": selected_payload.get("regime_metrics", {}),
            "industry_status": "evaluated" if industry_metrics is not None else "blocked",
            "industry_rank_ic": industry_metrics or {},
            "industry_reason": None if industry_metrics is not None else "selected_candidate_did_not_publish_industry_metrics",
        },
        "holdout_12m": {
            "status": "evaluated_once",
            "selected_candidate": selected,
            "metrics": holdout,
        },
        "stress_6m": {
            "status": "evaluated_once",
            "selected_candidate": selected,
            "metrics": stress,
        },
        "cost_liquidity": {
            "status": "blocked",
            "reason": "verified_market_cost_schedule_not_attached_to_formal_dataset",
            "required_inputs": ["TradingCostSchedule", "tradeability_state", "liquidity_constraint"],
        },
        "artifact_hash": {
            "status": "blocked",
            "artifact_kind": "candidate_evaluation",
            "candidate_result_hash": _canonical_hash(result),
            "deployable_artifacts_persisted": False,
            "reason": "formal_model_artifact_serializer_not_attached",
        },
        "approval": {
            "status": "blocked",
            "reason": "candidate_evidence_only",
            "blocking_reports": ["ablation", "market_industry_regime", "cost_liquidity", "artifact_hash"],
        },
    }


def _task_metrics(task: str, result: Mapping[str, Any], *, stage: str) -> dict[str, Any]:
    if task == "drawdown_20d":
        scores = _numbers(result.get(f"{stage}_scores", []))
        labels = [int(value) for value in result.get(f"{stage}_labels", [])]
        return {
            "sample_count": len(labels),
            "brier": _brier(scores, labels),
            "mean_score": _average(scores),
            "alert_precision": _alert_precision(scores, labels),
        }
    if task.startswith("direction_"):
        probabilities = list(result.get(f"{stage}_probabilities", []))
        labels = [str(value) for value in result.get(f"{stage}_labels", [])]
        predicted = [max(row, key=row.get) for row in probabilities if isinstance(row, Mapping) and row]
        aligned = min(len(labels), len(predicted), len(probabilities))
        return {
            "sample_count": aligned,
            "accuracy": _ratio(sum(labels[index] == predicted[index] for index in range(aligned)), aligned),
            "log_loss": _multiclass_log_loss(probabilities[:aligned], labels[:aligned]),
            "class_counts": dict(sorted(Counter(labels[:aligned]).items())),
        }
    quantiles = list(result.get(f"{stage}_quantiles", []))
    targets = _numbers(result.get(f"{stage}_targets", []))
    aligned = min(len(quantiles), len(targets))
    p50 = [float(row[1]) for row in quantiles[:aligned] if isinstance(row, (list, tuple)) and len(row) >= 3]
    aligned = min(aligned, len(p50))
    intervals = quantiles[:aligned]
    pinball = _quantile_pinball(intervals, targets[:aligned])
    return {
        "sample_count": aligned,
        "p50_mae": _average([abs(targets[index] - p50[index]) for index in range(aligned)]),
        "mae": _average([abs(targets[index] - p50[index]) for index in range(aligned)]),
        "pinball_loss": pinball,
        "direction_accuracy": _ratio(sum((targets[index] >= 0) == (p50[index] >= 0) for index in range(aligned)), aligned),
        "interval_coverage": _ratio(sum(float(row[0]) <= targets[index] <= float(row[2]) for index, row in enumerate(intervals)), aligned),
    }


def _candidate_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    interesting = (
        "brier", "auroc", "ece", "alert_precision", "drawdown_lift",
        "macro_f1", "balanced_accuracy", "log_loss", "mean_pinball_loss",
        "interval_coverage", "p50_mae", "direction_accuracy", "spearman_ic",
    )
    return {key: value[key] for key in interesting if key in value}


def _industry_metrics(selected_payload: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Expose industry stability when the evaluator actually computed it.

    An empty mapping is not evidence of stability, so it remains a blocked
    report unless a candidate published at least one industry bucket.
    """
    for payload in (
        selected_payload,
        result.get("holdout_metrics", {}) if isinstance(result.get("holdout_metrics"), Mapping) else {},
        result.get("oof_metrics", {}) if isinstance(result.get("oof_metrics"), Mapping) else {},
    ):
        value = payload.get("industry_rank_ic")
        if isinstance(value, Mapping) and value:
            return dict(value)
    return None


def _numbers(values: Iterable[Any]) -> list[float]:
    return [float(value) for value in values]


def _average(values: list[float]) -> float | None:
    return None if not values else float(mean(values))


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if not denominator else numerator / denominator


def _brier(scores: list[float], labels: list[int]) -> float | None:
    aligned = min(len(scores), len(labels))
    return _average([(scores[index] - labels[index]) ** 2 for index in range(aligned)])


def _alert_precision(scores: list[float], labels: list[int], *, threshold: float = 0.5) -> float | None:
    positives = [index for index, value in enumerate(scores[:len(labels)]) if value >= threshold]
    return _ratio(sum(labels[index] == 1 for index in positives), len(positives))


def _multiclass_log_loss(probabilities: list[Any], labels: list[str]) -> float | None:
    losses = []
    for row, label in zip(probabilities, labels):
        if not isinstance(row, Mapping):
            continue
        losses.append(-log(max(float(row.get(label, 0.0)), 1e-12)))
    return _average(losses)


def _quantile_pinball(quantiles: list[Any], targets: list[float]) -> float | None:
    losses: list[float] = []
    for row, target in zip(quantiles, targets):
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        for prediction, quantile in zip(row[:3], (0.1, 0.5, 0.9)):
            error = float(target) - float(prediction)
            losses.append(max(quantile * error, (quantile - 1.0) * error))
    return _average(losses)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    from hashlib import sha256
    import json

    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
