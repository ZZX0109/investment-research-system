"""Integration adapter graceful-degradation tests.

The adapters wrap live akshare fetches; in a network-gated research
environment every call must degrade to a typed ``FetchResult(status=...)``
instead of crashing the research run.  These tests pin that contract without
touching the network: akshare is monkeypatched to raise / return canned
frames, and the regime detector is exercised against a mocked kline.
"""
from __future__ import annotations

from typing import Any

import pytest
import pandas as pd

from investment_research.integrations.base import FetchResult, safe_fetch
from investment_research.integrations.fortune.data_services import (
    dragon_tiger,
    fundamental,
    fund_flow,
    margin,
    regime,
)
from investment_research.integrations.xystock import quote_fetcher


# --- base.safe_fetch ------------------------------------------------------

def test_safe_fetch_network_error_is_degraded_not_crash() -> None:
    result = safe_fetch("test", lambda: (_ for _ in ()).throw(TimeoutError("timed out")))
    assert result.ok is False
    assert result.status == "network_unavailable"
    assert result.degraded is True


def test_safe_fetch_empty_is_no_data() -> None:
    result = safe_fetch("test", lambda: [])
    assert result.status == "no_data"
    assert result.degraded is True


def test_safe_fetch_ok_returns_data() -> None:
    result = safe_fetch("test", lambda: [1, 2, 3])
    assert result.ok is True
    assert result.status == "ok"
    assert result.data == [1, 2, 3]


# --- adapter degradation when akshare is network-gated --------------------

@pytest.fixture
def akshare_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every akshare data call raise a network-style timeout."""
    import akshare

    def _raise(*_a: Any, **_k: Any) -> Any:
        raise TimeoutError("Read timed out")

    for fn in (
        "stock_financial_analysis_indicator", "stock_hsgt_individual_em",
        "stock_margin_detail_sse", "stock_margin_detail_szse",
        "stock_lhb_detail_em", "stock_zh_a_spot_em", "stock_zh_a_hist",
        "stock_history_dividend_detail",
    ):
        if hasattr(akshare, fn):
            monkeypatch.setattr(akshare, fn, _raise, raising=False)


def test_fundamentals_degrades_when_akshare_unreachable(
    akshare_unreachable: None,
) -> None:
    result = fundamental.fetch_fundamentals("600519")
    assert result.ok is False
    assert result.status == "network_unavailable"
    assert result.degraded is True


def test_fund_flow_degrades_when_akshare_unreachable(
    akshare_unreachable: None,
) -> None:
    result = fund_flow.fetch_northbound_flow("600519")
    assert result.status == "network_unavailable"
    assert result.degraded is True


def test_quote_degrades_when_akshare_unreachable(
    akshare_unreachable: None,
) -> None:
    result = quote_fetcher.fetch_realtime_quote("600519")
    assert result.status == "network_unavailable"
    assert result.degraded is True


def test_news_and_notices_keep_provider_source_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workbench needs the original provider URL for each clickable item."""

    class FakeAkshare:
        @staticmethod
        def stock_news_em(*, symbol: str) -> pd.DataFrame:
            assert symbol == "600519"
            return pd.DataFrame([{
                "新闻标题": "公司经营发生变化",
                "新闻内容": "摘要",
                "发布时间": "2026-08-20 14:00:00",
                "文章来源": "财经媒体",
                "新闻链接": "https://example.com/news/1",
            }])

        @staticmethod
        def stock_individual_notice_report(**_kwargs: object) -> pd.DataFrame:
            return pd.DataFrame([{
                "公告标题": "公司公告",
                "公告类型": "定期报告",
                "公告日期": "2026-08-20",
                "网址": "https://www.cninfo.com.cn/notice/1",
            }])

    monkeypatch.setattr(quote_fetcher, "_require_akshare", lambda: FakeAkshare())

    news = quote_fetcher.fetch_stock_news("600519")
    notices = quote_fetcher.fetch_stock_notices("600519")

    assert news.available and news.data[0]["url"] == "https://example.com/news/1"
    assert notices.available and notices.data[0]["url"] == "https://www.cninfo.com.cn/notice/1"


def test_margin_degrades_when_akshare_unreachable(
    akshare_unreachable: None,
) -> None:
    result = margin.fetch_margin("600519")
    assert result.status == "network_unavailable"
    assert result.degraded is True


def test_dragon_tiger_degrades_when_akshare_unreachable(
    akshare_unreachable: None,
) -> None:
    result = dragon_tiger.fetch_dragon_tiger("600519")
    assert result.status == "network_unavailable"
    assert result.degraded is True


# --- regime detector (pure, mocked kline) ---------------------------------

def _canned_kline(monkeypatch: pytest.MonkeyPatch, closes: list[float]) -> None:
    """Patch regime's kline source to return a canned close series."""
    bars = [{"close": c, "date": f"2026-01-{i+1:02d}"} for i, c in enumerate(closes)]
    monkeypatch.setattr(
        regime, "fetch_kline",
        lambda symbol, days=30: FetchResult(
            ok=True, status="ok", provider="mock", data=bars,
        ),
    )


def test_regime_bull_when_20d_return_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closes = [10.0] * 19 + [11.0]  # +10% over 20 bars -> bull
    _canned_kline(monkeypatch, closes)
    result = regime.detect_regime("600519")
    assert result.available
    assert result.data["trend"] == "bull"
    assert result.data["ma_position"] in {"above", "below"}


def test_regime_bear_when_20d_return_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closes = [10.0] * 19 + [9.0]  # -10% -> bear
    _canned_kline(monkeypatch, closes)
    result = regime.detect_regime("600519")
    assert result.available
    assert result.data["trend"] == "bear"


def test_regime_passthrough_when_kline_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        regime, "fetch_kline",
        lambda symbol, days=30: FetchResult(
            ok=False, status="network_unavailable", provider="mock",
            error="TimeoutError", degraded=True,
        ),
    )
    result = regime.detect_regime("600519")
    assert result.ok is False
    assert result.status == "network_unavailable"
    assert result.degraded is True


def test_regime_no_data_when_history_too_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _canned_kline(monkeypatch, [10.0, 10.5])  # < 20 bars
    result = regime.detect_regime("600519")
    assert result.status == "no_data"
    assert result.degraded is True
