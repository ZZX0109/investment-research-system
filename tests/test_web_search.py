"""Tests for the web-search adapter."""
from __future__ import annotations

import json
from pathlib import Path

from investment_research.agent.web_search import (
    DemoWebSearchProvider,
    WebSearchService,
)


def _write_index(tmp_path: Path, results: list[dict[str, object]]) -> Path:
    index = tmp_path / "web_search_index.json"
    index.write_text(json.dumps({"results": results}, ensure_ascii=False), encoding="utf-8")
    return index


def test_demo_provider_returns_sourced_results(tmp_path: Path) -> None:
    index = _write_index(tmp_path, [
        {"title": "公司发布中期报告", "source": "交易所公告", "url": "https://exchange.example/1", "published_at": "2026-08-12", "snippet": "净利润同比增长", "tags": ["600519"]},
        {"title": "行业景气度跟踪", "source": "研究资讯", "url": "https://news.example/2", "published_at": "2026-08-10", "snippet": "消费板块承压"},
    ])
    provider = DemoWebSearchProvider(index_path=index)
    results = provider.search("公司经营变化", limit=6)
    assert results
    for item in results:
        assert item.title and item.source and item.url
        assert item.mode == "demo"
        assert item.verified is False  # demo results are explanations, not confirmed facts


def test_every_result_has_source_title_date_and_url(tmp_path: Path) -> None:
    index = _write_index(tmp_path, [
        {"title": "监管新规", "source": "证监会", "url": "https://reg.example/1", "published_at": "2026-07-01", "snippet": "提高披露要求"},
    ])
    results = DemoWebSearchProvider(index_path=index).search("监管", limit=6)
    assert results
    item = results[0]
    assert item.title and item.source and item.url and item.published_at


def test_service_degrades_to_demo_when_http_unconfigured(tmp_path: Path) -> None:
    index = _write_index(tmp_path, [
        {"title": "公告", "source": "交易所", "url": "https://exchange.example/1", "published_at": "2026-08-12", "snippet": "披露", "tags": ["600519"]},
    ])
    service = WebSearchService(demo_index=index)
    response = service.search("公司经营", limit=6)
    assert response.mode == "demo"
    assert response.results
    assert response.note == "research_demonstration_index"


def test_empty_query_returns_empty_without_error(tmp_path: Path) -> None:
    index = _write_index(tmp_path, [])
    service = WebSearchService(demo_index=index)
    response = service.search("   ", limit=6)
    assert response.results == []
    assert response.note == "empty_query"


def test_missing_index_returns_empty_not_crash(tmp_path: Path) -> None:
    service = WebSearchService(demo_index=tmp_path / "does-not-exist.json")
    response = service.search("anything", limit=6)
    assert response.results == []


def test_snippets_not_marked_verified(tmp_path: Path) -> None:
    index = _write_index(tmp_path, [
        {"title": "传闻", "source": "博客", "url": "https://blog.example/1", "published_at": "2026-08-10", "snippet": "据传"},
    ])
    results = DemoWebSearchProvider(index_path=index).search("传闻", limit=6)
    assert results and all(not item.verified for item in results)
