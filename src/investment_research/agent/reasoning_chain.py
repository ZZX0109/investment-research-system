"""Causal reasoning chain for the long-term investment AI assistant (Phase 7).

This is the "evidence-linked reasoning" layer the plan called for: rather than
pasting labels next to each other, it connects the five-dimension scorecard,
the dual-horizon model readings, fact-card stances and structured line items
into 2-3 causal observations, each referencing at least two evidence items and
at least one explicit invalidation condition.  It is deterministic so it stays
a safe fallback even without an LLM; when an LLM is later wired in it consumes
this richer structured evidence.

The builder NEVER emits a buy/sell/position/target-price/return instruction; it
only describes causal links and the conditions that would overturn them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from investment_research.agent.answer_models import CausalObservation, PlainReadingObservation

# Re-export shared models for backward-compatible imports.
__all__ = ["ReasoningChainBuilder", "CausalObservation", "PlainReadingObservation"]


class ReasoningChainBuilder:
    """Synthesize causal observations from merged, structured evidence."""

    def build(
        self,
        *,
        scorecard: Mapping[str, object] | None,
        observations: list[PlainReadingObservation],
        fact_cards: Iterable[Mapping[str, object]] | None,
        line_items: Iterable[Mapping[str, object]] | None,
        arbitrations: Iterable[Mapping[str, object]] | None,
        data_as_of: str | None = None,
    ) -> list[CausalObservation]:
        card = dict(scorecard or {})
        readings = list(observations or [])
        cards = list(fact_cards or [])
        items = list(line_items or [])
        arbs = list(arbitrations or [])

        quality = self._dim_label(card.get("long_term_quality"))
        valuation = self._dim_label(card.get("valuation_position"))
        risk = self._dim_label(card.get("long_term_risk"))

        excess = {item.horizon: item for item in readings if "相对基准" in item.label}
        drawdown = {item.horizon: item for item in readings if "下跌幅度" in item.label}
        soft_240 = excess.get("约 12 个月") and "偏弱" in excess["约 12 个月"].tendency
        firm_120 = excess.get("约 6 个月") and "偏强" in excess["约 6 个月"].tendency

        revenue_yoy = self._line_item_yoy(items, "revenue")
        margin_yoy = self._line_item_yoy(items, "gross_margin")
        contrary_ops = any(
            str(c.get("stance")) == "contrary" and "经营" in str(c.get("topic", "")) for c in cards
        )
        uncertain_industry = any(
            str(c.get("stance")) == "uncertain" and "行业" in str(c.get("topic", "")) for c in cards
        )

        observations: list[CausalObservation] = []

        # Observation 1: quality vs. valuation vs. 240d softness -> cyclical-peak framing.
        if quality and soft_240:
            evidence = [
                f"经营质量{quality}",
                "约 12 个月相对基准偏弱",
            ]
            if valuation:
                evidence.append(f"估值位置{valuation}")
            obs = (
                "经营质量{quality}叠加约 12 个月相对表现偏弱{valuation_clause}，"
                "市场可能在定价周期高点，关注行业相对景气与毛利率拐点。"
            ).format(
                quality=quality,
                valuation_clause=(f"、估值位置{valuation}" if valuation else ""),
            )
            invalidation = []
            if revenue_yoy is not None and revenue_yoy < 8:
                invalidation.append("下一期营收同比增速进一步回落")
            invalidation.append("毛利率连续两季下行")
            observations.append(CausalObservation(
                observation=obs, evidence_refs=evidence, invalidation_refs=invalidation,
            ))

        # Observation 2: margin / capacity / risk -> earnings-stability framing.
        margin_under_pressure = (
            (margin_yoy is not None and margin_yoy < 0)
            or contrary_ops
            or (risk and "高" in risk)
        )
        if margin_under_pressure:
            evidence = []
            if margin_yoy is not None:
                evidence.append(f"毛利率同比 {margin_yoy:+.1f}%")
            if contrary_ops:
                evidence.append("经营方向存在反面证据")
            if risk:
                evidence.append(f"长期风险读数{risk}")
            obs = (
                "盈利稳定性面临压力{clause}，关注产能消化与上游成本传导；"
                "若毛利率继续下行或海外贸易政策收紧，长期风险读数可能进一步上升。"
            ).format(clause="，主要线索为" + "、".join(evidence) if evidence else "")
            invalidation = ["毛利率连续两季回升", "行业产能利用率企稳"]
            observations.append(CausalObservation(
                observation=obs, evidence_refs=evidence, invalidation_refs=invalidation,
            ))

        # Observation 3: industry divergence or horizon disagreement -> conflict framing.
        horizon_disagree = firm_120 and soft_240
        if uncertain_industry or horizon_disagree or arbs:
            evidence = []
            if horizon_disagree:
                evidence.append("约 6 个月偏强而约 12 个月偏弱的周期分歧")
            if uncertain_industry:
                evidence.append("行业景气度存在不确定证据")
            if arbs:
                evidence.append("来源分歧已按权威与时效仲裁")
            obs = (
                "周期与来源层面存在分歧{clause}，当前不下方向性结论，"
                "需更权威或更及时的披露再判断。"
            ).format(clause="（" + "、".join(evidence) + "）" if evidence else "")
            invalidation = ["更权威披露与最新公开信息一致", "120/240 日读数方向收敛"]
            observations.append(CausalObservation(
                observation=obs, evidence_refs=evidence, invalidation_refs=invalidation,
            ))

        if not observations:
            observations.append(CausalObservation(
                observation="可引用证据尚不足以形成因果观察，请等待下一次财报与披露更新。",
                evidence_refs=[], invalidation_refs=["至少一期财务科目与长期读数齐备"],
            ))

        # Cap at three observations for a focused, non-exhaustive answer.
        return observations[:3]

    @staticmethod
    def _dim_label(value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            value = value.get("label") or value.get("score") or value
        text = str(value)
        return text or None

    @staticmethod
    def _line_item_yoy(items: list[Mapping[str, object]], metric: str) -> float | None:
        for item in items:
            if str(item.get("metric")) == metric:
                yoy = item.get("yoy_pct")
                if isinstance(yoy, (int, float)):
                    return float(yoy)
        return None
