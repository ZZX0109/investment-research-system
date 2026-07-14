from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from investment_research.training.real_data import LocalJsonCache, RealDataSourceHub


class StubPriceFetcher:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def fetch_price_rows(self, symbol: str, *, start: date, end: date):
        self.calls += 1
        return self.rows


class StubFilingFetcher:
    def fetch_filings(self, symbol: str, *, start: date, end: date):
        return [
            {
                "form": "10-Q",
                "acceptance_datetime": "2026-01-28T21:00:00+00:00",
                "accession_number": "sec-1",
            }
        ]


class StubAnnouncementFetcher:
    def fetch_announcements(self, symbol: str, *, start: date, end: date):
        return [
            {
                "title": "公告",
                "公告时间": "2026-01-28T19:00:00+08:00",
                "id": "cn-1",
            }
        ]


class StubNewsFetcher:
    def fetch_news(self, symbol: str, *, start: date, end: date):
        return [
            {
                "headline": "headline",
                "published_at": "2026-01-28T20:00:00+00:00",
                "id": "news-1",
            }
        ]


def _us_rows(*, base: float = 100.0, step: float = 1.0):
    return [
        {
            "date": f"2026-01-{day:02d}",
            "open": base + day * step,
            "high": base + 1 + day * step,
            "low": base - 1 + day * step,
            "close": base + day * step,
            "adj_close": base + day * step,
            "volume": 1000 + day,
            "published_at": f"2026-01-{day:02d}T21:00:00+00:00",
        }
        for day in range(1, 31)
    ]


def _cn_rows():
    return [
        {
            "日期": f"2026-01-{day:02d}",
            "开盘": 4000 + day,
            "最高": 4010 + day,
            "最低": 3990 + day,
            "收盘": 4000 + day,
            "复权收盘": 4000 + day,
            "成交量": 1200000 + day,
            "fx_rate_to_usd": 0.14,
            "更新时间": f"2026-01-{day:02d}T15:00:00+08:00",
        }
        for day in range(1, 31)
    ]


def test_real_data_hub_builds_bundle_and_uses_cache(tmp_path: Path) -> None:
    us_fetcher = StubPriceFetcher(_us_rows())
    cn_fetcher = StubPriceFetcher(_cn_rows())
    hub = RealDataSourceHub(
        us_price_fetcher=us_fetcher,
        cn_price_fetcher=cn_fetcher,
        sec_filing_fetcher=StubFilingFetcher(),
        news_fetcher=StubNewsFetcher(),
        cn_announcement_fetcher=StubAnnouncementFetcher(),
        cache=LocalJsonCache(tmp_path / "cache"),
    )

    bundle = hub.build_bundle("AAPL", start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert bundle.price_bars
    assert bundle.events
    assert us_fetcher.calls == 1
    second = hub.build_bundle("AAPL", start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert second.price_bars
    assert us_fetcher.calls == 1


def test_cache_manifest_distinguishes_fresh_stale_and_expired(tmp_path: Path) -> None:
    cache = LocalJsonCache(tmp_path / "cache")
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    cache.store(symbol="600519.SH", artifact="prices", rows=[{"close": 10}], provider="research", fetched_at=now, ttl=timedelta(minutes=1))
    assert cache.inspect(symbol="600519.SH", artifact="prices", now=now).state == "fresh"
    assert cache.inspect(symbol="600519.SH", artifact="prices", now=now + timedelta(minutes=2)).state == "stale_usable"
    assert cache.inspect(symbol="600519.SH", artifact="prices", now=now + timedelta(days=4)).state == "expired"

def test_real_data_hub_builds_training_samples_from_real_bundle(tmp_path: Path) -> None:
    hub = RealDataSourceHub(
        us_price_fetcher=StubPriceFetcher(_us_rows()),
        cn_price_fetcher=StubPriceFetcher(_cn_rows()),
        sec_filing_fetcher=StubFilingFetcher(),
        news_fetcher=StubNewsFetcher(),
        cache=LocalJsonCache(tmp_path / "cache"),
    )

    hub.us_price_fetcher = StubPriceFetcher(_us_rows(base=300.0, step=0.5))
    benchmark_bundle = hub.build_bundle("QQQ", start=date(2026, 1, 1), end=date(2026, 1, 31))
    hub.us_price_fetcher = StubPriceFetcher(_us_rows(base=250.0, step=0.3))
    sector_reference_bundle = hub.build_bundle("XLK", start=date(2026, 1, 1), end=date(2026, 1, 31))
    hub.us_price_fetcher = StubPriceFetcher(_us_rows(base=280.0, step=0.4))
    style_reference_bundle = hub.build_bundle("QQQ", start=date(2026, 1, 1), end=date(2026, 1, 31))
    hub.us_price_fetcher = StubPriceFetcher(_us_rows())
    samples = hub.build_training_samples(
        "AAPL",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        feature_version="f-v1",
        data_version="d-v1",
        benchmark_bundle=benchmark_bundle,
        sector_reference_bundle=sector_reference_bundle,
        style_reference_bundle=style_reference_bundle,
    )

    assert samples
    assert samples[-1].features["relative_strength_20d"] != 0.0
    assert samples[-1].features["sector_relative_strength_20d"] != 0.0
    assert samples[-1].features["style_relative_strength_20d"] != 0.0


def test_akshare_fetcher_uses_preset_type_for_sz_etf_and_index(monkeypatch) -> None:
    captured: list[tuple[str, str]] = []

    class FakeFrame:
        columns = []

        def __init__(self, *, empty: bool = True):
            self.empty = empty

        def iterrows(self):
            return iter([])

    class FakeAk:
        @staticmethod
        def fund_etf_hist_em(symbol: str, **kwargs):
            captured.append(("etf", symbol))
            return FakeFrame()

        @staticmethod
        def index_zh_a_hist(symbol: str, **kwargs):
            captured.append(("index", symbol))
            return FakeFrame()

        @staticmethod
        def stock_zh_index_daily(symbol: str, **kwargs):
            captured.append(("index_daily", symbol))
            return FakeFrame(empty=False)

        @staticmethod
        def stock_zh_index_daily_tx(symbol: str, **kwargs):
            captured.append(("index_daily_tx", symbol))
            return FakeFrame()

        @staticmethod
        def stock_zh_index_hist_csindex(symbol: str, **kwargs):
            captured.append(("index_csindex", symbol))
            return FakeFrame()

        @staticmethod
        def stock_zh_a_hist(symbol: str, **kwargs):
            captured.append(("stock", symbol))
            return FakeFrame()

    import sys
    import types

    sys.modules["akshare"] = types.SimpleNamespace(
        fund_etf_hist_em=FakeAk.fund_etf_hist_em,
        index_zh_a_hist=FakeAk.index_zh_a_hist,
        stock_zh_index_daily=FakeAk.stock_zh_index_daily,
        stock_zh_index_daily_tx=FakeAk.stock_zh_index_daily_tx,
        stock_zh_index_hist_csindex=FakeAk.stock_zh_index_hist_csindex,
        stock_zh_a_hist=FakeAk.stock_zh_a_hist,
    )
    try:
        from investment_research.training.real_data import AksharePriceFetcher

        fetcher = AksharePriceFetcher()
        fetcher.fetch_price_rows("159919.SZ", start=date(2026, 1, 1), end=date(2026, 1, 31))
        fetcher.fetch_price_rows("399006.SZ", start=date(2026, 1, 1), end=date(2026, 1, 31))
    finally:
        sys.modules.pop("akshare", None)

    assert ("etf", "159919") in captured
    assert ("index", "399006") in captured
    assert ("index_daily", "sz399006") in captured
