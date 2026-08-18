from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from investment_research.training.feature_v4 import (
    build_cross_sectional_features,
    build_equal_weight_reference_bars,
    build_reference_return_features,
)
from investment_research.training.formal_direction_runner import _direction
from investment_research.training.models import InstrumentType, LabelSet, PreparedPriceBar
from investment_research.training.research_evaluation import (
    classify_market_regime_axes,
    fit_regime_thresholds,
)
from investment_research.training.tabular_preprocessing import estimator_pipeline, sample_matrix


def _bar(symbol: str, index: int, close: float, amount: float) -> PreparedPriceBar:
    when = date(2024, 1, 1) + timedelta(days=index)
    return PreparedPriceBar(
        symbol=symbol, trade_date=when,
        open_native=close, high_native=close * 1.01, low_native=close * 0.99,
        close_native=close, open_normalized=close, high_normalized=close * 1.01,
        low_normalized=close * 0.99, close_normalized=close,
        volume=1_000 + index, amount=amount, turnover_rate=0.01 + index / 10_000,
        is_halted=False, is_suspended=False,
        currency="CNY", target_currency="CNY",
        published_at=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
    )


def test_feature_v4_builds_nonzero_market_and_cross_section_features() -> None:
    bars = {
        "A": [_bar("A", index, 100 + index, 1_000_000 + index) for index in range(25)],
        "B": [_bar("B", index, 100 - index * 0.25, 2_000_000 + index) for index in range(25)],
    }
    reference = build_equal_weight_reference_bars(
        bars, symbols=["A", "B"], reference_symbol="510300",
    )
    features = build_reference_return_features(reference)
    latest = features[max(features)]
    assert latest["benchmark_ret_20d"] != 0

    cross_section = build_cross_sectional_features(bars, symbols=["A", "B"])
    row = cross_section["A"][max(cross_section["A"])]
    assert 0 < row["market_advance_ratio_1d"] < 1
    assert row["market_return_dispersion_1d"] > 0
    assert row["amount_cross_section_percentile"] != row["turnover_cross_section_percentile"]


def test_cross_section_uses_point_in_time_membership_when_supplied() -> None:
    bars = {
        "A": [_bar("A", index, 100 + index, 1_000_000) for index in range(3)],
        "B": [_bar("B", index, 100 - index, 2_000_000) for index in range(3)],
    }
    dates = [date(2024, 1, 1) + timedelta(days=index) for index in range(3)]
    features = build_cross_sectional_features(
        bars,
        symbols=["A", "B"],
        symbols_by_date={dates[0]: {"A", "B"}, dates[1]: {"A"}, dates[2]: {"A"}},
    )
    latest = features["A"][dates[-1]]
    assert latest["market_cross_section_coverage"] == pytest.approx(1.0)
    assert "B" not in features or dates[-1] not in features["B"]


def test_fold_pipeline_fits_imputer_on_training_rows_only() -> None:
    from sklearn.linear_model import LinearRegression

    train = [
        SimpleNamespace(symbol="A", as_of_date=date(2024, 1, 1), features={"x": 1.0}),
        SimpleNamespace(symbol="A", as_of_date=date(2024, 1, 2), features={"x": 3.0}),
        SimpleNamespace(symbol="A", as_of_date=date(2024, 1, 3), features={}),
    ]
    evaluate = [SimpleNamespace(symbol="A", as_of_date=date(2024, 1, 4), features={"x": 100.0})]
    pipeline = estimator_pipeline(LinearRegression())
    pipeline.fit(sample_matrix(train, ["x"]), [1.0, 3.0, 2.0])
    assert pipeline.steps[0][1].statistics_[0] == pytest.approx(2.0)
    pipeline.predict(sample_matrix(evaluate, ["x"]))
    assert pipeline.steps[0][1].statistics_[0] == pytest.approx(2.0)


def test_direction_multiplier_changes_only_development_selected_boundary() -> None:
    labels = LabelSet(
        symbol="A", as_of_date=date(2024, 1, 1), future_return_1d=0.006,
        volatility_standardized_return_1d=0.5, direction_1d="up",
    )
    sample = SimpleNamespace(labels=labels, instrument_type=InstrumentType.EQUITY)
    assert _direction(sample, 1, 0.25) == "up"
    assert _direction(sample, 1, 0.75) == "flat"


def test_regime_v3_produces_independent_trend_and_volatility_axes() -> None:
    training = [
        SimpleNamespace(features={"benchmark_ret_20d": value, "vol_20d": 0.1 + index / 100})
        for index, value in enumerate((-0.10, -0.05, 0.0, 0.03, 0.08, 0.12) * 10)
    ]
    thresholds = fit_regime_thresholds(training)
    bull_high = SimpleNamespace(features={"benchmark_ret_20d": 0.20, "vol_20d": 1.0})
    axes = classify_market_regime_axes(bull_high, thresholds)
    assert axes["trend"] == "bull"
    assert axes["volatility"] == "high_vol"
