"""Tests for the portfolio risk explainer."""
from __future__ import annotations

from investment_research.agent.portfolio_risk import PortfolioRiskExplainer


def _holdings():
    return [
        {"ticker": "600519", "name": "示例白酒", "value": 60000, "industry": "消费"},
        {"ticker": "300750", "name": "示例电池", "value": 30000, "industry": "新能源"},
        {"ticker": "000858", "name": "示例食饮", "value": 10000, "industry": "消费"},
    ]


def test_explains_concentration_industry_and_missing_info() -> None:
    explanation = PortfolioRiskExplainer().explain(_holdings(), portfolio_name="演示组合")
    assert "演示组合" in explanation.concentration
    assert "集中度最高" in explanation.concentration
    assert "消费" in explanation.concentration
    assert "景气度" in explanation.possible_impact
    assert "行业归属" in explanation.missing_info or "持仓" in explanation.missing_info


def test_does_not_produce_rebalancing_instruction() -> None:
    explanation = PortfolioRiskExplainer().explain(_holdings())
    assert explanation.has_rebalancing_instruction is False
    text = f"{explanation.concentration} {explanation.possible_impact} {explanation.missing_info}"
    for forbidden in ("建议买入", "建议卖出", "加仓", "减仓", "调仓至", "仓位应", "目标仓位"):
        assert forbidden not in text, forbidden


def test_scenarios_are_examples_not_predictions() -> None:
    explanation = PortfolioRiskExplainer().explain(_holdings())
    assert explanation.scenarios
    for scenario in explanation.scenarios:
        assert scenario.is_example is True
        assert "示例" in scenario.description
        assert "不是预测结果" in scenario.description


def test_empty_portfolio_reports_missing_not_zero_risk() -> None:
    explanation = PortfolioRiskExplainer().explain(None)
    assert "不足" in explanation.concentration or "未配置" in explanation.concentration
    text = f"{explanation.concentration} {explanation.possible_impact} {explanation.missing_info}"
    assert "零风险" not in text and "无风险" not in text


def test_missing_industry_flagged_as_incomplete() -> None:
    holdings = _holdings()
    holdings[2] = {"ticker": "000858", "name": "示例食饮", "value": 10000}  # no industry
    explanation = PortfolioRiskExplainer().explain(holdings)
    assert "未分类" in explanation.industry_concentration or "行业归属" in explanation.missing_info
