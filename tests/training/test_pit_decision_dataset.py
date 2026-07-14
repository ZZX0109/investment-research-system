from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.models import (
    CanonicalInstrument,
    CoverageGroup,
    EventType,
    InstrumentType,
    Market,
    PointInTimeEvent,
    PreparedPriceBar,
)


def test_close_excludes_evening_event_while_pre_open_includes_it() -> None:
    start = date(2026, 5, 4)
    dates: list[date] = []
    current = start
    while len(dates) < 30:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    bars = [
        PreparedPriceBar(
            symbol="600000.SH", trade_date=day, close_native=10 + index / 10,
            close_normalized=10 + index / 10, volume=1000, currency="CNY",
            target_currency="CNY", is_halted=False, is_suspended=False,
            published_at=datetime.combine(day, datetime.min.time(), timezone.utc),
        )
        for index, day in enumerate(dates)
    ]
    target_day = dates[20]
    evening = datetime(
        target_day.year, target_day.month, target_day.day, 10, 0, tzinfo=timezone.utc
    )  # 18:00 Asia/Shanghai
    event = PointInTimeEvent(
        symbol="600000.SH", event_type=EventType.ANNOUNCEMENT,
        event_time=evening, published_at=evening, available_at=evening,
        source_name="exchange",
    )
    instrument = CanonicalInstrument(
        symbol="600000.SH", market=Market.CN, instrument_type=InstrumentType.EQUITY,
        coverage_group=CoverageGroup.CN_A_SHARE, name="Test", currency="CNY",
    )
    builder = TrainingDatasetBuilder(feature_version="v2", data_version="pit-v1")

    close = builder.build_samples(
        instrument=instrument, price_bars=bars, events=[event],
        decision_context="close_confirmed", event_coverage_status="complete",
    )
    pre_open = builder.build_samples(
        instrument=instrument, price_bars=bars, events=[event],
        decision_context="pre_open", event_coverage_status="complete",
    )

    close_sample = next(item for item in close if item.as_of_date == target_day)
    pre_open_sample = next(item for item in pre_open if item.as_of_date == target_day)
    assert close_sample.point_in_time_event_count == 0
    assert pre_open_sample.point_in_time_event_count == 1
    assert pre_open_sample.event_source_available is True
