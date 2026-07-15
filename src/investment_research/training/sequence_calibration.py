"""Time-OOF calibration and disagreement controls for sequence ensembles."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from investment_research.training.calibration import CalibrationMethod, TimeOutOfFoldCalibrator


@dataclass(frozen=True)
class EnsembleDecision:
    prediction: Any
    weights: dict[str, float]
    disagreement: float
    abstain: bool
    reasons: list[str]


def fit_direction_calibrators(raw_probabilities: list[dict[str, float]], labels: list[str], fold_ids: list[str], *, training_fold_ids: list[str] = ()) -> dict[str, TimeOutOfFoldCalibrator]:
    if not (len(raw_probabilities) == len(labels) == len(fold_ids)):
        raise ValueError("OOF calibration inputs must align")
    output = {}
    for label in ("up", "down", "flat"):
        target = [int(value == label) for value in labels]
        if len(set(target)) < 2:
            continue
        output[label] = TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit([float(row.get(label, 0.0)) for row in raw_probabilities], target, prediction_fold_ids=fold_ids, training_fold_ids=training_fold_ids)
    return output


def fit_risk_calibrator(raw_probabilities: list[float], labels: list[int], fold_ids: list[str], *, training_fold_ids: list[str] = ()) -> TimeOutOfFoldCalibrator:
    if not (len(raw_probabilities) == len(labels) == len(fold_ids)):
        raise ValueError("OOF calibration inputs must align")
    if len(set(labels)) < 2:
        raise ValueError("risk calibration requires both classes")
    return TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit(raw_probabilities, labels, prediction_fold_ids=fold_ids, training_fold_ids=training_fold_ids)


def inverse_brier_weights(probabilities_by_model: dict[str, list[float]], labels: list[int]) -> dict[str, float]:
    if not probabilities_by_model or not labels:
        raise ValueError("ensemble requires model probabilities and labels")
    scores = {name: sum((float(prob) - label) ** 2 for prob, label in zip(values, labels)) / len(labels) for name, values in probabilities_by_model.items()}
    inverse = {name: 1.0 / max(score, 1e-6) for name, score in scores.items()}
    total = sum(inverse.values())
    return {name: value / total for name, value in inverse.items()}


def weighted_direction_ensemble(probabilities_by_model: dict[str, dict[str, float]], weights: dict[str, float]) -> tuple[dict[str, float], float]:
    labels = ("up", "down", "flat")
    prediction = {label: sum(weights.get(name, 0.0) * float(values.get(label, 0.0)) for name, values in probabilities_by_model.items()) for label in labels}
    total = sum(prediction.values()) or 1.0
    prediction = {label: value / total for label, value in prediction.items()}
    disagreement = max(
        abs(float(probabilities_by_model[left].get(label, 0.0)) - float(probabilities_by_model[right].get(label, 0.0)))
        for left in probabilities_by_model for right in probabilities_by_model if left < right for label in labels
    ) if len(probabilities_by_model) > 1 else 0.0
    return prediction, min(1.0, disagreement)


def decide_with_disagreement(prediction: Any, weights: dict[str, float], disagreement: float, *, threshold: float, reasons: list[str] | None = None) -> EnsembleDecision:
    gating = list(reasons or [])
    if disagreement > threshold:
        gating.append("model_disagreement_above_threshold")
    return EnsembleDecision(prediction=prediction, weights=weights, disagreement=disagreement, abstain=bool(gating), reasons=gating)
