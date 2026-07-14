from datetime import date, datetime, timezone

from investment_research.training.labels import generate_multitask_labels
from investment_research.training.models import EventType, PointInTimeEvent, PreparedPriceBar


def _bar(symbol: str, trade_date: date, close_value: float) -> PreparedPriceBar:
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
        published_at=datetime.combine(trade_date, datetime.min.time(), tzinfo=timezone.utc),
    )


def test_generate_multitask_labels_uses_future_only_windows() -> None:
    price_bars = [
        _bar("AAPL", date(2026, 7, 1), 100.0),
        _bar("AAPL", date(2026, 7, 2), 101.0),
        _bar("AAPL", date(2026, 7, 3), 90.0),
        _bar("AAPL", date(2026, 7, 4), 95.0),
    ]
    benchmark_bars = [
        _bar("XLK", date(2026, 7, 1), 100.0),
        _bar("XLK", date(2026, 7, 2), 100.5),
        _bar("XLK", date(2026, 7, 3), 101.0),
        _bar("XLK", date(2026, 7, 4), 102.0),
    ]
    industry_bars = [
        _bar("SOXX", date(2026, 7, 1), 100.0),
        _bar("SOXX", date(2026, 7, 2), 100.2),
        _bar("SOXX", date(2026, 7, 3), 100.4),
        _bar("SOXX", date(2026, 7, 4), 100.6),
    ]
    events = [
        PointInTimeEvent(
            symbol="AAPL",
            event_type=EventType.EARNINGS,
            event_time=datetime(2026, 7, 3, 20, tzinfo=timezone.utc),
            published_at=datetime(2026, 7, 3, 20, tzinfo=timezone.utc),
            source_name="sec",
        )
    ]

    labels = generate_multitask_labels(
        symbol="AAPL",
        as_of_date=date(2026, 7, 1),
        price_bars=price_bars,
        benchmark_bars=benchmark_bars,
        industry_reference_bars=industry_bars,
        events=events,
    )

    assert round(labels.future_max_drawdown_20d or 0.0, 4) == -0.1089
    assert labels.post_earnings_abnormal_move_5d is not None
    assert labels.excess_return_20d is not None
    assert labels.industry_excess_return_20d is not None
