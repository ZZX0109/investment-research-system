"""
E2E conftest：共享 fixtures。
"""

import sys
from pathlib import Path
from typing import Generator

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
pytest_plugins = ["backend.tests.conftest"]


@pytest.fixture(scope="function")
def app(test_db_path: str) -> Generator:
    import app as app_module

    original_db = app_module.DB_PATH
    original_market = app_module.try_fetch_market_snapshot
    original_news = app_module.try_fetch_news_events
    original_disclosures = app_module.try_fetch_disclosures
    original_history = app_module.try_fetch_historical_prices

    def fake_market_snapshot(symbol: str, market: str) -> dict:
        return {
            "ok": True,
            "marketValueHint": 123.45 if market == "us" else 88.8,
            "dayChange": 1.23,
            "sourceName": f"e2e-{market}-snapshot",
            "observedAt": app_module.iso(app_module.now_utc()),
            "sourceMeta": app_module.build_source_meta(
                provider=f"e2e-{market}-snapshot",
                as_of=app_module.iso(app_module.now_utc()),
                overrides=[],
                synthetic_ratio=0.0,
            ),
        }

    def fake_news(symbol: str, market: str) -> dict:
        return {
            "ok": True,
            "sourceName": f"e2e-{market}-news",
            "count": 2,
            "articles": [
                {"title": f"{symbol} news headline 1", "url": "https://example.com/1", "publisher": "E2E News", "publishedAt": "2026-07-01T00:00:00Z"},
                {"title": f"{symbol} news headline 2", "url": "https://example.com/2", "publisher": "E2E News", "publishedAt": "2026-07-01T01:00:00Z"},
            ],
        }

    def fake_disclosures(symbol: str, market: str) -> dict:
        return {
            "ok": True,
            "sourceName": f"e2e-{market}-disclosures",
            "count": 1,
            "filings": [
                {
                    "form": "10-Q" if market == "us" else "公告",
                    "filingDate": "2026-06-30",
                    "reportDate": "2026-06-30",
                    "primaryDocument": f"{symbol} quarterly update",
                    "url": "https://example.com/disclosure",
                }
            ],
        }

    def fake_history(symbol: str, market: str | None) -> dict:
        return {"ok": False, "error": "e2e history uses seeded cache", "sourceName": "e2e-history-cache"}

    app_module.DB_PATH = Path(test_db_path)
    app_module.try_fetch_market_snapshot = fake_market_snapshot
    app_module.try_fetch_news_events = fake_news
    app_module.try_fetch_disclosures = fake_disclosures
    app_module.try_fetch_historical_prices = fake_history
    app_module.init_db()
    yield app_module.app
    app_module.DB_PATH = original_db
    app_module.try_fetch_market_snapshot = original_market
    app_module.try_fetch_news_events = original_news
    app_module.try_fetch_disclosures = original_disclosures
    app_module.try_fetch_historical_prices = original_history
