from datetime import date, timedelta

from investment_research.training.validation import build_walk_forward_folds


def test_purged_walk_forward_leaves_full_label_horizon() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(80)]
    folds = build_walk_forward_folds(
        dates,
        train_window_days=30,
        validation_window_days=10,
        prediction_horizon_days=20,
    )
    assert folds
    first = folds[0]
    assert (first.validation_start - first.train_end).days >= 21
    assert first.purge_days == first.embargo_days == first.label_horizon_days == 20
