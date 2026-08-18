from datetime import date

from investment_research.training.incremental_rebuild import DataRevisionChange, plan_incremental_rebuild


def test_revision_expands_features_backwards_and_labels_separately() -> None:
    plan = plan_incremental_rebuild(
        [DataRevisionChange("daily_bars_qfq", "000001", date(2026, 8, 10), date(2026, 8, 11), "old", "new")],
        feature_lookback_sessions=60,
        label_horizons=(60, 120, 240),
        snapshot_ids=("snapshot-old",),
        model_versions=("model-old",),
    )
    assert plan.feature_ranges["000001"] == (date(2026, 8, 10), date(2026, 10, 10))
    assert plan.label_ranges["000001"] == (date(2025, 12, 13), date(2026, 8, 11))
    assert plan.invalidated_snapshot_ids == ("snapshot-old",)


def test_revision_uses_verified_trading_calendar_for_session_windows() -> None:
    calendar = tuple(date(2026, 8, day) for day in (3, 4, 5, 6, 7, 10, 11))
    plan = plan_incremental_rebuild(
        [DataRevisionChange("daily_bars_raw", "000001", date(2026, 8, 10), date(2026, 8, 10), None, "new")],
        feature_lookback_sessions=2,
        label_horizons=(3,),
        trading_dates=calendar,
    )
    assert plan.feature_ranges["000001"] == (date(2026, 8, 10), date(2026, 8, 11))
    assert plan.label_ranges["000001"] == (date(2026, 8, 5), date(2026, 8, 10))
