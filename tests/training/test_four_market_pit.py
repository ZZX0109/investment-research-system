from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import pytest

from investment_research.domain.decision_context import build_market_decision_context
from investment_research.domain.monitoring import (
    RuntimeMetricSnapshot,
    choose_runtime_route,
)
from investment_research.domain.pit import (
    EventCoverageStatus,
    HistoricalUniverseMembership,
)
from investment_research.training.labels import TradeableLabelPolicy, generate_tradeable_labels
from investment_research.training.leakage_audit import (
    audit_point_in_time_inputs,
    require_publishable_leakage_report,
)
from investment_research.training.models import PreparedPriceBar


def _bar(day: date, value: float, **updates) -> PreparedPriceBar:
    published = datetime.combine(day, datetime.min.time(), timezone.utc)
    payload = dict(
        symbol="TEST",
        trade_date=day,
        close_native=value,
        close_normalized=value,
        open_native=value,
        high_native=value * 1.01,
        low_native=value * 0.99,
        open_normalized=value,
        high_normalized=value * 1.01,
        low_normalized=value * 0.99,
        volume=1000,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=published,
        available_at=published,
    )
    payload.update(updates)
    return PreparedPriceBar(**payload)


def test_exchange_local_context_handles_us_dst_and_asian_sessions() -> None:
    us = build_market_decision_context(
        date(2026, 7, 13), "close_confirmed", calendar_code="XNYS"
    )
    jp = build_market_decision_context(
        date(2026, 7, 13), "close_confirmed", calendar_code="XTKS"
    )
    assert us.decision_time.hour == 16 and us.decision_time.utcoffset() == timedelta(
        hours=-4
    )
    assert jp.decision_time.hour == 15 and jp.decision_time.minute == 40


def test_us_context_uses_exchange_local_offset_on_both_sides_of_dst() -> None:
    # New York switches to daylight time on 2026-03-08 and returns on 2026-11-01.
    before = build_market_decision_context(
        date(2026, 3, 6), "close_confirmed", calendar_code="XNYS"
    )
    after = build_market_decision_context(
        date(2026, 3, 9), "close_confirmed", calendar_code="XNYS"
    )
    winter = build_market_decision_context(
        date(2026, 11, 2), "close_confirmed", calendar_code="XNYS"
    )
    assert before.decision_time.utcoffset() == timedelta(hours=-5)
    assert after.decision_time.utcoffset() == timedelta(hours=-4)
    assert winter.decision_time.utcoffset() == timedelta(hours=-5)


def test_tradeable_label_defers_one_price_limit_up_entry() -> None:
    start = date(2026, 1, 1)
    bars = [_bar(start + timedelta(days=index), 100 + index) for index in range(30)]
    bars[1] = bars[1].model_copy(
        update={"is_one_price_limit": True, "is_limit_up": True}
    )
    labels = generate_tradeable_labels(symbol="TEST", as_of_date=start, price_bars=bars)
    assert labels.entry_trade_date == start + timedelta(days=2)
    assert labels.entry_delay_sessions == 1
    assert labels.label_available is True
    assert labels.future_max_drawdown_20d is not None
    assert labels.direction_5d in {"up", "down", "flat"}


def test_volatility_direction_label_uses_instrument_cost_floor() -> None:
    start = date(2026, 1, 1)
    # A low-volatility 0.45% move is above the ETF cost floor (0.24%) but
    # below the stock floor (0.42%) once the v2 two-way cost rule applies.
    bars = [_bar(start + timedelta(days=index), 100.0) for index in range(45)]
    bars[1] = bars[1].model_copy(update={"close_native": 100.40, "close_normalized": 100.40})
    policy = TradeableLabelPolicy(version="cn-direction-volatility-label-v2", minimum_cost_boundary=0.0)
    stock = generate_tradeable_labels(symbol="TEST", as_of_date=start, price_bars=bars, policy=policy)
    etf = generate_tradeable_labels(symbol="ETF", as_of_date=start, price_bars=bars, policy=policy, instrument_is_etf=True)
    assert stock.direction_1d == "flat"
    assert etf.direction_1d == "up"


def test_leakage_report_blocks_future_and_unproven_inputs() -> None:
    decision = datetime(2026, 1, 2, 21, 10, tzinfo=timezone.utc)
    bar = _bar(date(2026, 1, 2), 100).model_copy(update={"available_at": None})
    universe = HistoricalUniverseMembership(
        symbol="TEST",
        market="us",
        exchange="XNYS",
        instrument_type="equity",
        effective_from=decision + timedelta(days=1),
        listed_on=date(2020, 1, 1),
        available_at=decision + timedelta(days=1),
        provider="licensed",
        revision=1,
    )
    report = audit_point_in_time_inputs(
        training_run_id="run-1",
        decision_time=decision,
        generated_at=decision + timedelta(minutes=1),
        bars=[bar],
        universe=[universe],
        feature_names=["future_return_1d"],
        label_names=["future_return_1d"],
    )
    assert report.error_count >= 3
    assert report.verify_hash()
    with pytest.raises(ValueError):
        require_publishable_leakage_report(report)


def test_runtime_route_uses_approved_baseline_then_abstains() -> None:
    metric = RuntimeMetricSnapshot(
        market="hk",
        decision_context="pre_open",
        task="risk",
        observed_at=datetime.now(timezone.utc),
        missing_rate=0.3,
        coverage_ratio=0.9,
        abstain_rate=0.1,
    )
    fallback = choose_runtime_route(
        metric=metric, primary_version="primary-v1", baseline_version="linear-v1"
    )
    assert fallback.selected_tier == "baseline"
    stopped = choose_runtime_route(
        metric=metric, primary_version="primary-v1", baseline_version=None
    )
    assert stopped.selected_tier == "abstain"


def test_event_coverage_enum_only_allows_valid_zero_semantics() -> None:
    assert EventCoverageStatus.CONFIRMED_NONE.permits_zero_features
    assert not EventCoverageStatus.FETCH_FAILED.permits_zero_features
