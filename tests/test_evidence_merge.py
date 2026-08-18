"""Tests for the evidence merger step of the agent tool flow."""
from __future__ import annotations

from investment_research.agent.evidence_merge import EvidenceMerger


def _readings() -> dict[str, dict[str, object]]:
    return {
        "excess_return_120d": {"q50": 0.05, "data_as_of": "2026-08-15", "artifact_hash": "a" * 64},
        "excess_return_240d": {"q50": -0.05, "data_as_of": "2026-08-15", "artifact_hash": "b" * 64},
        "future_max_drawdown_120d": {"q50": -0.14, "data_as_of": "2026-08-15", "artifact_hash": "c" * 64},
        "future_max_drawdown_240d": {"q50": -0.18, "data_as_of": "2026-08-15", "artifact_hash": "d" * 64},
    }


def _scorecard() -> dict[str, object]:
    return {"long_term_quality": 72.0, "long_term_risk": 40.0}


def test_classifies_knowledge_as_confirmed_and_keeps_source() -> None:
    result = EvidenceMerger().merge(
        knowledge=[{"snippet": "公司分红稳定", "document": {"title": "公司资料", "source_name": "知识库", "source_url": "https://kb.example/1", "published_at": "2026-06-30"}, "citation_id": "kb:1"}],
        web=None, readings=_readings(), price_facts=None, scorecard=_scorecard(),
    )
    assert result.confirmed_count >= 1
    assert any(item.classification == "confirmed_fact" for item in result.evidence)
    assert any(item.kind == "knowledge" for item in result.sources)
    assert all(item.url for item in result.sources)


def test_unverified_web_results_are_explanations_not_facts() -> None:
    result = EvidenceMerger().merge(
        knowledge=None,
        web=[{"title": "传闻", "source": "博客", "url": "https://blog.example/1", "published_at": "2026-08-10", "snippet": "据传公司考虑并购"}],
        readings=_readings(), price_facts=None, scorecard=_scorecard(),
    )
    assert result.explanation_count >= 1
    assert all(item.classification != "confirmed_fact" or item.sources[0].kind == "knowledge" for item in result.evidence)


def test_verified_web_results_are_confirmed_facts() -> None:
    result = EvidenceMerger().merge(
        knowledge=None,
        web=[{"title": "监管公告", "source": "交易所", "url": "https://exchange.example/1", "published_at": "2026-08-12", "snippet": "发布中期报告", "verified": True}],
        readings=_readings(), price_facts=None, scorecard=_scorecard(),
    )
    assert result.confirmed_count >= 1


def test_conflict_detected_between_history_and_latest_news() -> None:
    result = EvidenceMerger().merge(
        knowledge=[{"snippet": "净利润同比增长，盈利改善", "document": {"title": "季报", "source_name": "知识库", "source_url": "https://kb.example/2"}}],
        web=[{"title": "行业承压", "source": "新闻", "url": "https://news.example/1", "published_at": "2026-08-10", "snippet": "公司利润下滑"}],
        readings=_readings(), price_facts=None, scorecard=_scorecard(),
    )
    assert result.conflict_present is True
    assert any(item.classification == "conflict" for item in result.evidence)


def test_missing_readings_and_scorecard_marked_as_missing_not_zero_risk() -> None:
    result = EvidenceMerger().merge(
        knowledge=None, web=None, readings=None, price_facts=None, scorecard=None,
    )
    assert result.missing_present is True
    assert any(item.classification == "missing" for item in result.evidence)
    # An empty input must never be turned into a "no risk" conclusion.
    assert not any("无风险" in item.text or "零风险" in item.text for item in result.evidence)


def test_sources_deduplicated_by_url() -> None:
    knowledge = [{"snippet": "a", "document": {"title": "T", "source_name": "S", "source_url": "https://kb.example/1", "published_at": "2026-06-30"}}]
    web = [{"title": "T2", "source": "S2", "url": "https://kb.example/1", "published_at": "2026-08-10", "snippet": "b"}]
    result = EvidenceMerger().merge(knowledge=knowledge, web=web, readings=_readings(), price_facts=None, scorecard=_scorecard())
    urls = [item.url for item in result.sources if item.kind in {"knowledge", "news"}]
    assert urls.count("https://kb.example/1") == 1


def test_model_readings_carry_artifact_source() -> None:
    result = EvidenceMerger().merge(knowledge=None, web=None, readings=_readings(), price_facts=None, scorecard=_scorecard())
    assert any(item.kind == "model" for item in result.sources)
    assert all(item.url.startswith("artifact://") for item in result.sources if item.kind == "model")
