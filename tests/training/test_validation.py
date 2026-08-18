from datetime import date, datetime, timezone

from investment_research.training.models import PreparedPriceBar
from investment_research.training.validation import build_period_walk_forward_folds, build_walk_forward_folds, infer_market_regime


def _reference_bar(trade_date: date, close_value: float, *, symbol: str = "SPY") -> PreparedPriceBar:
    return PreparedPriceBar(
        symbol=symbol,
        trade_date=trade_date,
        close_native=close_value,
        close_normalized=close_value,
        volume=1000.0,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_walk_forward_folds_are_time_ordered_and_non_overlapping() -> None:
    dates = [date(2026, 1, day) for day in range(1, 11)]
    reference = [_reference_bar(day, 100 + index) for index, day in enumerate(dates)]

    folds = build_walk_forward_folds(
        dates,
        train_window_days=4,
        validation_window_days=2,
        step_days=2,
        regime_reference=reference,
    )

    assert len(folds) == 3
    assert folds[0].train_end < folds[0].validation_start
    assert folds[1].train_start > folds[0].train_start
    assert folds[0].regime in {"bull", "bear", "high_vol", "range", "unknown"}


def test_period_walk_forward_folds_keep_period_windows_and_real_horizon_metadata() -> None:
    dates = [date(2020 + index // 4, (index % 4) * 3 + 3, 28) for index in range(40)]
    folds = build_period_walk_forward_folds(
        dates,
        train_periods=8,
        validation_periods=2,
        purge_periods=1,
        embargo_periods=1,
        label_horizon_days=960,
    )
    assert folds
    assert folds[0].label_horizon_days == 960
    assert folds[0].purge_days == 1
    assert folds[0].embargo_days == 1
    assert folds[0].train_end < folds[0].validation_start


def test_high_vol_regime_is_detected_before_bear_drawdown() -> None:
    dates = [date(2026, 1, day) for day in range(1, 31)]
    closes = [
        *[100.0 + (index * 0.1) for index in range(20)],
        110.0,
        96.0,
        112.0,
        91.0,
        115.0,
        89.0,
        118.0,
        86.0,
        121.0,
        84.0,
    ]
    reference = [_reference_bar(day, close) for day, close in zip(dates, closes)]

    regime = infer_market_regime(dates[-10:], regime_reference=reference)

    assert regime == "high_vol"


def test_regime_reference_aggregates_multiple_symbols_by_date() -> None:
    dates = [date(2026, 1, day) for day in range(1, 31)]
    reference = []
    for index, day in enumerate(dates):
        reference.append(_reference_bar(day, 100.0 + (index * 2.0), symbol="SPY"))
        reference.append(_reference_bar(day, 1000.0 + (index * 20.0), symbol="AAPL"))

    regime = infer_market_regime(dates[-10:], regime_reference=reference)

    assert regime == "bull"


def test_regime_reference_uses_per_market_high_vol_before_global_average() -> None:
    dates = [date(2026, 1, day) for day in range(1, 31)]
    reference = []
    for index, day in enumerate(dates):
        reference.append(_reference_bar(day, 100.0 + (index * 0.1), symbol="SPY"))
    volatile_cn = [
        *[100.0 + (index * 0.1) for index in range(20)],
        110.0,
        92.0,
        116.0,
        88.0,
        120.0,
        84.0,
        124.0,
        82.0,
        126.0,
        80.0,
    ]
    for day, close in zip(dates, volatile_cn):
        reference.append(_reference_bar(day, close, symbol="000300.SH"))

    regime = infer_market_regime(dates[-10:], regime_reference=reference)

    assert regime == "high_vol"
