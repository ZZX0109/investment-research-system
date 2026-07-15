from datetime import datetime, timezone

import pytest

from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import Asset, Evidence, PricePoint, PriceSeries
from investment_research.pipeline.snapshot_factory import AnalysisSnapshotFactory
from investment_research.service.analysis_intake import AnalysisIntakeResolution, EvidenceSelection, PriceSeriesSelection

FIXED_NOW = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)


def snapshot_factory() -> AnalysisSnapshotFactory:
    return AnalysisSnapshotFactory(clock=lambda: FIXED_NOW)


def provenance(*, data_mode: DataMode = DataMode.REAL, source_type: DataSourceType = DataSourceType.REAL) -> Provenance:
    return Provenance(
        data_mode=data_mode,
        source_type=source_type,
        source_name=f"{data_mode.value}-{source_type.value}",
        observed_at=FIXED_NOW,
        confidence=0.9,
    )


def price_series(asset: Asset, *, source_type: DataSourceType, close: float) -> PriceSeries:
    observed_at = FIXED_NOW
    return PriceSeries(
        asset_id=asset.id,
        interval="1d",
        points=[
            PricePoint(
                asset_id=asset.id,
                timestamp=observed_at,
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=1000,
                provenance=provenance(source_type=source_type),
            )
        ],
        provenance=provenance(source_type=source_type),
    )


def evidence(asset: Asset, *, source_type: DataSourceType, title: str) -> Evidence:
    return Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.RESEARCH_NOTE,
        title=title,
        summary=f"{title} summary",
        collected_at=FIXED_NOW,
        provenance=provenance(source_type=source_type),
    )


def test_snapshot_factory_freezes_selected_inputs_and_source_metadata() -> None:
    asset = Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type=AssetType.EQUITY,
        provenance=provenance(source_type=DataSourceType.REAL),
    )
    selected_price = price_series(asset, source_type=DataSourceType.BACKFILLED, close=420.5)
    selected_evidence = evidence(asset, source_type=DataSourceType.REAL, title="Channel checks")
    resolution = AnalysisIntakeResolution(
        price_selection=PriceSeriesSelection(
            provider_name="persisted-market",
            provider_version="1.0.0",
            status="fallback_backfilled",
            fallback_reasons=["market fallback", "market fallback"],
            price_series=[selected_price],
        ),
        evidence_selection=EvidenceSelection(
            provider_name="persisted-evidence",
            provider_version="1.0.0",
            status="real_time",
            evidence=[selected_evidence],
        ),
    )

    snapshot = snapshot_factory().build_snapshot(asset, resolution)

    assert snapshot.asset_id == str(asset.id)
    assert snapshot.asset_snapshot == asset
    assert snapshot.price_series_snapshot == [selected_price]
    assert snapshot.evidence_snapshot == [selected_evidence]
    assert snapshot.provider == "persisted-market@1.0.0 | persisted-evidence@1.0.0"
    assert snapshot.source_meta.provider == snapshot.provider
    assert snapshot.as_of == selected_price.points[-1].timestamp
    assert snapshot.source_meta.as_of == snapshot.as_of
    assert snapshot.overrides == ["market fallback"]
    assert snapshot.fallback_reasons == ["market fallback", "market fallback"]
    assert snapshot.latest_close == 420.5
    assert snapshot.price_provider_status == "fallback_backfilled"
    assert snapshot.evidence_provider_status == "real_time"
    assert snapshot.evidence_ids == [str(selected_evidence.id)]
    assert snapshot.evidence_citation_ids == [str(selected_evidence.id)]
    assert snapshot.data_modes == ["real"]
    assert snapshot.source_types == ["backfilled", "real"]
    assert snapshot.synthetic_share == 0.0
    assert snapshot.real_share == pytest.approx(2 / 3)
    assert snapshot.source_meta.synthetic_ratio == snapshot.synthetic_ratio
    assert snapshot.feature_built_at == FIXED_NOW
    assert snapshot.captured_at == FIXED_NOW


def test_snapshot_factory_rejects_transparent_mixed_data_modes() -> None:
    asset = Asset(
        ticker="DEMO",
        name="Demo Asset",
        asset_type=AssetType.EQUITY,
        provenance=provenance(data_mode=DataMode.DEMO, source_type=DataSourceType.SYNTHETIC),
    )
    real_evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.RESEARCH_NOTE,
        title="Real note",
        summary="Mixed mode should not be accepted.",
        collected_at=FIXED_NOW,
        provenance=provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL),
    )
    resolution = AnalysisIntakeResolution(
        price_selection=PriceSeriesSelection(
            provider_name="demo-market",
            provider_version="1.0.0",
            status="seeded",
            price_series=[],
        ),
        evidence_selection=EvidenceSelection(
            provider_name="real-evidence",
            provider_version="1.0.0",
            status="real_time",
            evidence=[real_evidence],
        ),
    )

    with pytest.raises(ValueError, match="cannot mix data modes transparently"):
        snapshot_factory().build_snapshot(asset, resolution)


def test_snapshot_factory_rejects_naive_clock() -> None:
    asset = Asset(
        ticker="DEMO",
        name="Demo Asset",
        asset_type=AssetType.EQUITY,
        provenance=provenance(),
    )
    resolution = AnalysisIntakeResolution(
        price_selection=PriceSeriesSelection(
            provider_name="empty",
            provider_version="1.0.0",
            status="unavailable",
            price_series=[],
        ),
        evidence_selection=EvidenceSelection(
            provider_name="empty",
            provider_version="1.0.0",
            status="unavailable",
            evidence=[],
        ),
    )

    with pytest.raises(ValueError, match="aware datetime"):
        AnalysisSnapshotFactory(clock=lambda: datetime(2026, 7, 14)).build_snapshot(
            asset, resolution
        )
