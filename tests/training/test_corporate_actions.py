"""Tests for corporate action adjustment module."""

import pandas as pd

from investment_research.training.corporate_actions import (
    adjust_price_bars_for_corporate_actions,
    calculate_adjustment_factors,
    detect_unadjusted_bars,
)
from investment_research.training.models import CanonicalPriceBar


def _make_bar(
    trade_date: str,
    close: float,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1000.0,
    split_factor: float | None = None,
    dividend_cash: float | None = None,
) -> CanonicalPriceBar:
    val = open_ or close
    return CanonicalPriceBar(
        symbol="AAPL",
        trade_date=pd.Timestamp(trade_date),
        open=val,
        high=high or val,
        low=low or val,
        close=close,
        volume=volume,
        currency="USD",
        split_factor=split_factor,
        dividend_cash=dividend_cash,
        published_at=pd.Timestamp.now(),
    )


class TestAdjustPriceBarsForCorporateActions:
    def test_empty_bars_returns_unchanged(self):
        result, records = adjust_price_bars_for_corporate_actions([])
        assert result == []
        assert records == []

    def test_no_corporate_actions_returns_unchanged(self):
        bars = [
            _make_bar("2025-01-02", 100.0),
            _make_bar("2025-01-03", 102.0),
        ]
        result, records = adjust_price_bars_for_corporate_actions(bars)
        assert result[0].close == 100.0
        assert result[1].close == 102.0
        assert records == []

    def test_2_for_1_split_halves_earlier_prices(self):
        bars = [
            _make_bar("2025-01-02", 200.0),
            _make_bar("2025-01-03", 101.0, split_factor=0.5),  # 2:1 split, price halves
        ]
        result, records = adjust_price_bars_for_corporate_actions(bars)

        # Earlier bar close was 200, now should be 200 * 0.5 = 100
        assert result[0].close == 100.0
        assert result[0].open == 100.0
        # Split bar itself unchanged
        assert result[1].close == 101.0
        assert len(records) == 1
        assert records[0].event_type == "split"

    def test_dividend_adjuses_earlier_prices_proportionally(self):
        bars = [
            _make_bar("2025-01-02", 100.0),
            _make_bar("2025-01-03", 100.0, dividend_cash=2.0),  # $2 dividend
        ]
        result, records = adjust_price_bars_for_corporate_actions(bars)

        # Dividend ratio = 2/100 = 0.02, so earlier = 100 * (1 - 0.02) = 98
        assert abs(result[0].close - 98.0) < 0.01
        assert result[1].close == 100.0
        assert len(records) == 1
        assert records[0].event_type == "dividend"

    def test_chain_multiple_splits_backward(self):
        bars = [
            _make_bar("2025-01-02", 400.0),
            _make_bar("2025-01-03", 201.0, split_factor=0.5),
            _make_bar("2025-01-04", 50.0, split_factor=0.25),
        ]
        result, records = adjust_price_bars_for_corporate_actions(bars)

        # Cumulative factor = 0.5 * 0.25 = 0.125
        # Day 1: 400 * 0.125 = 50
        # Day 2: 201 * 0.25 = 50.25
        assert abs(result[0].close - 50.0) < 0.01
        assert abs(result[1].close - 50.25) < 0.01
        assert result[2].close == 50.0
        assert len(records) == 2

    def test_split_and_dividend_combined(self):
        bars = [
            _make_bar("2025-01-02", 200.0),
            _make_bar("2025-01-03", 100.0, split_factor=0.5),
            _make_bar("2025-01-04", 100.0, dividend_cash=1.0),
        ]
        result, records = adjust_price_bars_for_corporate_actions(bars)

        # Cumulative split=0.5, dividend ratio = 1/100 = 0.01
        # Day 1: 200 * 0.5 * (1-0.01) = 99
        # Day 2: 100 * (1-0.01) = 99
        assert abs(result[0].close - 99.0) < 0.01
        assert abs(result[1].close - 99.0) < 0.01
        assert result[2].close == 100.0
        assert len(records) == 2


class TestCalculateAdjustmentFactors:
    def test_no_events_returns_ones(self):
        bars = [
            _make_bar("2025-01-02", 100.0),
            _make_bar("2025-01-03", 102.0),
        ]
        factors = calculate_adjustment_factors(bars)
        assert factors == [1.0, 1.0]

    def test_single_split_applies_correctly(self):
        bars = [
            _make_bar("2025-01-02", 200.0),
            _make_bar("2025-01-03", 101.0, split_factor=0.5),
        ]
        factors = calculate_adjustment_factors(bars)
        assert factors[0] == 0.5
        assert factors[1] == 1.0

    def test_chain_applies_cumulative(self):
        bars = [
            _make_bar("2025-01-02", 400.0),
            _make_bar("2025-01-03", 201.0, split_factor=0.5),
            _make_bar("2025-01-04", 100.0, split_factor=0.5),
        ]
        factors = calculate_adjustment_factors(bars)
        assert factors[0] == 0.25  # 0.5 * 0.5
        assert factors[1] == 0.5
        assert factors[2] == 1.0


class TestDetectUnadjustedBars:
    def test_normal_bars_produce_no_warnings(self):
        bars = [
            _make_bar("2025-01-02", 99.0),
            _make_bar("2025-01-03", 50.0, split_factor=0.5),
        ]
        warnings = detect_unadjusted_bars(bars)
        assert warnings == []

    def test_large_discontinuity_triggers_warning(self):
        bars = [
            _make_bar("2025-01-02", 200.0),
            _make_bar("2025-01-03", 200.0, split_factor=0.5),  # price didn't adjust for 2:1 split
        ]
        # Expected ratio 0.5, actual 1.0 → large gap
        warnings = detect_unadjusted_bars(bars)
        assert len(warnings) >= 1
        assert "unadjusted split" in warnings[0].lower()
