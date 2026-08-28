from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Protocol

from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.models import Asset, Evidence, PriceSeries
from investment_research.service.training_bundle_data import TrainingBundleDataError, TrainingBundleDataStore


@dataclass(frozen=True)
class ProviderSelection:
    provider_name: str
    provider_version: str
    status: str
    fallback_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriceSeriesSelection(ProviderSelection):
    price_series: list[PriceSeries] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceSelection(ProviderSelection):
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class AnalysisIntakeResolution:
    price_selection: PriceSeriesSelection
    evidence_selection: EvidenceSelection

    @property
    def price_series(self) -> list[PriceSeries]:
        return self.price_selection.price_series

    @property
    def evidence(self) -> list[Evidence]:
        return self.evidence_selection.evidence

    @property
    def fallback_reasons(self) -> list[str]:
        return [*self.price_selection.fallback_reasons, *self.evidence_selection.fallback_reasons]


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_name: str
    provider_version: str
    kind: str


class AnalysisProviderSettings:
    def __init__(self) -> None:
        self.market_data_provider = os.getenv("INVESTMENT_RESEARCH_MARKET_DATA_PROVIDER", "persisted_fallback")
        self.evidence_provider = os.getenv("INVESTMENT_RESEARCH_EVIDENCE_PROVIDER", "persisted_fallback")


class MarketDataProvider(Protocol):
    provider_name: str
    provider_version: str

    def select(self, asset: Asset, *, price_series: list[PriceSeries]) -> PriceSeriesSelection:
        ...


class EvidenceProvider(Protocol):
    provider_name: str
    provider_version: str

    def select(self, asset: Asset, *, evidence: list[Evidence]) -> EvidenceSelection:
        ...


class PersistedFallbackMarketDataProvider:
    provider_name = "persisted-market-data-provider"
    provider_version = "1.0.0"

    def select(self, asset: Asset, *, price_series: list[PriceSeries]) -> PriceSeriesSelection:
        if asset.provenance.data_mode != DataMode.REAL:
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="synthetic" if price_series else "unavailable",
                price_series=price_series,
            )

        real_series = [entry for entry in price_series if entry.provenance.source_type == DataSourceType.REAL]
        if real_series:
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="real_stale",
                fallback_reasons=["Persisted real data has no live-feed freshness guarantee."],
                price_series=real_series,
            )

        backfilled_series = [entry for entry in price_series if entry.provenance.source_type == DataSourceType.BACKFILLED]
        if backfilled_series:
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="backfilled",
                fallback_reasons=["Real-time market data unavailable; analysis fell back to backfilled price history."],
                price_series=backfilled_series,
            )

        if price_series:
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="synthetic",
                fallback_reasons=["Real-time market data unavailable; analysis used non-real persisted price inputs."],
                price_series=price_series,
            )

        return PriceSeriesSelection(
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            status="unavailable",
            fallback_reasons=["No persisted price data available for the requested real-data analysis."],
            price_series=[],
        )


class PersistedFallbackEvidenceProvider:
    provider_name = "persisted-evidence-provider"
    provider_version = "1.0.0"

    def select(self, asset: Asset, *, evidence: list[Evidence]) -> EvidenceSelection:
        if asset.provenance.data_mode != DataMode.REAL:
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="synthetic" if evidence else "unavailable",
                evidence=evidence,
            )

        real_evidence = [entry for entry in evidence if entry.provenance.source_type == DataSourceType.REAL]
        if real_evidence:
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="real_stale",
                fallback_reasons=["Persisted evidence has no live-feed freshness guarantee."],
                evidence=real_evidence,
            )

        non_synthetic_evidence = [entry for entry in evidence if entry.provenance.source_type != DataSourceType.SYNTHETIC]
        if non_synthetic_evidence:
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="backfilled",
                fallback_reasons=["No real-time evidence feed available; analysis fell back to curated persisted evidence."],
                evidence=non_synthetic_evidence,
            )

        if evidence:
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="synthetic",
                fallback_reasons=["No real-time evidence feed available; analysis fell back to synthetic evidence."],
                evidence=evidence,
            )

        return EvidenceSelection(
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            status="unavailable",
            fallback_reasons=["No evidence records available for the requested real-data analysis."],
            evidence=[],
        )


class RealtimeMarketDataProvider:
    """§6⑤: live market data via the xystock akshare adapter (replaces the
    ``stub-realtime`` filter).  Prefers pre-supplied REAL entries; when none
    are present it fetches a daily kline window via xystock + builds
    REAL-provenance ``PricePoint``s, then degrades to the persisted fallback
    on network failure — never synthesizes."""

    provider_name = "xystock-realtime-market-data-provider"
    provider_version = "1.0.0"

    def select(self, asset: Asset, *, price_series: list[PriceSeries]) -> PriceSeriesSelection:
        real_series = [entry for entry in price_series if entry.provenance.source_type == DataSourceType.REAL]
        if real_series:
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="real_time",
                price_series=real_series,
            )
        fetched = self._fetch_xystock_series(asset)
        if fetched:
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="real_time_fetched",
                price_series=fetched,
            )
        return PersistedFallbackMarketDataProvider().select(asset, price_series=price_series)

    def _fetch_xystock_series(self, asset: Asset) -> list[PriceSeries]:
        try:
            from datetime import datetime

            from investment_research.domain.models import PricePoint, PriceSeries, Provenance

            from investment_research.integrations.xystock.quote_fetcher import fetch_kline

            result = fetch_kline(asset.ticker, days=90)
            if not result.ok or not isinstance(result.data, list):
                return []
            points: list[PricePoint] = []
            for bar in result.data:
                if not isinstance(bar, dict):
                    continue
                try:
                    timestamp = datetime.fromisoformat(str(bar.get("date", "")))
                except (ValueError, TypeError):
                    continue
                open_v = bar.get("open")
                high_v = bar.get("high")
                low_v = bar.get("low")
                close_v = bar.get("close")
                if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (open_v, high_v, low_v, close_v)):
                    continue
                provenance = Provenance(
                    data_mode=DataMode.REAL,
                    source_type=DataSourceType.REAL,
                    source_name="xystock-akshare-kline",
                    observed_at=timestamp,
                )
                points.append(
                    PricePoint(
                        asset_id=asset.id,
                        timestamp=timestamp,
                        open=float(open_v),
                        high=float(high_v),
                        low=float(low_v),
                        close=float(close_v),
                        volume=bar.get("volume"),
                        provenance=provenance,
                    )
                )
            if not points:
                return []
            series = PriceSeries(
                asset_id=asset.id,
                interval="1d",
                series_role="asset",
                reference_symbol=asset.ticker,
                points=points,
                provenance=points[0].provenance,
            )
            return [series]
        except Exception:
            return []


class RealtimeEvidenceProvider:
    """§6⑤: live fundamental evidence via the fortune akshare adapter
    (replaces the ``stub-realtime`` filter).  Prefers pre-supplied REAL
    entries; when none are present it fetches fundamentals via fortune +
    builds REAL-provenance ``FILING`` ``Evidence`` entries, then degrades to
    the persisted fallback on network failure — never synthesizes."""

    provider_name = "fortune-realtime-evidence-provider"
    provider_version = "1.0.0"

    def select(self, asset: Asset, *, evidence: list[Evidence]) -> EvidenceSelection:
        real_evidence = [entry for entry in evidence if entry.provenance.source_type == DataSourceType.REAL]
        if real_evidence:
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="real_time",
                evidence=real_evidence,
            )
        fetched = self._fetch_fortune_evidence(asset)
        if fetched:
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status="real_time_fetched",
                evidence=fetched,
            )
        return PersistedFallbackEvidenceProvider().select(asset, evidence=evidence)

    def _fetch_fortune_evidence(self, asset: Asset) -> list[Evidence]:
        try:
            from datetime import datetime, timezone

            from investment_research.domain.enums import EvidenceType
            from investment_research.domain.models import Evidence, Provenance

            from investment_research.integrations.fortune.data_services.fundamental import fetch_fundamentals

            result = fetch_fundamentals(asset.ticker)
            if not result.ok or not isinstance(result.data, dict):
                return []
            observed_at = datetime.now(timezone.utc)
            provenance = Provenance(
                data_mode=DataMode.REAL,
                source_type=DataSourceType.REAL,
                source_name="fortune-akshare-fundamentals",
                observed_at=observed_at,
            )
            entries: list[Evidence] = []
            for metric, value in result.data.items():
                if metric == "symbol" or not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                entries.append(
                    Evidence(
                        asset_id=asset.id,
                        evidence_type=EvidenceType.FILING,
                        title=str(metric),
                        summary=f"{metric}: {value}",
                        collected_at=observed_at,
                        provenance=provenance,
                    )
                )
            return entries
        except Exception:
            return []


class BundleBackedMarketDataProvider:
    provider_name = "authoritative-training-bundle-market-provider"
    provider_version = "1.0.0"

    def __init__(self, store: TrainingBundleDataStore | None = None) -> None:
        self.store = store or TrainingBundleDataStore()

    def select(self, asset: Asset, *, price_series: list[PriceSeries]) -> PriceSeriesSelection:
        if asset.provenance.data_mode != DataMode.REAL:
            return PersistedFallbackMarketDataProvider().select(asset, price_series=price_series)
        try:
            bundle_series = self.store.price_series_for_asset(asset)
        except (TrainingBundleDataError, ValueError) as exc:
            fallback = PersistedFallbackMarketDataProvider().select(asset, price_series=price_series)
            return PriceSeriesSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status=fallback.status,
                fallback_reasons=[
                    f"Authoritative real bundle unavailable for {asset.ticker}: {exc}",
                    *fallback.fallback_reasons,
                ],
                price_series=fallback.price_series,
            )
        return PriceSeriesSelection(
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            status="authoritative_real_bundle",
            price_series=bundle_series,
        )


class BundleBackedEvidenceProvider:
    provider_name = "authoritative-training-bundle-evidence-provider"
    provider_version = "1.0.0"

    def __init__(self, store: TrainingBundleDataStore | None = None) -> None:
        self.store = store or TrainingBundleDataStore()

    def select(self, asset: Asset, *, evidence: list[Evidence]) -> EvidenceSelection:
        if asset.provenance.data_mode != DataMode.REAL:
            return PersistedFallbackEvidenceProvider().select(asset, evidence=evidence)
        try:
            bundle_evidence = self.store.evidence_for_asset(asset)
        except (TrainingBundleDataError, ValueError) as exc:
            fallback = PersistedFallbackEvidenceProvider().select(asset, evidence=evidence)
            return EvidenceSelection(
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                status=fallback.status,
                fallback_reasons=[
                    f"Authoritative real evidence bundle unavailable for {asset.ticker}: {exc}",
                    *fallback.fallback_reasons,
                ],
                evidence=fallback.evidence,
            )
        return EvidenceSelection(
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            status="authoritative_real_bundle",
            evidence=bundle_evidence,
        )


class AnalysisIntakeService:
    def __init__(
        self,
        *,
        market_data_provider: MarketDataProvider | None = None,
        evidence_provider: EvidenceProvider | None = None,
    ) -> None:
        self.market_data_provider = market_data_provider or PersistedFallbackMarketDataProvider()
        self.evidence_provider = evidence_provider or PersistedFallbackEvidenceProvider()

    def resolve(self, asset: Asset, *, price_series: list[PriceSeries], evidence: list[Evidence]) -> AnalysisIntakeResolution:
        return AnalysisIntakeResolution(
            price_selection=self.market_data_provider.select(asset, price_series=price_series),
            evidence_selection=self.evidence_provider.select(asset, evidence=evidence),
        )


@dataclass(frozen=True)
class AnalysisProviderRegistry:
    market_data_provider: MarketDataProvider
    evidence_provider: EvidenceProvider

    def describe(self) -> list[ProviderDescriptor]:
        return [
            ProviderDescriptor(
                provider_name=self.market_data_provider.provider_name,
                provider_version=self.market_data_provider.provider_version,
                kind="market_data",
            ),
            ProviderDescriptor(
                provider_name=self.evidence_provider.provider_name,
                provider_version=self.evidence_provider.provider_version,
                kind="evidence",
            ),
        ]

    def create_intake_service(self) -> AnalysisIntakeService:
        return AnalysisIntakeService(
            market_data_provider=self.market_data_provider,
            evidence_provider=self.evidence_provider,
        )


def build_provider_registry(settings: AnalysisProviderSettings | None = None) -> AnalysisProviderRegistry:
    configured = settings or AnalysisProviderSettings()
    market_data_provider = _build_market_data_provider(configured.market_data_provider)
    evidence_provider = _build_evidence_provider(configured.evidence_provider)
    return AnalysisProviderRegistry(
        market_data_provider=market_data_provider,
        evidence_provider=evidence_provider,
    )


def build_default_provider_registry() -> AnalysisProviderRegistry:
    return build_provider_registry()


def _build_market_data_provider(provider_key: str) -> MarketDataProvider:
    normalized = provider_key.strip().lower()
    if normalized in {"persisted_fallback", "persisted"}:
        return PersistedFallbackMarketDataProvider()
    if normalized in {"realtime", "real", "stub_realtime", "stub"}:
        # §6⑤: the stub filter is replaced by the xystock live fetcher;
        # "stub*" keys stay as aliases so existing env configs keep working.
        return RealtimeMarketDataProvider()
    if normalized in {"bundle_backed", "authoritative_bundle", "training_bundle"}:
        return BundleBackedMarketDataProvider()
    raise ValueError(f"Unsupported market data provider '{provider_key}'.")


def _build_evidence_provider(provider_key: str) -> EvidenceProvider:
    normalized = provider_key.strip().lower()
    if normalized in {"persisted_fallback", "persisted"}:
        return PersistedFallbackEvidenceProvider()
    if normalized in {"realtime", "real", "stub_realtime", "stub"}:
        # §6⑤: the stub filter is replaced by the fortune live fetcher;
        # "stub*" keys stay as aliases so existing env configs keep working.
        return RealtimeEvidenceProvider()
    if normalized in {"bundle_backed", "authoritative_bundle", "training_bundle"}:
        return BundleBackedEvidenceProvider()
    raise ValueError(f"Unsupported evidence provider '{provider_key}'.")
