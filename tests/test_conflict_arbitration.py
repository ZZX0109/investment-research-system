"""Tests for evidence conflict arbitration (Phase 4).

Guards the "detect but never resolve" hardening: a conflict between a
high-authority official disclosure and a low-authority news blog is arbitrated
toward the disclosure; an equal-authority, equal-recency conflict stays
``unresolved`` and both views are retained.
"""
from __future__ import annotations

from datetime import datetime, timezone

from investment_research.agent.evidence_merge import EvidenceMerger


def _merge(*, knowledge, web, scorecard=None, readings=None):
    return EvidenceMerger().merge(
        knowledge=knowledge, web=web, scorecard=scorecard, readings=readings,
        price_facts=None, abstain_reasons=None,
    )


def test_higher_authority_disclosure_wins_over_news_blog() -> None:
    knowledge = [{
        "snippet": "2025 年净利润同比增长约 8.0%，盈利提升，经营质量保持稳定。",
        "source_name": "交易所公告", "source_url": "https://example-exchange.com/x",
        "published_at": "2026-06-30", "authority_level": 4,
    }]
    web = [{
        "snippet": "某研究称公司盈利下滑、不及预期，前景承压。",
        "source": "博客", "url": "https://example-news.com/x",
        "published_at": "2026-08-01", "verified": False,
    }]
    result = _merge(knowledge=knowledge, web=web)
    assert result.conflict_present
    assert len(result.arbitrations) == 1
    arb = result.arbitrations[0]
    assert arb.resolved_stance == "knowledge"
    assert not arb.unresolved
    assert "权威" in arb.reasoning
    assert arb.authority_basis


def test_equal_authority_equal_recency_stays_unresolved() -> None:
    knowledge = [{
        "snippet": "营收增长、盈利改善。",
        "source_name": "交易所公告", "source_url": "https://example-exchange.com/a",
        "published_at": "2026-06-30", "authority_level": 3,
    }]
    web = [{
        "snippet": "研究称盈利下滑、承压。",
        "source": "研究资讯", "url": "https://example-news.com/a",
        "published_at": "2026-06-30", "verified": False, "authority_level": 3,
    }]
    result = _merge(knowledge=knowledge, web=web)
    assert result.arbitrations
    arb = result.arbitrations[0]
    assert arb.resolved_stance == "unresolved"
    assert arb.unresolved
    assert "保留双方" in arb.reasoning


def test_more_recent_source_wins_when_authority_ties() -> None:
    knowledge = [{
        "snippet": "盈利改善、增长。",
        "source_name": "交易所公告", "source_url": "https://example-exchange.com/b",
        "published_at": "2026-06-30", "authority_level": 3,
    }]
    web = [{
        "snippet": "盈利下滑、不及预期。",
        "source": "交易所公告", "url": "https://example-exchange.com/b2",
        "published_at": "2026-08-10", "verified": True,
    }]
    result = _merge(knowledge=knowledge, web=web)
    arb = result.arbitrations[0]
    assert arb.resolved_stance == "web"
    assert not arb.unresolved
    assert "时效" in arb.reasoning


def test_no_conflict_produces_no_arbitration() -> None:
    knowledge = [{"snippet": "公司经营稳健，分红稳定。",
                  "source_name": "交易所公告", "source_url": "https://example-exchange.com/c",
                  "published_at": "2026-06-30", "authority_level": 4}]
    web = [{"snippet": "公司经营稳健，分红延续。",
            "source": "研究资讯", "url": "https://example-news.com/c",
            "published_at": "2026-07-01", "verified": False}]
    result = _merge(knowledge=knowledge, web=web)
    assert not result.conflict_present
    assert result.arbitrations == []
