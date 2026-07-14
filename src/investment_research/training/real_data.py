from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Protocol

from pydantic import BaseModel

from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.models import (
    CanonicalDatasetBundle,
    PointInTimeEvent,
    TrainingSample,
)
from investment_research.training.source_rows import (
    AksharePriceRow,
    CnAnnouncementRow,
    JsonObject,
    NewsRow,
    ProviderEventRow,
    ProviderPriceRow,
    ProviderRowInput,
    SecFilingRow,
    YFinancePriceRow,
)
from investment_research.training.sources import (
    build_instrument_from_symbol,
    normalize_akshare_rows,
    normalize_cn_announcements,
    normalize_news_rows,
    normalize_sec_filings,
    normalize_yfinance_rows,
    resolve_coverage_preset,
)


class OptionalDependencyError(RuntimeError):
    pass


class PriceHistoryFetcher(Protocol):
    def fetch_price_rows(self, symbol: str, *, start: date, end: date) -> list[ProviderPriceRow | ProviderRowInput]:
        ...


class FilingFetcher(Protocol):
    def fetch_filings(self, symbol: str, *, start: date, end: date) -> list[SecFilingRow | ProviderRowInput]:
        ...


class AnnouncementFetcher(Protocol):
    def fetch_announcements(self, symbol: str, *, start: date, end: date) -> list[CnAnnouncementRow | ProviderRowInput]:
        ...


class NewsFetcher(Protocol):
    def fetch_news(self, symbol: str, *, start: date, end: date) -> list[NewsRow | ProviderRowInput]:
        ...


class CacheManifest(BaseModel):
    provider: str
    fetched_at: datetime
    latest_source_time: datetime
    coverage_start: date | None = None
    coverage_end: date | None = None
    quality_status: str = "passed"
    expires_at: datetime


class CacheRead(BaseModel):
    state: str
    rows: list[JsonObject] = []
    manifest: CacheManifest | None = None


class LocalJsonCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def inspect(self, *, symbol: str, artifact: str, now: datetime | None = None) -> CacheRead:
        path = self._path(symbol=symbol, artifact=artifact)
        if not path.exists():
            return CacheRead(state="unavailable")
        manifest_path = self._manifest_path(symbol=symbol, artifact=artifact)
        if not manifest_path.exists():
            return CacheRead(state="expired")
        rows = json.loads(path.read_text(encoding="utf-8"))
        manifest = CacheManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        current = now or datetime.now(timezone.utc)
        expires_at = manifest.expires_at if manifest.expires_at.tzinfo else manifest.expires_at.replace(tzinfo=timezone.utc)
        if current <= expires_at and manifest.quality_status in {"passed", "degraded"}:
            state = "fresh"
        elif manifest.quality_status in {"passed", "degraded"} and current <= expires_at + self._stale_grace(artifact):
            state = "stale_usable"
        else:
            state = "expired"
        return CacheRead(state=state, rows=rows if isinstance(rows, list) else [], manifest=manifest)

    def load(self, *, symbol: str, artifact: str) -> list[JsonObject] | None:
        result = self.inspect(symbol=symbol, artifact=artifact)
        return result.rows if result.state in {"fresh", "stale_usable"} else None

    def store(
        self,
        *,
        symbol: str,
        artifact: str,
        rows: Iterable[ProviderRowInput],
        provider: str = "unknown",
        fetched_at: datetime | None = None,
        latest_source_time: datetime | None = None,
        coverage_start: date | None = None,
        coverage_end: date | None = None,
        quality_status: str = "passed",
        ttl: timedelta | None = None,
    ) -> None:
        resolved_rows = [_row_to_json(row) for row in rows]
        path = self._path(symbol=symbol, artifact=artifact)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(resolved_rows, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        observed = fetched_at or datetime.now(timezone.utc)
        manifest = CacheManifest(
            provider=provider,
            fetched_at=observed,
            latest_source_time=latest_source_time or observed,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            quality_status=quality_status,
            expires_at=observed + (ttl or self._default_ttl(artifact)),
        )
        self._manifest_path(symbol=symbol, artifact=artifact).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def _path(self, *, symbol: str, artifact: str) -> Path:
        safe_symbol = symbol.replace("/", "_")
        return self.root / safe_symbol / f"{artifact}.json"

    def _manifest_path(self, *, symbol: str, artifact: str) -> Path:
        return self._path(symbol=symbol, artifact=artifact).with_suffix(".meta.json")

    @staticmethod
    def _default_ttl(artifact: str) -> timedelta:
        return timedelta(seconds=15) if artifact in {"snapshots", "quotes"} else timedelta(hours=20) if artifact == "prices" else timedelta(minutes=15)

    @staticmethod
    def _stale_grace(artifact: str) -> timedelta:
        return timedelta(minutes=5) if artifact in {"snapshots", "quotes"} else timedelta(days=3)


@dataclass
class RealDataSourceHub:
    us_price_fetcher: PriceHistoryFetcher
    cn_price_fetcher: PriceHistoryFetcher
    sec_filing_fetcher: FilingFetcher | None = None
    cn_announcement_fetcher: AnnouncementFetcher | None = None
    news_fetcher: NewsFetcher | None = None
    cache: LocalJsonCache | None = None

    def build_bundle(self, symbol: str, *, start: date, end: date) -> CanonicalDatasetBundle:
        preset = resolve_coverage_preset(symbol)
        if preset.market.value == "us":
            price_rows = self._cached_or_fetch(symbol=preset.symbol, artifact="prices", fetch=lambda: self.us_price_fetcher.fetch_price_rows(preset.symbol, start=start, end=end))
            bundle = normalize_yfinance_rows(preset.symbol, price_rows)
            filing_rows = self._fetch_optional_rows(symbol=preset.symbol, artifact="filings", fetcher=self.sec_filing_fetcher, fetch_name="fetch_filings", start=start, end=end)
            bundle.events.extend(normalize_sec_filings(preset.symbol, filing_rows))
        else:
            price_rows = self._cached_or_fetch(symbol=preset.symbol, artifact="prices", fetch=lambda: self.cn_price_fetcher.fetch_price_rows(preset.symbol, start=start, end=end))
            bundle = normalize_akshare_rows(preset.symbol, price_rows)
            announcement_rows = self._fetch_optional_rows(symbol=preset.symbol, artifact="announcements", fetcher=self.cn_announcement_fetcher, fetch_name="fetch_announcements", start=start, end=end)
            bundle.events.extend(normalize_cn_announcements(preset.symbol, announcement_rows))

        news_rows = self._fetch_optional_rows(symbol=preset.symbol, artifact="news", fetcher=self.news_fetcher, fetch_name="fetch_news", start=start, end=end)
        bundle.events.extend(normalize_news_rows(preset.symbol, news_rows))
        bundle.coverage_notes.append(f"Event coverage count={len(bundle.events)}")
        return bundle

    def build_training_samples(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        feature_version: str,
        data_version: str,
        benchmark_bundle: CanonicalDatasetBundle | None = None,
        sector_reference_bundle: CanonicalDatasetBundle | None = None,
        style_reference_bundle: CanonicalDatasetBundle | None = None,
    ) -> list[TrainingSample]:
        bundle = self.build_bundle(symbol, start=start, end=end)
        instrument = build_instrument_from_symbol(symbol)
        builder = TrainingDatasetBuilder(feature_version=feature_version, data_version=data_version)
        benchmark_bars = [] if benchmark_bundle is None else benchmark_bundle.price_bars  # type: ignore[arg-type]
        from investment_research.training.data_quality import prepare_price_bars
        from investment_research.training.models import DataQualityRuleSet

        prepared_bars, issues = prepare_price_bars(bundle.price_bars, rules=DataQualityRuleSet())
        if issues:
            bundle.coverage_notes.extend(f"{issue.code}:{issue.message}" for issue in issues)

        prepared_benchmark = []
        if benchmark_bundle is not None:
            prepared_benchmark, benchmark_issues = prepare_price_bars(benchmark_bundle.price_bars, rules=DataQualityRuleSet())
            if benchmark_issues:
                bundle.coverage_notes.extend(f"benchmark-{issue.code}:{issue.message}" for issue in benchmark_issues)
        prepared_sector_reference = []
        if sector_reference_bundle is not None:
            prepared_sector_reference, sector_issues = prepare_price_bars(
                sector_reference_bundle.price_bars,
                rules=DataQualityRuleSet(),
            )
            if sector_issues:
                bundle.coverage_notes.extend(f"sector-reference-{issue.code}:{issue.message}" for issue in sector_issues)
        prepared_style_reference = []
        if style_reference_bundle is not None:
            prepared_style_reference, style_issues = prepare_price_bars(
                style_reference_bundle.price_bars,
                rules=DataQualityRuleSet(),
            )
            if style_issues:
                bundle.coverage_notes.extend(f"style-reference-{issue.code}:{issue.message}" for issue in style_issues)
        return builder.build_samples(
            instrument=instrument,
            price_bars=prepared_bars,
            benchmark_bars=prepared_benchmark,
            sector_reference_bars=prepared_sector_reference,
            style_reference_bars=prepared_style_reference,
            events=bundle.events,
        )

    def _cached_or_fetch(self, *, symbol: str, artifact: str, fetch) -> list[ProviderRowInput]:
        if self.cache is not None:
            cached = self.cache.load(symbol=symbol, artifact=artifact)
            if cached is not None:
                return cached
        rows = fetch()
        if self.cache is not None:
            self.cache.store(
                symbol=symbol,
                artifact=artifact,
                rows=rows,
                provider=type(self.us_price_fetcher if resolve_coverage_preset(symbol).market.value == "us" else self.cn_price_fetcher).__name__,
            )
        return rows

    def _fetch_optional_rows(
        self,
        *,
        symbol: str,
        artifact: str,
        fetcher,
        fetch_name: str,
        start: date,
        end: date,
    ) -> list[ProviderRowInput]:
        if fetcher is None:
            return []
        return self._cached_or_fetch(
            symbol=symbol,
            artifact=artifact,
            fetch=lambda: getattr(fetcher, fetch_name)(symbol, start=start, end=end),
        )


class YFinancePriceFetcher:
    def fetch_price_rows(self, symbol: str, *, start: date, end: date) -> list[YFinancePriceRow]:
        try:
            import yfinance as yf  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise OptionalDependencyError("yfinance is required for US market price fetches") from exc

        history = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=False)
        rows: list[YFinancePriceRow] = []
        for index, row in history.iterrows():
            published_at = index.to_pydatetime() if hasattr(index, "to_pydatetime") else datetime.fromisoformat(str(index))
            rows.append(
                YFinancePriceRow(
                    trade_date=published_at.date().isoformat(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    adj_close=None if "Adj Close" not in row else float(row["Adj Close"]),
                    volume=None if "Volume" not in row else float(row["Volume"]),
                    published_at=published_at.isoformat(),
                )
            )
        return rows


class AksharePriceFetcher:
    def fetch_price_rows(self, symbol: str, *, start: date, end: date) -> list[AksharePriceRow]:
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise OptionalDependencyError("akshare is required for CN market price fetches") from exc

        preset = resolve_coverage_preset(symbol)
        normalized = symbol.replace(".SH", "").replace(".SZ", "")
        if preset.instrument_type.value == "index":
            frame = _fetch_cn_index_frame(ak, normalized=normalized, start=start, end=end)
        elif preset.instrument_type.value == "etf":
            frame = ak.fund_etf_hist_em(symbol=normalized, period="daily", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
        else:
            frame = ak.stock_zh_a_hist(symbol=normalized, period="daily", start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"), adjust="")
        rows: list[AksharePriceRow] = []
        for _, row in frame.iterrows():
            rows.append(
                AksharePriceRow.model_validate(
                    {key: (value.item() if hasattr(value, "item") else value) for key, value in row.to_dict().items()}
                )
            )
        return rows


def _fetch_cn_index_frame(ak, *, normalized: str, start: date, end: date):
    attempts = [
        (
            "index_zh_a_hist",
            lambda: ak.index_zh_a_hist(
                symbol=normalized,
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            ),
        ),
        ("stock_zh_index_daily", lambda: ak.stock_zh_index_daily(symbol=_cn_index_symbol(normalized))),
        ("stock_zh_index_daily_tx", lambda: ak.stock_zh_index_daily_tx(symbol=_cn_index_symbol(normalized))),
        ("stock_zh_index_hist_csindex", lambda: ak.stock_zh_index_hist_csindex(symbol=normalized)),
    ]
    failures: list[str] = []
    for name, fetch in attempts:
        if not hasattr(ak, name):
            failures.append(f"{name}: unavailable")
            continue
        try:
            frame = fetch()
            frame = _filter_frame_by_date(frame, start=start, end=end)
            if frame is not None and not frame.empty:
                return frame
            failures.append(f"{name}: empty")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    raise RuntimeError(f"Unable to fetch CN index {normalized}: {'; '.join(failures)}")


def _cn_index_symbol(normalized: str) -> str:
    prefix = "sz" if normalized.startswith(("399", "159")) else "sh"
    return f"{prefix}{normalized}"


def _filter_frame_by_date(frame, *, start: date, end: date):
    if frame is None or frame.empty:
        return frame
    date_column = "日期" if "日期" in frame.columns else "date" if "date" in frame.columns else None
    if date_column is None:
        return frame
    import pandas as pd  # type: ignore

    filtered = frame.copy()
    dates = pd.to_datetime(filtered[date_column]).dt.date
    return filtered.loc[(dates >= start) & (dates <= end)].copy()


def _row_to_json(row: ProviderRowInput | ProviderEventRow | ProviderPriceRow) -> JsonObject:
    if hasattr(row, "to_json_object"):
        return row.to_json_object()
    return dict(row)
