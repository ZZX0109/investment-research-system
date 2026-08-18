from datetime import date, datetime, timezone

import pytest

from scripts.run_cn_research_inference import _latest_price, _parse_decision_time


def _bar(trade_date: str, *, available_at: str | None, close: float) -> dict:
    return {
        "symbol": "600000.SH",
        "trade_date": trade_date,
        "close_native": close,
        "close_normalized": close,
        "volume": 100.0,
        "currency": "CNY",
        "target_currency": "CNY",
        "is_halted": False,
        "is_suspended": False,
        "published_at": "2026-08-10T08:00:00+00:00",
        "available_at": available_at,
    }


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def read_partition(self, _ref):
        return self.rows


def test_parse_decision_time_requires_timezone_and_normalizes_to_utc() -> None:
    parsed = _parse_decision_time("2026-08-10T16:00:00+08:00")
    assert parsed == datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone"):
        _parse_decision_time("2026-08-10T16:00:00")


def test_latest_price_does_not_read_future_or_unproven_bars() -> None:
    store = _Store([
        _bar("2026-08-08", available_at="2026-08-10T09:00:00+00:00", close=10.0),
        _bar("2026-08-09", available_at=None, close=11.0),
        _bar("2026-08-11", available_at="2026-08-11T09:00:00+00:00", close=12.0),
    ])
    result = _latest_price(
        {"partitions": [{"parquet_ref": "prices/600000"}]},
        store,
        decision_time=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
        cutoff_date=date(2026, 8, 10),
    )
    assert result == 10.0
