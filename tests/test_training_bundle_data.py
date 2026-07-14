from __future__ import annotations

import pickle
from datetime import date, datetime, timedelta, timezone

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset
from investment_research.service.analysis_intake import BundleBackedEvidenceProvider, BundleBackedMarketDataProvider
from investment_research.service.training_bundle_data import TrainingBundleDataStore
from investment_research.training.models import (
    CanonicalPriceBar,
    EventDirection,
    EventSourceTier,
    EventType,
    PointInTimeEvent,
)


def _asset() -> Asset:
    return Asset(
        ticker="AAPL",
        name="Apple",
        asset_type=AssetType.EQUITY,
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="operator",
            observed_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
        ),
    )


def _bar(symbol: str, offset: int) -> CanonicalPriceBar:
    trade_date = date(2026, 1, 1) + timedelta(days=offset)
    close = 100.0 + offset
    return CanonicalPriceBar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close,
        low=close,
        close=close,
        adjusted_close=close,
        volume=1_000_000,
        currency="USD",
        published_at=datetime.combine(trade_date, datetime.min.time(), tzinfo=timezone.utc),
        provider="yfinance",
    )


def test_bundle_backed_providers_expose_asset_references_and_structured_events(tmp_path) -> None:
    symbols = ["AAPL", "^GSPC", "XLK", "QQQ"]
    bars = [_bar(symbol, offset) for symbol in symbols for offset in range(25)]
    event_time = datetime(2026, 1, 24, tzinfo=timezone.utc)
    events = [
        PointInTimeEvent(
            symbol="AAPL",
            event_type=EventType.FILING,
            event_time=event_time,
            published_at=event_time,
            source_name="sec",
            headline="8-K guidance cut",
            payload_ref="filing-1",
            event_direction=EventDirection.NEGATIVE,
            source_tier=EventSourceTier.REGULATORY,
            filing_subtype="8-K",
        )
    ]
    with (tmp_path / "bundle_us.pkl").open("wb") as handle:
        pickle.dump({"source": "real:test", "price_bars": bars, "events": events}, handle)

    store = TrainingBundleDataStore(tmp_path)
    price_selection = BundleBackedMarketDataProvider(store).select(_asset(), price_series=[])
    evidence_selection = BundleBackedEvidenceProvider(store).select(_asset(), evidence=[])

    assert price_selection.status == "authoritative_real_bundle"
    assert {series.series_role for series in price_selection.price_series} == {
        "asset",
        "benchmark",
        "sector",
        "style",
    }
    assert evidence_selection.status == "authoritative_real_bundle"
    assert evidence_selection.evidence[0].direction == "negative"
    assert evidence_selection.evidence[0].filing_type == "8-K"
    assert evidence_selection.evidence[0].payload_ref == "filing-1"
