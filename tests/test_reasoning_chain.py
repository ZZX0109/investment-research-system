"""Tests for the causal reasoning chain (Phase 7).

Guards the "label-pasting, not analysis" hardening: each causal observation
references at least two evidence items and at least one invalidation
condition, contains no trade instruction, and the conflict/horizon-disagreement
case surfaces arbitration rather than silently picking a side.
"""
from __future__ import annotations

from investment_research.agent.plain_answer import PlainReadingObservation
from investment_research.agent.reasoning_chain import ReasoningChainBuilder


def _observation(*, horizon: str, label: str, tendency: str) -> PlainReadingObservation:
    return PlainReadingObservation(
        horizon=horizon, label=label, tendency=tendency,
        interpretation=f"{label}{tendency}", available=True,
        data_as_of=None,
    )


def test_quality_and_soft_240d_produces_cyclical_peak_observation() -> None:
    builder = ReasoningChainBuilder()
    observations = [
        _observation(horizon="约 6 个月", label="相对基准", tendency="偏强"),
        _observation(horizon="约 12 个月", label="相对基准", tendency="偏弱"),
        _observation(horizon="约 6 个月", label="潜在下跌幅度", tendency="偏小"),
    ]
    result = builder.build(
        scorecard={
            "long_term_quality": "约 72（偏稳）",
            "valuation_position": "偏高",
            "long_term_risk": "中等",
        },
        observations=observations,
        fact_cards=None,
        line_items=[{"metric": "revenue", "yoy_pct": 5.0}, {"metric": "gross_margin", "yoy_pct": 0.2}],
        arbitrations=None,
    )
    assert result
    first = result[0]
    assert "周期高点" in first.observation
    assert len(first.evidence_refs) >= 2
    assert first.invalidation_refs
    # No trade instruction.
    assert not any(word in first.observation for word in ("买入", "卖出", "目标价", "加仓", "减仓"))


def test_margin_pressure_and_contrary_ops_produces_stability_observation() -> None:
    builder = ReasoningChainBuilder()
    result = builder.build(
        scorecard={"long_term_quality": "约 60（一般）", "valuation_position": "中等", "long_term_risk": "偏高"},
        observations=[_observation(horizon="约 12 个月", label="相对基准", tendency="偏弱")],
        fact_cards=[{"stance": "contrary", "topic": "经营", "claim": "毛利率较上年回落"}],
        line_items=[{"metric": "gross_margin", "yoy_pct": -1.5}],
        arbitrations=None,
    )
    stability = next((o for o in result if "盈利稳定" in o.observation), None)
    assert stability is not None
    assert any("毛利率" in ref for ref in stability.evidence_refs)
    assert stability.invalidation_refs


def test_horizon_disagreement_surfaces_conflict_not_silent_pick() -> None:
    builder = ReasoningChainBuilder()
    observations = [
        _observation(horizon="约 6 个月", label="相对基准", tendency="偏强"),
        _observation(horizon="约 12 个月", label="相对基准", tendency="偏弱"),
    ]
    result = builder.build(
        scorecard={"long_term_quality": "约 70（偏稳）"},
        observations=observations,
        fact_cards=[{"stance": "uncertain", "topic": "行业", "claim": "行业景气度存在分歧"}],
        line_items=None,
        arbitrations=None,
    )
    conflict = next((o for o in result if "分歧" in o.observation), None)
    assert conflict is not None
    assert "不下方向性结论" in conflict.observation
    assert len(conflict.evidence_refs) >= 2


def test_insufficient_evidence_yields_safe_placeholder() -> None:
    builder = ReasoningChainBuilder()
    result = builder.build(
        scorecard=None, observations=[], fact_cards=None, line_items=None, arbitrations=None,
    )
    assert len(result) == 1
    assert "不足以形成因果观察" in result[0].observation
    assert result[0].invalidation_refs
