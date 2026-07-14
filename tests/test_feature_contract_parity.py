from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from investment_research.domain.base import Provenance
from investment_research.domain.enums import (
    AssetType,
    DataMode,
    DataSourceType,
    EvidenceType,
)
from investment_research.domain.models import Asset, Evidence, PricePoint, PriceSeries
from investment_research.pipeline.model_inference import SnapshotFeatureBuilder
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.feature_contract import INVESTMENT_RISK_FEATURE_ORDER
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.models import (
    CanonicalInstrument,
    EventDirection,
    EventIntensity,
    EventType,
    InstrumentType,
    Market,
    PointInTimeEvent,
    PreparedPriceBar,
    EventSourceTier,
)


def _provenance(observed_at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="parity",
        observed_at=observed_at,
    )


def _bar(symbol: str, day: int, multiplier: float = 1.0) -> PreparedPriceBar:
    trade_date = date(2026, 1, day)
    published_at = datetime(2026, 1, day, 20, tzinfo=timezone.utc)
    return PreparedPriceBar(
        symbol=symbol,
        trade_date=trade_date,
        close_native=(100 + day) * multiplier,
        close_normalized=(100 + day) * multiplier,
        volume=1_000_000 + day * 100,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=published_at,
    )


def test_training_and_runtime_build_identical_29_feature_vector() -> None:
    instrument = CanonicalInstrument(
        symbol="AAPL",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        name="Apple",
        currency="USD",
        benchmark_symbol="SPY",
        sector_reference_symbol="XLK",
        style_reference_symbol="QQQ",
        industry_key="technology",
    )
    bars = [_bar("AAPL", day) for day in range(1, 31)]
    benchmark = [_bar("SPY", day, 2.0) for day in range(1, 31)]
    sector = [_bar("XLK", day, 1.5) for day in range(1, 31)]
    style = [_bar("QQQ", day, 2.5) for day in range(1, 31)]
    event_time = datetime(2026, 1, 28, 12, tzinfo=timezone.utc)
    event = PointInTimeEvent(
        symbol="AAPL",
        event_type=EventType.FILING,
        event_time=event_time,
        published_at=event_time,
        source_name="SEC",
        event_direction=EventDirection.NEGATIVE,
        event_intensity=EventIntensity.MAJOR,
        source_tier=EventSourceTier.REGULATORY,
        filing_subtype="8-K",
    )
    sample = TrainingDatasetBuilder(
        feature_version="investment-risk-features-v1", data_version="parity"
    ).build_samples(
        instrument=instrument,
        price_bars=bars,
        benchmark_bars=benchmark,
        sector_reference_bars=sector,
        style_reference_bars=style,
        events=[event],
    )[-1]

    asset = Asset(
        ticker="AAPL",
        name="Apple",
        asset_type=AssetType.EQUITY,
        exchange="NASDAQ",
        provenance=_provenance(bars[-1].published_at),
    )
    role_bars = {
        "asset": bars,
        "benchmark": benchmark,
        "sector": sector,
        "style": style,
    }
    series = []
    for role, source in role_bars.items():
        points = [
            PricePoint(
                asset_id=asset.id,
                timestamp=bar.published_at,
                open=bar.close_normalized,
                high=bar.close_normalized,
                low=bar.close_normalized,
                close=bar.close_normalized,
                volume=bar.volume,
                provenance=_provenance(bar.published_at),
            )
            for bar in source
        ]
        series.append(
            PriceSeries(
                asset_id=asset.id,
                interval="1d",
                series_role=role,
                points=points,
                provenance=_provenance(points[-1].timestamp),
            )
        )
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.FILING,
        title="8-K regulatory filing",
        summary="Material negative event",
        collected_at=event_time,
        published_at=event_time,
        event_type="filing",
        direction="negative",
        intensity="major",
        source_tier="regulatory",
        filing_type="8-K",
        provenance=_provenance(event_time),
    )
    cutoff = datetime(2026, 1, 30, 23, 59, tzinfo=timezone.utc)
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id),
        asset_snapshot=asset,
        captured_at=cutoff,
        as_of=cutoff,
        data_modes=["real"],
        source_types=["real"],
        price_series_snapshot=series,
        evidence_snapshot=[evidence],
        synthetic_share=0,
        real_share=1,
    )

    runtime = SnapshotFeatureBuilder().build(snapshot, INVESTMENT_RISK_FEATURE_ORDER)

    assert runtime.feature_coverage == 1.0
    assert runtime.missing_features == []
    assert runtime.values == pytest.approx(
        [sample.features[name] for name in INVESTMENT_RISK_FEATURE_ORDER]
    )
