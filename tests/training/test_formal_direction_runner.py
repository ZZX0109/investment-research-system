from investment_research.training.formal_direction_runner import _calibrate_multiclass, _ensemble, _metrics
import pytest


def test_direction_runner_uses_probability_distributions_and_time_oof_calibration() -> None:
    raw = [
        {"up": 0.8, "down": 0.1, "flat": 0.1},
        {"up": 0.1, "down": 0.8, "flat": 0.1},
        {"up": 0.1, "down": 0.1, "flat": 0.8},
        {"up": 0.7, "down": 0.2, "flat": 0.1},
        {"up": 0.2, "down": 0.7, "flat": 0.1},
        {"up": 0.1, "down": 0.2, "flat": 0.7},
    ]
    labels = ["up", "down", "flat", "up", "down", "flat"]
    calibrated = _calibrate_multiclass(raw, labels, apply_probabilities=raw)
    assert all(abs(sum(item.values()) - 1.0) < 1e-8 for item in calibrated)
    metrics = _metrics("candidate", raw, calibrated, labels, "fold")
    assert metrics.macro_f1 >= 0
    assert metrics.log_loss >= 0


def test_direction_time_oof_ensemble_uses_candidate_probability_metrics() -> None:
    labels = ["up", "down", "flat"]
    first = [
        {"up": 0.8, "down": 0.1, "flat": 0.1},
        {"up": 0.1, "down": 0.8, "flat": 0.1},
        {"up": 0.1, "down": 0.1, "flat": 0.8},
    ]
    second = [
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        {"up": 0.3, "down": 0.5, "flat": 0.2},
        {"up": 0.2, "down": 0.3, "flat": 0.5},
    ]
    ensemble = _ensemble({"first": first, "second": second}, labels)
    assert len(ensemble) == len(labels)
    assert all(abs(sum(row.values()) - 1.0) < 1e-12 for row in ensemble)


def test_direction_calibration_requires_fold_id_per_oof_prediction() -> None:
    rows = [
        {"up": 0.8, "down": 0.1, "flat": 0.1},
        {"up": 0.1, "down": 0.8, "flat": 0.1},
        {"up": 0.1, "down": 0.1, "flat": 0.8},
    ]
    with pytest.raises(ValueError, match="fold identifiers"):
        _calibrate_multiclass(rows, ["up", "down", "flat"], apply_probabilities=rows, prediction_fold_ids=["fold-1"])
