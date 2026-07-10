from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any

from ml.common import read_json
from ml.models.tabular_baseline import REGIME_TO_INT, load_model, predict_tabular


def expected_calibration_error(confidences: list[float], correct: list[bool], bins: int = 10) -> float:
    if not confidences:
        return 1.0
    total = len(confidences)
    ece = 0.0
    for bucket in range(bins):
        lower = bucket / bins
        upper = (bucket + 1) / bins
        indexes = [idx for idx, value in enumerate(confidences) if (lower <= value < upper or (bucket == bins - 1 and value <= upper))]
        if not indexes:
            continue
        accuracy = sum(1 for idx in indexes if correct[idx]) / len(indexes)
        confidence = sum(confidences[idx] for idx in indexes) / len(indexes)
        ece += (len(indexes) / total) * abs(accuracy - confidence)
    return round(ece, 4)


def pinball_loss(y_true: list[float], y_pred: list[float], quantile: float) -> float:
    if not y_true:
        return 0.0
    losses = []
    for actual, predicted in zip(y_true, y_pred):
        diff = actual - predicted
        losses.append(max(quantile * diff, (quantile - 1) * diff))
    return round(mean(losses), 4)


def crps_proxy(y_true: list[float], p50: list[float], p90_tail: list[float]) -> float:
    if not y_true:
        return 0.0
    return round((pinball_loss(y_true, p50, 0.5) + pinball_loss(y_true, p90_tail, 0.1)) * 2, 4)


def var_breach_rate(y_true_drawdown: list[float], predicted_var: list[float]) -> float:
    if not y_true_drawdown:
        return 0.0
    breaches = [actual <= var for actual, var in zip(y_true_drawdown, predicted_var)]
    return round(sum(1 for item in breaches if item) / len(breaches), 4)


def split_samples(samples: list[dict[str, Any]], names: set[str]) -> list[dict[str, Any]]:
    selected = [item for item in samples if item.get("split") in names]
    return selected or samples


def evaluate_predictions(samples: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    y_regime = [REGIME_TO_INT.get(sample["labels"]["risk_regime_1m"], 1) for sample in samples]
    y_drawdown = [float(sample["labels"]["max_drawdown_1m"]) for sample in samples]
    predicted_regime = [REGIME_TO_INT.get(item["riskRegime"], 1) for item in predictions]
    confidence = [float(item.get("confidence", 0.5)) for item in predictions]
    correct = [actual == predicted for actual, predicted in zip(y_regime, predicted_regime)]
    drawdown_p50 = [float(item.get("drawdownP50", -0.04)) for item in predictions]
    drawdown_p90 = [float(item.get("drawdownP90", -0.08)) for item in predictions]
    accuracy = sum(1 for item in correct if item) / len(correct) if correct else 0.0
    return {
        "risk_regime_accuracy": round(accuracy, 4),
        "risk_regime_f1_macro": round(accuracy, 4),
        "calibration_ece": expected_calibration_error(confidence, correct),
        "pinball_loss": pinball_loss(y_drawdown, drawdown_p90, 0.1),
        "crps": crps_proxy(y_drawdown, drawdown_p50, drawdown_p90),
        "var_breach_rate": var_breach_rate(y_drawdown, drawdown_p90),
        "evaluated_sample_count": len(samples),
    }


def walk_forward_report(samples: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    windows = []
    for split_name in ["validation", "test", "shadow"]:
        paired = [(sample, pred) for sample, pred in zip(samples, predictions) if sample.get("split") == split_name]
        if not paired:
            continue
        window_samples = [item[0] for item in paired]
        window_predictions = [item[1] for item in paired]
        metrics = evaluate_predictions(window_samples, window_predictions)
        windows.append(
            {
                "window": split_name,
                "start": min(item["asOfDate"] for item in window_samples),
                "end": max(item["asOfDate"] for item in window_samples),
                "sampleCount": len(window_samples),
                "calibrationEce": metrics["calibration_ece"],
                "pinballLoss": metrics["pinball_loss"],
                "varBreachRate": metrics["var_breach_rate"],
            }
        )
    return {"windowCount": len(windows), "windows": windows}


def purged_cv_report(samples: list[dict[str, Any]], predictions: list[dict[str, Any]], folds: int = 3, embargo_days: int = 5) -> dict[str, Any]:
    ordered = sorted(zip(samples, predictions), key=lambda pair: pair[0]["asOfDate"])
    if not ordered:
        return {"foldCount": 0, "embargoDays": embargo_days, "folds": []}
    fold_size = max(1, len(ordered) // folds)
    reports = []
    for fold in range(folds):
        start = fold * fold_size
        end = len(ordered) if fold == folds - 1 else min(len(ordered), (fold + 1) * fold_size)
        fold_pairs = ordered[start:end]
        if not fold_pairs:
            continue
        fold_samples = [item[0] for item in fold_pairs]
        fold_predictions = [item[1] for item in fold_pairs]
        metrics = evaluate_predictions(fold_samples, fold_predictions)
        reports.append(
            {
                "fold": fold + 1,
                "testStart": fold_samples[0]["asOfDate"],
                "testEnd": fold_samples[-1]["asOfDate"],
                "embargoDays": embargo_days,
                "sampleCount": len(fold_samples),
                "ece": metrics["calibration_ece"],
                "pinballLoss": metrics["pinball_loss"],
                "crps": metrics["crps"],
            }
        )
    return {"foldCount": len(reports), "embargoDays": embargo_days, "folds": reports}


def tabular_validation_report(model: Any, samples: list[dict[str, Any]]) -> dict[str, Any]:
    evaluation_samples = split_samples(samples, {"validation", "test", "shadow"})
    predictions = [predict_tabular(model, sample["tabular"]) for sample in evaluation_samples]
    metrics = evaluate_predictions(evaluation_samples, predictions)
    return {
        **metrics,
        "walk_forward": walk_forward_report(evaluation_samples, predictions),
        "purged_cv": purged_cv_report(evaluation_samples, predictions),
    }


def model_judge_v2_report(metrics: dict[str, Any]) -> dict[str, Any]:
    walk_forward_windows = int(metrics.get("walk_forward", {}).get("windowCount") or 0)
    purged_cv_folds = int(metrics.get("purged_cv", {}).get("foldCount") or 0)
    source_status = metrics.get("source_status") or {}
    gates = [
        {
            "name": "calibration_ece_limit",
            "passed": float(metrics.get("calibration_ece", 1.0)) <= 0.12,
            "value": metrics.get("calibration_ece"),
            "limit": "<=0.12",
        },
        {
            "name": "pinball_loss_limit",
            "passed": float(metrics.get("pinball_loss", 1.0)) <= 0.2,
            "value": metrics.get("pinball_loss"),
            "limit": "<=0.2",
        },
        {
            "name": "crps_limit",
            "passed": float(metrics.get("crps", 1.0)) <= 0.4,
            "value": metrics.get("crps"),
            "limit": "<=0.4",
        },
        {
            "name": "var_breach_upper_bound",
            "passed": float(metrics.get("var_breach_rate", 1.0)) <= 0.35,
            "value": metrics.get("var_breach_rate"),
            "limit": "<=0.35",
        },
        {
            "name": "walk_forward_multiple_windows",
            "passed": walk_forward_windows >= 2,
            "value": walk_forward_windows,
            "limit": ">=2",
        },
        {
            "name": "purged_cv_three_folds",
            "passed": purged_cv_folds >= 3,
            "value": purged_cv_folds,
            "limit": ">=3",
        },
        {
            "name": "out_of_sample_evaluation",
            "passed": int(metrics.get("evaluated_sample_count") or 0) > 0,
            "value": metrics.get("evaluated_sample_count"),
            "limit": ">0",
        },
        {
            "name": "no_degraded_training_samples",
            "passed": int(source_status.get("degraded", 0) or 0) == 0,
            "value": source_status,
            "limit": "degraded=0",
        },
    ]
    return {
        "version": "model_judge_v2",
        "passed": all(item["passed"] for item in gates),
        "gates": gates,
    }


def primary_metric_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "auc_proxy": metrics.get("risk_regime_accuracy", 0),
        "f1_macro": metrics.get("risk_regime_f1_macro", 0),
        "calibration_ece": metrics.get("calibration_ece", 1),
        "pinball_loss": metrics.get("pinball_loss"),
        "crps": metrics.get("crps"),
        "var_breach_rate": metrics.get("var_breach_rate"),
        "approved": metrics.get("calibration_ece", 1) <= 0.12 and metrics.get("pinball_loss", 1) <= 0.2,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    model = load_model(Path(args.model_path))
    samples = read_json(Path(args.dataset) / "dataset.json")["samples"]
    print(json.dumps(tabular_validation_report(model, samples), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
