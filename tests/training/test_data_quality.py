from datetime import date, datetime, timezone

from investment_research.training.data_quality import (
    detect_future_leakage,
    prepare_price_bars,
    select_point_in_time_events,
)
from investment_research.training.models import (
    CanonicalPriceBar,
    CurrencyHandlingPolicy,
    DataQualityRuleSet,
    EventType,
    MissingValuePolicy,
    PointInTimeEvent,
)


def test_prepare_price_bars_requires_fx_for_non_usd_conversion() -> None:
    bars = [
        CanonicalPriceBar(
            symbol="600519.SH",
            trade_date=date(2026, 7, 1),
            open=1500.0,
            high=1510.0,
            low=1490.0,
            close=1505.0,
            adjusted_close=1502.0,
            volume=1000.0,
            currency="CNY",
            published_at=datetime(2026, 7, 1, 16, tzinfo=timezone.utc),
            calendar_code="XSHG",
        )
    ]
    prepared, issues = prepare_price_bars(
        bars,
        rules=DataQualityRuleSet(currency_policy=CurrencyHandlingPolicy.CONVERT_TO_USD),
    )

    assert prepared == []
    assert issues[0].code == "missing_fx_rate"


def test_select_point_in_time_events_excludes_future_publications() -> None:
    as_of = datetime(2026, 7, 3, 12, tzinfo=timezone.utc)
    events = [
        PointInTimeEvent(
            symbol="AAPL",
            event_type=EventType.NEWS,
            event_time=datetime(2026, 7, 3, 10, tzinfo=timezone.utc),
            published_at=datetime(2026, 7, 3, 10, tzinfo=timezone.utc),
            source_name="wire",
        ),
        PointInTimeEvent(
            symbol="AAPL",
            event_type=EventType.NEWS,
            event_time=datetime(2026, 7, 3, 13, tzinfo=timezone.utc),
            published_at=datetime(2026, 7, 3, 13, tzinfo=timezone.utc),
            source_name="wire",
        ),
    ]

    selected = select_point_in_time_events(events, as_of=as_of)

    assert len(selected) == 1
    assert selected[0].published_at <= as_of


def test_detect_future_leakage_flags_future_bars_and_events() -> None:
    prepared, _ = prepare_price_bars(
        [
            CanonicalPriceBar(
                symbol="QQQ",
                trade_date=date(2026, 7, 3),
                open=500.0,
                high=501.0,
                low=495.0,
                close=498.0,
                adjusted_close=498.0,
                volume=1000.0,
                currency="USD",
                published_at=datetime(2026, 7, 3, 22, tzinfo=timezone.utc),
            )
        ],
        rules=DataQualityRuleSet(missing_value_policy=MissingValuePolicy.ERROR),
    )
    issues = detect_future_leakage(
        bars=prepared,
        events=[
            PointInTimeEvent(
                symbol="QQQ",
                event_type=EventType.NEWS,
                event_time=datetime(2026, 7, 3, 21, tzinfo=timezone.utc),
                published_at=datetime(2026, 7, 3, 21, tzinfo=timezone.utc),
                source_name="wire",
            )
        ],
        as_of=datetime(2026, 7, 3, 20, tzinfo=timezone.utc),
    )

    assert {issue.code for issue in issues} == {"future_price_bar", "future_event"}
