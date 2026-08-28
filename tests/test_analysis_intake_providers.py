"""§6⑤ stub→real provider replacement regression tests.

The stub filter providers are replaced by xystock/fortune live fetchers that
prefer pre-supplied REAL entries, attempt a live fetch when none are present,
and degrade to the persisted fallback on network failure — never synthesize.
"""
from __future__ import annotations

from datetime import datetime, timezone

from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, Provenance
from investment_research.service.analysis_intake import (
    RealtimeEvidenceProvider,
    RealtimeMarketDataProvider,
    _build_evidence_provider,
    _build_market_data_provider,
)


def _asset() -> Asset:
    provenance = Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="test",
        observed_at=datetime.now(timezone.utc),
    )
    return Asset(ticker="600519", name="贵州茅台", asset_type=AssetType.EQUITY, provenance=provenance)


def test_factory_returns_real_providers_for_stub_keys() -> None:
    # "stub*" keys now select the real fetchers (alias) so existing configs
    # keep working; the provider_name honestly reflects real fetching.
    assert _build_market_data_provider("stub_realtime").provider_name == "xystock-realtime-market-data-provider"
    assert _build_market_data_provider("stub").provider_name == "xystock-realtime-market-data-provider"
    assert _build_market_data_provider("realtime").provider_name == "xystock-realtime-market-data-provider"
    assert _build_evidence_provider("stub").provider_name == "fortune-realtime-evidence-provider"


def test_realtime_market_provider_degrades_to_persisted_when_fetch_empty() -> None:
    """No pre-supplied REAL entries + fetch returns nothing → degrade to the
    persisted fallback (never synthesize a fake series). Deterministic: the
    fetch is mocked so the test does not depend on akshare availability."""
    provider = RealtimeMarketDataProvider()
    assert provider.provider_name == "xystock-realtime-market-data-provider"
    provider._fetch_xystock_series = lambda asset: []  # type: ignore[assignment]
    selection = provider.select(_asset(), price_series=[])
    assert selection.provider_name == "persisted-market-data-provider"
    assert selection.status == "unavailable"


def test_realtime_market_provider_uses_fetched_series() -> None:
    """When the live fetch returns a series, the provider surfaces it as
    real_time_fetched (the §6⑤ live-fetch path, not the stub filter)."""
    from investment_research.domain.models import PricePoint, PriceSeries

    provider = RealtimeMarketDataProvider()
    ts = datetime.now(timezone.utc)
    provenance = Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="xystock-akshare-kline",
        observed_at=ts,
    )
    asset = _asset()
    series = PriceSeries(
        asset_id=asset.id,
        interval="1d",
        series_role="asset",
        reference_symbol=asset.ticker,
        points=[PricePoint(asset_id=asset.id, timestamp=ts, open=1.0, high=1.1, low=0.9, close=1.0, provenance=provenance)],
        provenance=provenance,
    )
    provider._fetch_xystock_series = lambda a: [series]  # type: ignore[assignment]
    selection = provider.select(asset, price_series=[])
    assert selection.provider_name == "xystock-realtime-market-data-provider"
    assert selection.status == "real_time_fetched"
    assert selection.price_series == [series]


def test_realtime_evidence_provider_degrades_to_persisted_when_fetch_empty() -> None:
    provider = RealtimeEvidenceProvider()
    assert provider.provider_name == "fortune-realtime-evidence-provider"
    provider._fetch_fortune_evidence = lambda asset: []  # type: ignore[assignment]
    selection = provider.select(_asset(), evidence=[])
    assert selection.provider_name == "persisted-evidence-provider"
    assert selection.status == "unavailable"


def test_realtime_evidence_provider_uses_fetched_evidence() -> None:
    from investment_research.domain.enums import EvidenceType
    from investment_research.domain.models import Evidence

    provider = RealtimeEvidenceProvider()
    asset = _asset()
    observed_at = datetime.now(timezone.utc)
    provenance = Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="fortune-akshare-fundamentals",
        observed_at=observed_at,
    )
    entry = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.FILING,
        title="gross_margin",
        summary="gross_margin: 91.5",
        collected_at=observed_at,
        provenance=provenance,
    )
    provider._fetch_fortune_evidence = lambda a: [entry]  # type: ignore[assignment]
    selection = provider.select(asset, evidence=[])
    assert selection.provider_name == "fortune-realtime-evidence-provider"
    assert selection.status == "real_time_fetched"
    assert selection.evidence == [entry]
