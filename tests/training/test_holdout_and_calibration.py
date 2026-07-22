from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from investment_research.training.calibration import (
    CalibrationMethod,
    TimeOutOfFoldCalibrator,
    compare_calibrators,
)
from investment_research.training.models import (
    InstrumentType,
    LabelSet,
    Market,
    TrainingSample,
)
from investment_research.training.validation import build_final_holdout_split


def _sample(index: int) -> TrainingSample:
    day = date(2024, 1, 1) + timedelta(days=index)
    return TrainingSample(
        symbol="TEST",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        as_of_date=day,
        as_of_time=datetime.combine(day, datetime.min.time(), timezone.utc),
        feature_cutoff=datetime.combine(day, datetime.min.time(), timezone.utc),
        feature_version="v2",
        data_version="pit",
        features={"x": float(index)},
        labels=LabelSet(
            symbol="TEST",
            as_of_date=day,
            future_max_drawdown_20d=-0.1 if index % 2 else -0.01,
            label_end=day + timedelta(days=20),
        ),
    )


def test_final_holdout_reserves_12m_and_nested_6m() -> None:
    samples = [_sample(index) for index in range(400)]
    split = build_final_holdout_split(samples)
    assert len(split.holdout_12m) == 252
    assert len(split.stress_6m) == 126
    assert all(
        item.labels.label_end < split.holdout_start for item in split.development
    )


def test_calibrator_rejects_in_sample_provenance_and_compares_methods() -> None:
    with pytest.raises(ValueError):
        TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit(
            [0.2, 0.8], [0, 1], prediction_fold_ids=["a", "a"], training_fold_ids=["a"]
        )
    selected, reports = compare_calibrators(
        calibration_scores=[0.05, 0.2, 0.3, 0.7, 0.8, 0.95],
        calibration_labels=[0, 0, 0, 1, 1, 1],
        prediction_fold_ids=["validation"] * 6,
        training_fold_ids=["training"],
    )
    assert selected.method in set(CalibrationMethod)
    assert {item.method for item in reports} == set(CalibrationMethod)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -float("inf")])
def test_calibrator_rejects_non_finite_scores(score: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit(
            [0.1, score, 0.9],
            [0, 0, 1],
            prediction_fold_ids=["validation"] * 3,
            training_fold_ids=["training"],
        )


def test_platt_calibration_handles_extreme_oof_probabilities() -> None:
    calibrator = TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit(
        [0.0, 1e-300, 1e-12, 1.0 - 1e-12, 1.0],
        [0, 0, 0, 1, 1],
        prediction_fold_ids=["validation"] * 5,
        training_fold_ids=["training"],
    )
    predictions = calibrator.predict_many([0.0, 0.5, 1.0])
    assert all(0.0 <= value <= 1.0 for value in predictions)
