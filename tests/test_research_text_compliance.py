from __future__ import annotations

from investment_research.service.compliance import (
    ResearchTextComplianceChecker,
    ResearchTextCompliancePolicy,
)


def test_blocks_explicit_individual_security_trade_instructions() -> None:
    checker = ResearchTextComplianceChecker()
    cases = {
        "现在可以买入600519。": "DIRECT_BUY_INSTRUCTION",
        "建议卖出该股。": "DIRECT_SELL_INSTRUCTION",
        "600519适合加仓。": "POSITION_INCREASE_INSTRUCTION",
        "建议对该股减仓。": "POSITION_REDUCE_INSTRUCTION",
        "建议继续持有600519。": "HOLD_INSTRUCTION",
    }

    for text, expected in cases.items():
        result = checker.check(text, subject_symbol="600519")
        assert result.allowed is False, text
        assert expected in result.reason_codes, text


def test_blocks_target_price_and_guaranteed_return_claims() -> None:
    checker = ResearchTextComplianceChecker()
    result = checker.check("600519目标价为220元，这个方案保证收益并且稳赚不赔。")

    assert result.allowed is False
    assert "TARGET_PRICE_GUIDANCE" in result.reason_codes
    assert "GUARANTEED_RETURN_CLAIM" in result.reason_codes


def test_allows_explicit_disclaimer_mentions_but_not_disguised_negative_advice() -> None:
    checker = ResearchTextComplianceChecker()
    disclaimer = checker.check(
        "本报告仅供研究，不构成对600519的买入或卖出建议，也不保证收益。",
        subject_symbol="600519",
    )
    standalone_instruction = checker.check(
        "不要买入600519。", subject_symbol="600519",
    )

    assert disclaimer.allowed is True
    assert disclaimer.reason_codes == []
    # A bare individualized command is not made compliant merely by negating
    # the verb.  It needs an actual disclaimer/research-safety context.
    assert standalone_instruction.allowed is False
    assert standalone_instruction.reason_codes == ["DIRECT_BUY_INSTRUCTION"]

    product_boundary = checker.check(
        "系统禁止输出买入建议，不提供目标价，也不承诺保证收益。",
        subject_symbol="600519",
    )
    assert product_boundary.allowed is True


def test_does_not_misclassify_educational_or_corporate_action_language() -> None:
    checker = ResearchTextComplianceChecker()

    educational = checker.check("“买入”和“卖出”是交易术语，本段不涉及任何个股。")
    corporate_action = checker.check(
        "公司拟买入生产设备并卖出闲置资产。", subject_symbol="600519",
    )

    assert educational.allowed is True
    assert corporate_action.allowed is True


def test_policy_version_is_returned_for_audit_records() -> None:
    checker = ResearchTextComplianceChecker(ResearchTextCompliancePolicy(
        policy_version="cn-public-research-text-v2-test",
    ))

    result = checker.check("建议买入600519。", subject_symbol="600519")

    assert result.policy_version == "cn-public-research-text-v2-test"
    assert result.allowed is False
