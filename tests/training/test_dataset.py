from datetime import date, datetime, timedelta, timezone

from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.models import (
    CanonicalInstrument,
    EventDirection,
    GuidanceBucket,
    InstrumentType,
    Market,
    PointInTimeEvent,
    PreparedPriceBar,
    EventType,
    SurpriseBucket,
)


def _bar(
    symbol: str, trade_date: date, close_value: float, *, volume: float = 1000.0
) -> PreparedPriceBar:
    return PreparedPriceBar(
        symbol=symbol,
        trade_date=trade_date,
        close_native=close_value,
        close_normalized=close_value,
        volume=volume,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=datetime.combine(
            trade_date, datetime.min.time(), tzinfo=timezone.utc
        ),
    )


def test_training_dataset_builder_creates_point_in_time_samples() -> None:
    builder = TrainingDatasetBuilder(
        feature_version="features-v1", data_version="dataset-v1"
    )
    instrument = CanonicalInstrument(
        symbol="AAPL",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        name="Apple",
        currency="USD",
        benchmark_symbol="^GSPC",
        sector_reference_symbol="XLK",
        style_reference_symbol="QQQ",
        industry_key="tech",
    )
    price_bars = [
        _bar("AAPL", date(2026, 1, day), 100 + day, volume=1000 + day)
        for day in range(1, 31)
    ]
    benchmark_bars = [
        _bar("^GSPC", date(2026, 1, day), 300 + day, volume=3000 + day)
        for day in range(1, 31)
    ]
    sector_reference_bars = [
        _bar("XLK", date(2026, 1, day), 200 + day, volume=2000 + day)
        for day in range(1, 31)
    ]
    style_reference_bars = [
        _bar("QQQ", date(2026, 1, day), 250 + (day * 1.5), volume=2500 + day)
        for day in range(1, 31)
    ]
    events = [
        PointInTimeEvent(
            symbol="AAPL",
            event_type=EventType.NEWS,
            event_time=datetime(2026, 1, 25, 10, tzinfo=timezone.utc),
            published_at=datetime(2026, 1, 25, 10, tzinfo=timezone.utc),
            source_name="wire",
        )
    ]

    samples = builder.build_samples(
        instrument=instrument,
        price_bars=price_bars,
        benchmark_bars=benchmark_bars,
        sector_reference_bars=sector_reference_bars,
        style_reference_bars=style_reference_bars,
        events=events,
    )

    assert samples
    sample = samples[5]
    assert sample.feature_version == "features-v1"
    assert sample.data_version == "dataset-v1"
    assert "ret_20d" in sample.features
    assert "sector_relative_strength_20d" in sample.features
    assert "style_relative_strength_20d" in sample.features
    assert sample.sector_reference_symbol == "XLK"
    assert sample.style_reference_symbol == "QQQ"
    assert sample.labels.industry_excess_return_20d is not None
    assert sample.point_in_time_event_count >= 1


def test_structured_event_features_use_announcement_semantics() -> None:
    builder = TrainingDatasetBuilder(
        feature_version="features-v1", data_version="dataset-v1"
    )
    instrument = CanonicalInstrument(
        symbol="AAPL",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        name="Apple",
        currency="USD",
        benchmark_symbol="^GSPC",
        sector_reference_symbol="XLK",
        style_reference_symbol="QQQ",
        industry_key="tech",
    )
    price_bars = [
        _bar("AAPL", date(2026, 1, day), 100 + day, volume=1000 + day)
        for day in range(1, 31)
    ]
    event_time = datetime(2026, 1, 25, 10, tzinfo=timezone.utc)
    events = [
        PointInTimeEvent(
            symbol="AAPL",
            event_type=EventType.ANNOUNCEMENT,
            event_time=event_time,
            published_at=event_time,
            source_name="exchange",
            event_direction=EventDirection.NEGATIVE,
            surprise_bucket=SurpriseBucket.MISS,
            guidance_bucket=GuidanceBucket.CUT,
        )
    ]

    samples = builder.build_samples(
        instrument=instrument, price_bars=price_bars, events=events
    )
    sample = next(item for item in samples if item.as_of_date == date(2026, 1, 25))

    assert sample.features["negative_event_score_7d"] > 0
    assert sample.features["earnings_surprise_score_30d"] < 0
    assert sample.features["guidance_cut_flag_30d"] == 1.0


def test_reference_alignment_never_uses_future_publication_and_recovers_later() -> None:
    builder = TrainingDatasetBuilder(
        feature_version="features-v1", data_version="dataset-v1"
    )
    instrument = CanonicalInstrument(
        symbol="AAPL",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        name="Apple",
        currency="USD",
        benchmark_symbol="^GSPC",
        industry_key="tech",
    )
    price_bars = [_bar("AAPL", date(2026, 1, day), 100 + day) for day in range(1, 31)]
    benchmark_bars = [
        _bar("^GSPC", date(2026, 1, day), 300 + day) for day in range(1, 31)
    ]
    delayed = benchmark_bars[20]
    benchmark_bars[20] = delayed.model_copy(
        update={"published_at": delayed.published_at + timedelta(days=2)}
    )

    samples = builder.build_samples(
        instrument=instrument, price_bars=price_bars, benchmark_bars=benchmark_bars
    )
    jan_21 = next(
        sample for sample in samples if sample.as_of_date == date(2026, 1, 21)
    )
    jan_23 = next(
        sample for sample in samples if sample.as_of_date == date(2026, 1, 23)
    )

    assert jan_21.features["benchmark_ret_20d"] != (321 / 302) - 1
    assert jan_23.features["benchmark_ret_20d"] != 0.0
