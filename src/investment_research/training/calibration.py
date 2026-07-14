from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import log


class CalibrationMethod(str, Enum):
    PLATT = "platt"
    ISOTONIC = "isotonic"
    BETA = "beta"


@dataclass(frozen=True)
class CalibrationResult:
    method: CalibrationMethod
    brier: float
    ece: float
    sample_count: int


class TimeOutOfFoldCalibrator:
    """Calibrator that refuses in-sample scores and supports three methods."""

    def __init__(self, method: CalibrationMethod) -> None:
        self.method = method
        self._model = None

    def fit(
        self,
        scores: list[float],
        labels: list[int],
        *,
        prediction_fold_ids: list[str],
        training_fold_ids: list[str],
    ) -> "TimeOutOfFoldCalibrator":
        if (
            not scores
            or len(scores) != len(labels)
            or len(scores) != len(prediction_fold_ids)
        ):
            raise ValueError("calibration inputs must be non-empty and aligned")
        if set(prediction_fold_ids) & set(training_fold_ids):
            raise ValueError("calibration scores must be strictly time-out-of-fold")
        clipped = [_clip(value) for value in scores]
        if self.method == CalibrationMethod.ISOTONIC:
            from sklearn.isotonic import IsotonicRegression

            self._model = IsotonicRegression(out_of_bounds="clip").fit(clipped, labels)
        else:
            from sklearn.linear_model import LogisticRegression

            matrix = (
                [[log(value), -log(1.0 - value)] for value in clipped]
                if self.method == CalibrationMethod.BETA
                else [[_logit(value)] for value in clipped]
            )
            self._model = LogisticRegression().fit(matrix, labels)
        return self

    def predict_many(self, scores: list[float]) -> list[float]:
        if self._model is None:
            raise ValueError("calibrator is not fitted")
        clipped = [_clip(value) for value in scores]
        if self.method == CalibrationMethod.ISOTONIC:
            return [float(value) for value in self._model.predict(clipped)]
        matrix = (
            [[log(value), -log(1.0 - value)] for value in clipped]
            if self.method == CalibrationMethod.BETA
            else [[_logit(value)] for value in clipped]
        )
        return [float(row[1]) for row in self._model.predict_proba(matrix)]


def compare_calibrators(
    *,
    calibration_scores: list[float],
    calibration_labels: list[int],
    prediction_fold_ids: list[str],
    training_fold_ids: list[str],
) -> tuple[TimeOutOfFoldCalibrator, list[CalibrationResult]]:
    results: list[tuple[TimeOutOfFoldCalibrator, CalibrationResult]] = []
    for method in CalibrationMethod:
        calibrator = TimeOutOfFoldCalibrator(method).fit(
            calibration_scores,
            calibration_labels,
            prediction_fold_ids=prediction_fold_ids,
            training_fold_ids=training_fold_ids,
        )
        values = calibrator.predict_many(calibration_scores)
        results.append(
            (
                calibrator,
                CalibrationResult(
                    method,
                    _brier(values, calibration_labels),
                    _ece(values, calibration_labels),
                    len(values),
                ),
            )
        )
    results.sort(key=lambda item: (item[1].brier, item[1].ece))
    return results[0][0], [item[1] for item in results]


def _clip(value: float) -> float:
    return min(1.0 - 1e-6, max(1e-6, float(value)))


def _logit(value: float) -> float:
    return log(value / (1.0 - value))


def _brier(values: list[float], labels: list[int]) -> float:
    return sum((value - label) ** 2 for value, label in zip(values, labels)) / len(
        values
    )


def _ece(values: list[float], labels: list[int], bins: int = 10) -> float:
    total = len(values)
    result = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [
            (value, label)
            for value, label in zip(values, labels)
            if low <= value < high or (index == bins - 1 and value == 1.0)
        ]
        if members:
            confidence = sum(item[0] for item in members) / len(members)
            accuracy = sum(item[1] for item in members) / len(members)
            result += (len(members) / total) * abs(confidence - accuracy)
    return result
