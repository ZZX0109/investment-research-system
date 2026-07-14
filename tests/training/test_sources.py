from datetime import datetime, timezone

from investment_research.training.models import DataProvider, EventDirection, EventType, GuidanceBucket, SurpriseBucket
from investment_research.training.sources import (
    build_instrument_from_symbol,
    infer_event_type,
    infer_guidance_bucket,
    infer_surprise_bucket,
    normalize_akshare_rows,
    normalize_cn_announcements,
    normalize_sec_filings,
    normalize_news_rows,
    normalize_yfinance_rows,
    resolve_coverage_preset,
)


def test_resolve_coverage_preset_supports_us_and_cn_universe() -> None:
    us = resolve_coverage_preset("AAPL")
    cn = resolve_coverage_preset("SH600519")
    us_growth = resolve_coverage_preset("SOXX")
    cn_growth = resolve_coverage_preset("CHINEXT")

    assert us.primary_provider == DataProvider.YFINANCE
    assert cn.symbol == "600519.SH"
    assert us.benchmark_symbol == "^GSPC"
    assert us.sector_reference_symbol == "XLK"
    assert us.style_reference_symbol == "QQQ"
    assert us_growth.benchmark_symbol == "^NDX"
    assert cn_growth.symbol == "399006.SZ"


def test_normalize_yfinance_rows_builds_us_equity_bundle() -> None:
    bundle = normalize_yfinance_rows(
        "AAPL",
        [
            {
                "date": "2026-07-03T00:00:00+00:00",
                "open": 210.0,
                "high": 212.0,
                "low": 208.0,
                "close": 211.0,
                "adj_close": 210.5,
                "volume": 1000000,
                "published_at": "2026-07-03T21:00:00+00:00",
            }
        ],
    )

    assert bundle.instrument.symbol == "AAPL"
    assert bundle.price_bars[0].adjusted_close == 210.5


def test_normalize_akshare_rows_builds_cn_index_bundle() -> None:
    bundle = normalize_akshare_rows(
        "000300.SH",
        [
            {
                "日期": "2026-07-03",
                "开盘": 4000.0,
                "最高": 4050.0,
                "最低": 3980.0,
                "收盘": 4030.0,
                "复权收盘": 4030.0,
                "成交量": 1200000,
                "fx_rate_to_usd": 0.14,
                "更新时间": "2026-07-03T15:30:00+08:00",
            }
        ],
    )

    assert bundle.instrument.symbol == "000300.SH"
    assert bundle.price_bars[0].currency == "CNY"


def test_normalize_filings_and_announcements_keep_point_in_time_fields() -> None:
    sec_events = normalize_sec_filings(
        "AAPL",
        [
            {
                "form": "10-Q",
                "acceptance_datetime": "2026-07-03T20:15:00+00:00",
                "accession_number": "0000001",
                "url": "https://sec.example/10q",
            }
        ],
    )
    cn_events = normalize_cn_announcements(
        "600519.SH",
        [
            {
                "title": "业绩预告",
                "公告时间": "2026-07-03T19:00:00+08:00",
                "id": "cn-1",
                "url": "https://cninfo.example/1",
            }
        ],
    )

    assert sec_events[0].published_at.tzinfo is not None
    assert sec_events[0].payload_ref == "0000001"
    assert cn_events[0].headline == "业绩预告"


def test_structured_event_semantics_extract_direction_surprise_and_guidance() -> None:
    events = normalize_news_rows(
        "AAPL",
        [
            {
                "headline": "Apple cuts guidance after antitrust investigation and misses estimates",
                "published_at": "2026-07-03T20:00:00+00:00",
                "id": "n-risk",
                "url": "https://news.example/risk",
            }
        ],
        provider=DataProvider.NEWSWIRE,
    )

    event = events[0]
    assert event.event_type == EventType.EARNINGS
    assert event.event_direction == EventDirection.NEGATIVE
    assert event.guidance_bucket == GuidanceBucket.CUT
    assert event.surprise_bucket == SurpriseBucket.MISS

    cn_events = normalize_cn_announcements(
        "600519.SH",
        [
            {
                "title": "关于收到监管处罚决定书暨业绩预减的公告",
                "公告时间": "2026-07-03T19:00:00+08:00",
                "id": "cn-risk",
                "url": "https://cninfo.example/risk",
            }
        ],
    )

    assert cn_events[0].event_type == EventType.EARNINGS
    assert cn_events[0].event_direction == EventDirection.NEGATIVE
    assert cn_events[0].guidance_bucket == GuidanceBucket.CUT
    assert cn_events[0].surprise_bucket == SurpriseBucket.MISS
    assert infer_event_type("Discloseable transaction: acquisition of assets") == EventType.MNA
    assert infer_event_type("SEC investigation and regulatory penalty") == EventType.REGULATION
    assert infer_event_type("控制权变更及重大资产重组") == EventType.MNA
    assert infer_event_type("收到行政处罚及退市风险警示") == EventType.REGULATION
    assert infer_guidance_bucket("positive profit alert raises outlook") == GuidanceBucket.RAISE
    assert infer_guidance_bucket("guidance below consensus with margin warning") == GuidanceBucket.CUT
    assert infer_surprise_bucket("big miss below estimates") == SurpriseBucket.BIG_MISS


def test_normalize_price_rows_sanitizes_inconsistent_ohlc() -> None:
    bundle = normalize_yfinance_rows(
        "AAPL",
        [
            {
                "date": "2026-07-03T00:00:00+00:00",
                "open": 100.0,
                "high": 99.0,
                "low": 101.0,
                "close": 102.0,
                "adj_close": 101.5,
                "volume": 1000,
                "published_at": "2026-07-03T21:00:00+00:00",
            }
        ],
    )

    bar = bundle.price_bars[0]
    assert bar.high == 102.0
    assert bar.low == 100.0
