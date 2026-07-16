from __future__ import annotations

import pickle
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import Asset, Evidence, PricePoint, PriceSeries
from investment_research.training.models import (
    CanonicalPriceBar,
    PointInTimeEvent,
    PreparedPriceBar,
)
from investment_research.training.sources import resolve_coverage_preset
from investment_research.training.real_data import (
    AksharePriceFetcher,
    YFinancePriceFetcher,
)
from investment_research.config import AppEnvironment, get_app_settings
from investment_research.training.sources import (
    normalize_akshare_rows,
    normalize_yfinance_rows,
)


DEFAULT_BUNDLE_ROOT = Path(__file__).resolve().parents[3] / "output"


class TrainingBundleDataError(RuntimeError):
    pass


class LivePublicPriceDataStore:
    """Research/backfill adapter for free public providers; never production authority."""

    def price_series_for_asset(self, asset: Asset) -> list[PriceSeries]:
        if get_app_settings().environment == AppEnvironment.PRODUCTION:
            raise TrainingBundleDataError("Public AKShare/yfinance adapters are disabled in production")
        preset = resolve_coverage_preset(asset.ticker)
        roles = {
            "asset": preset.symbol,
            "benchmark": preset.benchmark_symbol,
            "sector": preset.sector_reference_symbol,
            "style": preset.style_reference_symbol,
        }
        end = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = end - timedelta(days=365 * 3 + 30)
        output: list[PriceSeries] = []
        failures: list[str] = []
        for role, symbol in roles.items():
            if not symbol:
                continue
            try:
                bars = self._fetch_bars(symbol, start=start, end=end)
                if not bars:
                    raise TrainingBundleDataError(f"empty response for {symbol}")
                points = [self._point(asset.id, symbol, bar) for bar in bars]
                output.append(
                    PriceSeries(
                        id=uuid5(
                            NAMESPACE_URL,
                            f"investment-research:live-series:{asset.id}:{role}:{symbol}:{points[-1].timestamp.isoformat()}",
                        ),
                        asset_id=asset.id,
                        interval="1d",
                        series_role=role,
                        reference_symbol=None if role == "asset" else symbol,
                        points=points,
                        provenance=self._provenance(
                            f"live-public:{bars[-1].provider or 'unknown'}:{symbol}",
                            points[-1].timestamp,
                        ),
                    )
                )
            except Exception as exc:
                failures.append(f"{role}:{symbol}:{exc}")
        if not any(item.series_role == "asset" for item in output):
            raise TrainingBundleDataError(
                "Live public price refresh failed: " + "; ".join(failures)
            )
        return output

    def _fetch_bars(self, symbol: str, *, start: date, end: date):
        preset = resolve_coverage_preset(symbol)
        if preset.market.value == "cn":
            rows = AksharePriceFetcher().fetch_price_rows(symbol, start=start, end=end)
            return normalize_akshare_rows(symbol, rows).price_bars
        rows = YFinancePriceFetcher().fetch_price_rows(symbol, start=start, end=end)
        return normalize_yfinance_rows(symbol, rows).price_bars

    def _point(self, asset_id: UUID, symbol: str, bar: CanonicalPriceBar) -> PricePoint:
        close = float(
            bar.adjusted_close if bar.adjusted_close is not None else bar.close
        )
        return PricePoint(
            id=uuid5(
                NAMESPACE_URL,
                f"investment-research:live-price:{asset_id}:{symbol}:{bar.trade_date.isoformat()}",
            ),
            asset_id=asset_id,
            timestamp=bar.published_at,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=close,
            volume=None if bar.volume is None else float(bar.volume),
            provenance=self._provenance(
                bar.provider or "live-public", bar.published_at
            ),
        )

    def _provenance(self, source_name: str, observed_at: datetime) -> Provenance:
        return Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name=source_name,
            observed_at=observed_at,
            confidence=0.9,
        )


class TrainingBundleDataStore:
    """Read authoritative real/full bundles through domain models used by analysis runs."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DEFAULT_BUNDLE_ROOT
        self._cache: dict[Path, tuple[int, dict]] = {}

    def price_series_for_asset(self, asset: Asset) -> list[PriceSeries]:
        preset = resolve_coverage_preset(asset.ticker)
        bundle = self._bundle(preset.market.value)
        roles = {
            "asset": preset.symbol,
            "benchmark": preset.benchmark_symbol,
            "sector": preset.sector_reference_symbol,
            "style": preset.style_reference_symbol,
        }
        series: list[PriceSeries] = []
        for role, symbol in roles.items():
            if not symbol:
                continue
            bars = sorted(
                [bar for bar in bundle.get("price_bars", []) if bar.symbol == symbol],
                key=lambda bar: bar.trade_date,
            )
            if not bars:
                continue
            points = [self._price_point(asset.id, symbol, bar) for bar in bars]
            observed_at = max(point.timestamp for point in points)
            series.append(
                PriceSeries(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"investment-research:series:{asset.id}:{role}:{symbol}:{observed_at.isoformat()}",
                    ),
                    asset_id=asset.id,
                    interval="1d",
                    series_role=role,
                    reference_symbol=None if role == "asset" else symbol,
                    points=points,
                    provenance=self._provenance(
                        source_name=f"training-bundle:{preset.market.value}:{symbol}",
                        observed_at=observed_at,
                    ),
                )
            )
        if not any(item.series_role == "asset" for item in series):
            raise TrainingBundleDataError(f"No price bars found for {asset.ticker}")
        return series

    def evidence_for_asset(self, asset: Asset) -> list[Evidence]:
        preset = resolve_coverage_preset(asset.ticker)
        bundle = self._bundle(preset.market.value)
        asset_bars = [
            bar for bar in bundle.get("price_bars", []) if bar.symbol == preset.symbol
        ]
        if not asset_bars:
            raise TrainingBundleDataError(
                f"No point-in-time cutoff found for {asset.ticker}"
            )
        as_of = max(bar.published_at for bar in asset_bars)
        earliest = as_of - timedelta(days=365)
        events = sorted(
            [
                event
                for event in bundle.get("events", [])
                if event.symbol == preset.symbol
                and earliest <= event.published_at <= as_of
            ],
            key=lambda event: event.published_at,
            reverse=True,
        )
        return [self._evidence(asset.id, event) for event in events]

    def _bundle(self, market: str) -> dict:
        path = self.root / f"bundle_{market}.pkl"
        if not path.exists():
            raise TrainingBundleDataError(f"Authoritative bundle is missing: {path}")
        mtime = path.stat().st_mtime_ns
        cached = self._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with path.open("rb") as handle:
            bundle = pickle.load(handle)  # noqa: S301 - local, training-produced artifact only
        if not isinstance(bundle, dict):
            raise TrainingBundleDataError(f"Invalid bundle payload: {path}")
        source = str(bundle.get("source") or "").lower()
        if "real" not in source:
            raise TrainingBundleDataError(f"Bundle is not marked real: {path}")
        self._cache[path] = (mtime, bundle)
        return bundle

    def _price_point(
        self,
        asset_id: UUID,
        symbol: str,
        bar: PreparedPriceBar | CanonicalPriceBar,
    ) -> PricePoint:
        normalized = getattr(bar, "close_normalized", None)
        adjusted = getattr(bar, "adjusted_close", None)
        close = float(
            normalized
            if normalized is not None
            else adjusted
            if adjusted is not None
            else bar.close
        )
        return PricePoint(
            id=uuid5(
                NAMESPACE_URL,
                f"investment-research:price:{asset_id}:{symbol}:{bar.trade_date.isoformat()}",
            ),
            asset_id=asset_id,
            timestamp=bar.published_at,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=None if bar.volume is None else float(bar.volume),
            provenance=self._provenance(
                source_name=bar.provider or "real-training-bundle",
                observed_at=bar.published_at,
            ),
        )

    def _evidence(self, asset_id: UUID, event: PointInTimeEvent) -> Evidence:
        event_type = event.event_type.value
        evidence_type = EvidenceType.NEWS
        if event_type in {"filing", "announcement"}:
            evidence_type = EvidenceType.FILING
        elif event_type == "earnings":
            evidence_type = EvidenceType.RESEARCH_NOTE
        identity = (
            event.payload_ref
            or event.normalized_hash
            or event.headline
            or event.published_at.isoformat()
        )
        return Evidence(
            id=uuid5(
                NAMESPACE_URL, f"investment-research:evidence:{asset_id}:{event_type}:{identity}"
            ),
            asset_id=asset_id,
            evidence_type=evidence_type,
            title=event.headline or f"{event_type.title()} event",
            summary=(
                f"{event_type} event; direction={event.event_direction.value}; "
                f"intensity={event.event_intensity.value}; source_tier={event.source_tier.value}"
            ),
            source_url=event.source_url,
            collected_at=event.published_at,
            published_at=event.published_at,
            payload_ref=event.payload_ref,
            event_type=event_type,
            direction=event.event_direction.value,
            intensity=event.event_intensity.value,
            source_tier=event.source_tier.value,
            surprise_bucket=event.surprise_bucket.value,
            guidance_bucket=event.guidance_bucket.value,
            filing_type=event.filing_subtype,
            raw_hash=event.raw_hash,
            normalized_hash=event.normalized_hash,
            data_version=event.data_version,
            provenance=self._provenance(
                source_name=event.source_name,
                observed_at=event.published_at,
            ),
        )

    def _provenance(self, *, source_name: str, observed_at) -> Provenance:
        return Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name=source_name,
            observed_at=observed_at,
            confidence=0.9,
        )
