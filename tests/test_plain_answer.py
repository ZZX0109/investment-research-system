"""Tests for the plain-language answer formatter.

These guard the product rules a competition judge cares about:

* no q10/q50/q90 quantiles reach the user-facing answer
* the four readings are translated into neutral observation wording
* the answer never contains buy/sell/position/target-price/guaranteed-return
* conflicts and missing evidence are stated explicitly
* every answer ends with a sources + data-date section
"""
from __future__ import annotations

from investment_research.agent.plain_answer import PlainAnswerBuilder


def _builder() -> PlainAnswerBuilder:
    return PlainAnswerBuilder()


def _full_readings() -> dict[str, dict[str, object]]:
    return {
        "excess_return_120d": {
            "q10": -0.08, "q50": 0.06, "q90": 0.18,
            "horizon_days": 120, "data_as_of": "2026-08-15",
            "artifact_hash": "a" * 64,
        },
        "excess_return_240d": {
            "q10": -0.10, "q50": -0.05, "q90": 0.12,
            "horizon_days": 240, "data_as_of": "2026-08-15",
            "artifact_hash": "b" * 64,
        },
        "future_max_drawdown_120d": {
            "q10": -0.20, "q50": -0.14, "q90": -0.05,
            "horizon_days": 120, "data_as_of": "2026-08-15",
            "artifact_hash": "c" * 64,
        },
        "future_max_drawdown_240d": {
            "q10": -0.30, "q50": -0.18, "q90": -0.06,
            "horizon_days": 240, "data_as_of": "2026-08-15",
            "artifact_hash": "d" * 64,
        },
    }


def _full_scorecard() -> dict[str, object]:
    return {
        "long_term_quality": 72.0,
        "growth_stability": 60.0,
        "valuation_position": 58.0,
        "shareholder_return": 65.0,
        "long_term_risk": 40.0,
        "evidence_completeness": 82.0,
        "as_of_date": "2026-08-15",
    }


def test_translates_four_readings_without_quantiles() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营怎么样",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts={"latest_close": 1680.0, "trade_date": "2026-08-15"},
        data_as_of="2026-08-15",
    )
    labels = {item.label for item in answer.long_term_observations}
    assert "相对基准的长期表现观察" in labels
    assert "潜在下跌幅度观察" in labels
    # The neutral observation wording must be present.
    text = _all_text(answer)
    assert "相对基准的长期表现观察" in text
    assert "潜在下跌幅度观察" in text
    # Quantiles must NEVER appear in the user-facing answer.
    for forbidden in ("q10", "q50", "q90", "P10", "P50", "P90", "低位", "中位", "高位"):
        assert forbidden not in text, forbidden


def test_no_trade_instructions_in_any_section() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="能不能买入",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    assert answer.compliance_allowed is True
    text = _all_text(answer)
    for forbidden in ("买入", "卖出", "加仓", "减仓", "目标价", "保证收益", "稳赚", "必涨"):
        assert forbidden not in text, forbidden


def test_missing_readings_produce_insufficient_evidence_status() -> None:
    readings = _full_readings()
    del readings["future_max_drawdown_240d"]
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    assert answer.result_status == "insufficient_evidence"
    assert "尚未生成" in answer.missing_evidence
    assert any(not item.available for item in answer.long_term_observations)


def test_conflict_between_knowledge_and_web_is_detected() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营变化",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=[{"snippet": "公司净利润同比增长，盈利改善", "document": {"title": "季报", "source_name": "知识库", "source_url": "https://kb.example/1", "published_at": "2026-06-30"}, "citation_id": "kb:1"}],
        web_results=[{"title": "行业承压", "source": "新闻", "url": "https://news.example/1", "published_at": "2026-08-10", "snippet": "公司利润下滑，行业承压"}],
        price_facts=None, data_as_of="2026-08-15",
    )
    assert answer.result_status == "conflict_present"
    assert any(item.classification == "conflict" for item in answer.evidence)


def test_sources_section_lists_materials_and_data_date() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="风险",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=[{"snippet": "分红稳定", "document": {"title": "公司资料", "source_name": "知识库", "source_url": "https://kb.example/2", "published_at": "2026-06-30"}, "citation_id": "kb:2"}],
        web_results=[{"title": "最新公告", "source": "交易所", "url": "https://exchange.example/1", "published_at": "2026-08-12", "snippet": "发布中期报告"}],
        price_facts=None, data_as_of="2026-08-15",
    )
    assert "数据截至 2026-08-15" in answer.sources_summary
    assert answer.sources
    assert any(item.kind == "news" for item in answer.sources)
    assert any(item.kind == "knowledge" for item in answer.sources)
    assert all(item.url for item in answer.sources)


def test_no_scorecard_does_not_fabricate_business_conclusion() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营情况",
        scorecard=None, model_readings=None,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of=None,
    )
    assert answer.result_status == "insufficient_evidence"
    assert "缺少" in answer.business_condition or "尚未" in answer.business_condition
    assert "不强行下结论" in answer.business_condition


def test_drawdown_described_as_observation_not_prediction() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="风险",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    text = _all_text(answer)
    assert "潜在下跌幅度观察" in text
    # Must not be sold as a fall prediction or sell signal.
    assert "卖出信号" not in text
    assert "必跌" not in text


def test_portfolio_note_is_explanation_not_rebalance() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="组合影响",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        portfolio_note={"concentration": "组合集中在消费与新能源", "possible_impact": "可能受行业景气度影响", "missing_info": "需补充持仓明细"},
    )
    assert answer.portfolio_note is not None
    assert "消费" in answer.portfolio_note.concentration
    text = _all_text(answer)
    assert "调仓" not in text and "仓位指令" not in text


def _all_text(answer) -> str:
    return " ".join([
        answer.business_condition,
        answer.long_term_changes,
        answer.possible_risks,
        answer.missing_evidence,
        answer.sources_summary,
        " ".join(item.text for item in answer.evidence),
        " ".join(item.interpretation for item in answer.long_term_observations),
    ])
