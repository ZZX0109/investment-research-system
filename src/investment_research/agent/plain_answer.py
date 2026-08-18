"""Plain-language answer formatter for the long-term investment AI assistant.

This module is the boundary between the backend's professional evidence
(model readings, scorecards, knowledge citations, web-search results) and the
plain-language answer a retail long-term investor sees on the homepage.

Design rules enforced here (and covered by tests):

* The four long-term model readings are translated into neutral
  "长期表现观察" / "潜在下跌幅度观察" wording.  The raw q10/q50/q90
  quantiles are never placed in the plain answer — they stay in the
  professional details payload.
* No reading is converted into a buy/sell signal, win probability, fixed
  position, target price, or guaranteed return.
* Every fact carries its source; conflicts and missing evidence are stated
  explicitly instead of being smoothed over.
* The answer always ends with a "依据和更新时间" section listing the
  materials, search results, calculation results, and data dates used.

The formatter is deterministic and side-effect free so the same inputs always
produce the same structured answer.  It is the safe fallback even when the LLM
is unavailable.
"""
from __future__ import annotations

from typing import Iterable, Literal, Mapping

from investment_research.agent.evidence_merge import EvidenceMerger
from investment_research.agent.answer_models import (
    CausalObservation,
    EvidenceClass,
    EvidenceItem,
    PlainAnswer,
    PlainPortfolioNote,
    PlainReadingObservation,
    PlainSource,
)
from investment_research.agent.reasoning_chain import ReasoningChainBuilder
from investment_research.service.compliance import ResearchTextComplianceChecker

# Re-export shared models so existing `from investment_research.agent.plain_answer
# import PlainAnswer` imports keep working without churn.
__all__ = [
    "PlainAnswerBuilder",
    "EvidenceClass",
    "EvidenceItem",
    "PlainSource",
    "PlainReadingObservation",
    "PlainPortfolioNote",
    "PlainAnswer",
    "CausalObservation",
]


# The four long-term horizons the platform keeps as backend evidence.  These
# names are internal; users never see them.
_EXCESS_RETURN_TASKS = ("excess_return_120d", "excess_return_240d")
_DRAWDOWN_TASKS = ("future_max_drawdown_120d", "future_max_drawdown_240d")

_HORIZON_LABEL = {
    "excess_return_120d": "约 6 个月",
    "excess_return_240d": "约 12 个月",
    "future_max_drawdown_120d": "约 6 个月",
    "future_max_drawdown_240d": "约 12 个月",
}

# Plain-language tendency thresholds.  These are presentation rules, not model
# outputs, and intentionally coarse so they read as observations rather than
# precise predictions.
_EXCESS_FIRM = 0.04
_EXCESS_SOFT = -0.04
_DRAWDOWN_LARGE = -0.12
_DRAWDOWN_MODERATE = -0.05


class PlainAnswerBuilder:
    """Translate backend evidence into a compliant plain-language answer."""

    def __init__(self, *, compliance: ResearchTextComplianceChecker | None = None) -> None:
        self.compliance = compliance or ResearchTextComplianceChecker()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def build(
        self,
        *,
        symbol: str,
        asset_name: str | None,
        task_text: str,
        scorecard: Mapping[str, object] | None,
        model_readings: Mapping[str, Mapping[str, object]] | None,
        knowledge_results: Iterable[Mapping[str, object]] | None,
        web_results: Iterable[Mapping[str, object]] | None,
        price_facts: Mapping[str, object] | None,
        data_as_of: str | None,
        portfolio_note: Mapping[str, object] | None = None,
        abstain_reasons: Iterable[str] | None = None,
        tools_used: Iterable[str] | None = None,
        fact_cards: Iterable[Mapping[str, object]] | None = None,
        line_items: Iterable[Mapping[str, object]] | None = None,
        generated_by: Literal["llm", "deterministic_fallback"] = "deterministic_fallback",
        causal_observations: Iterable[CausalObservation] | None = None,
        prior_turns: Iterable[Mapping[str, object]] | None = None,
        forecast_note: str | None = None,
    ) -> PlainAnswer:
        """Build the five-section answer.

        ``causal_observations`` lets an AssetSnapshot (Phase 2) pass its
        pre-computed, asset-scoped causal chain straight through instead of
        recomputing it with question-specific arbitrations — so the dashboard
        tile and the AI answer share one causal baseline and never drift on
        how a reading is reasoned about.

        ``prior_turns`` (Phase 3) lets a multi-turn conversation pass the
        session's previous rounds (role + content) so the next answer can
        reference the prior conclusion ("展开刚才...").  Only present for
        conversational runs; the single-turn path leaves it ``None``.

        ``forecast_note`` (Phase 5) is the shared, compliance-safe forecast
        wording from ``frame_prediction_as_observation``; when present it is
        appended to the business-condition section so the AI answer and the
        dashboard tile surface identical forecast language (and it goes through
        the compliance check below, never bypassing it).
        """
        abstain_list = [str(item) for item in (abstain_reasons or []) if item]
        readings = dict(model_readings or {})
        card = dict(scorecard or {})
        knowledge = list(knowledge_results or [])
        web = list(web_results or [])
        price = dict(price_facts or {})

        # Single evidence layer (Phase 1): EvidenceMerger classifies
        # knowledge/web/missing evidence, collects sources, and arbitrates
        # knowledge/web conflicts (authority > recency > corroboration) in one
        # pass.  The builder no longer keeps a parallel _classify_evidence /
        # _collect_sources path that could drift from the merger's
        # classification and conflict detection — the dashboard snapshot
        # (Phase 2) and the AI answer now share exactly one evidence layer.
        merge_result = EvidenceMerger().merge(
            knowledge=knowledge,
            web=web,
            readings=readings,
            price_facts=price,
            scorecard=card,
            abstain_reasons=abstain_list,
        )
        sources = merge_result.sources
        evidence_items = merge_result.evidence
        arbitrations = list(merge_result.arbitrations)
        observations = self._build_observations(readings)
        fundamentals = self._fundamental_dimensions(card)
        portfolio = self._portfolio_note(portfolio_note)

        # Phase 7: causal reasoning links the five-dimension scorecard, the
        # dual-horizon readings, fact-card stances and structured line items
        # into 2-3 causal observations with explicit invalidation conditions.
        # When an AssetSnapshot (Phase 2) supplies a pre-computed causal chain,
        # reuse it verbatim so the dashboard and the AI share one causal
        # baseline instead of recomputing with question-specific arbitrations.
        if causal_observations is not None:
            causal = list(causal_observations)
        else:
            causal = ReasoningChainBuilder().build(
                scorecard=card,
                observations=observations,
                fact_cards=fact_cards,
                line_items=line_items,
                arbitrations=[item.model_dump(mode="json") for item in arbitrations],
                data_as_of=data_as_of,
            )

        business = self._business_condition(card, observations, price)
        if forecast_note:
            business = f"{business}{forecast_note}".strip()
        changes = self._long_term_changes(card, observations, knowledge, web, data_as_of, arbitrations)
        prior_clause = self._prior_turn_clause(prior_turns)
        if prior_clause:
            changes = f"{prior_clause}{changes}"
        risks = self._possible_risks(card, observations, evidence_items, arbitrations)
        missing = self._missing_evidence(abstain_list, evidence_items, card, readings)
        sources_summary = self._sources_summary(sources, data_as_of)
        result_status = self._result_status(abstain_list, evidence_items, readings)

        answer = PlainAnswer(
            business_condition=business,
            long_term_changes=changes,
            possible_risks=risks,
            missing_evidence=missing,
            sources_summary=sources_summary,
            result_status=result_status,
            data_as_of=data_as_of,
            next_observation_conditions=self._next_conditions(card, readings, result_status),
            invalidation_conditions=self._invalidation_conditions(card, readings),
            long_term_observations=observations,
            fundamental_dimensions=fundamentals,
            evidence=evidence_items,
            sources=sources,
            portfolio_note=portfolio,
            tools_used=[str(item) for item in (tools_used or []) if item],
            compliance_allowed=True,
            generated_by=generated_by,
            arbitrations=[item.model_dump(mode="json") for item in arbitrations],
            causal_observations=[item.model_dump(mode="json") for item in causal],
        )
        answer = self._enforce_compliance(answer, symbol=symbol)
        return answer

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------
    def _prior_turn_clause(self, prior_turns: Iterable[Mapping[str, object]] | None) -> str:
        """Neutral clause referencing the previous round's conclusion.

        Deterministic fallback (no LLM) cannot re-derive a prior conclusion,
        so it surfaces the prior assistant turn's wording verbatim, capped,
        so the user sees the chain explicitly reference what was said before.
        Empty when there is no prior assistant turn (first round / single
        turn) — keeps the single-turn path byte-identical.
        """
        turns = list(prior_turns or [])
        last_assistant = None
        for turn in reversed(turns):
            if isinstance(turn, Mapping) and turn.get("role") == "assistant":
                content = turn.get("content")
                if isinstance(content, str) and content.strip():
                    last_assistant = content.strip()
                    break
        if not last_assistant:
            return ""
        snippet = last_assistant if len(last_assistant) <= 48 else f"{last_assistant[:48]}……"
        return f"已结合前一轮讨论（“{snippet}”），在此基础上继续观察。"

    def _business_condition(self, card: Mapping[str, object], observations: list[PlainReadingObservation], price: Mapping[str, object]) -> str:
        quality = self._score_label(card.get("long_term_quality"))
        growth = self._score_label(card.get("growth_stability"))
        parts: list[str] = []
        if quality and growth:
            parts.append(f"经营质量{quality}、成长稳定性{growth}。")
        elif quality or growth:
            present = quality or growth or ""
            parts.append(f"基本面部分维度可引用（{present}），但仍有维度暂无读数，先说明已知事实，不强行下结论。")
        else:
            parts.append("当前缺少可引用的基本面评分，先说明已知事实，不强行下结论。")
        excess = [item for item in observations if "表现观察" in item.label]
        if excess:
            compact = "；".join(f"{item.horizon}相对基准的长期表现观察{item.tendency}" for item in excess)
            parts.append(f"长期表现观察：{compact}。")
        close = price.get("latest_close")
        if close is not None:
            parts.append(f"最近收盘价约 {self._format_close(close)}。")
        return "".join(parts) if parts else "目前没有足够的经营数据形成判断，需要补充财报和最新披露。"

    def _long_term_changes(
        self,
        card: Mapping[str, object],
        observations: list[PlainReadingObservation],
        knowledge: list[Mapping[str, object]],
        web: list[Mapping[str, object]],
        data_as_of: str | None,
        arbitrations: list[object] | None = None,
    ) -> str:
        parts: list[str] = []
        known_events = self._event_sentences(knowledge, web)
        if known_events:
            parts.append("近期可引用的主要变化：" + "；".join(known_events[:3]) + "。")
        drawdown = [item for item in observations if "下跌幅度" in item.label]
        if drawdown:
            compact = "；".join(f"{item.horizon}{item.tendency}" for item in drawdown)
            parts.append(f"潜在下跌幅度观察：{compact}。")
        for arb in arbitrations or []:
            stance = arb.resolved_stance if hasattr(arb, "resolved_stance") else arb.get("resolved_stance")
            reasoning = arb.reasoning if hasattr(arb, "reasoning") else arb.get("reasoning")
            label = {"knowledge": "参考官方披露方向", "web": "参考最新公开信息", "unresolved": "分歧未消除"}
            tag = label.get(stance, "分歧未消除")
            parts.append(f"来源分歧：{tag}。{reasoning}")
        if not parts:
            parts.append("尚未收集到可引用的近期变化或长期读数，请等待下一次财报与披露更新。")
        if data_as_of:
            parts.append(f"资料日期 {data_as_of}。")
        return "".join(parts)

    def _possible_risks(
        self,
        card: Mapping[str, object],
        observations: list[PlainReadingObservation],
        evidence: list[EvidenceItem],
        arbitrations: list[object] | None = None,
    ) -> str:
        risks: list[str] = []
        risk_score = self._score_label(card.get("long_term_risk"))
        if risk_score:
            risks.append(f"长期风险读数{risk_score}")
        valuation = self._score_label(card.get("valuation_position"))
        if valuation:
            risks.append(f"估值位置{valuation}")
        for item in observations:
            if "下跌幅度" in item.label and "偏大" in item.tendency:
                risks.append(f"{item.horizon}潜在下跌幅度偏大")
        conflict_in_evidence = any(item.classification == "conflict" for item in evidence)
        has_arbitration = bool(arbitrations)
        if conflict_in_evidence or has_arbitration:
            if has_arbitration:
                risks.append("不同来源存在分歧并已按权威与时效标注参考方向")
            else:
                risks.append("不同来源信息存在冲突")
        if not risks:
            risks.append("当前可引用的风险证据有限，主要需关注行业景气度、盈利变化和融资情况")
        return "；".join(risks) + "。这些是观察线索，不构成交易结论。"

    def _missing_evidence(self, abstain: list[str], evidence: list[EvidenceItem], card: Mapping[str, object], readings: Mapping[str, Mapping[str, object]]) -> str:
        missing_items: list[str] = []
        if not card:
            missing_items.append("基本面五维评分尚未生成或未通过核验")
        required = set(_EXCESS_RETURN_TASKS) | set(_DRAWDOWN_TASKS)
        absent = sorted(required - set(readings.keys()))
        if absent:
            missing_items.append("部分长期模型读数尚未生成：" + "、".join(self._horizon_label(item) for item in absent))
        conflicts = [item for item in evidence if item.classification == "conflict"]
        if conflicts:
            missing_items.append("来源之间存在冲突，需要交叉核对后再下判断")
        if abstain:
            missing_items.append("研究门禁暂未通过：" + "；".join(self._human_reason(item) for item in abstain[:3]))
        if not missing_items:
            missing_items.append("目前证据相对完整；仍建议持续关注下一次定期报告和重大披露")
        return "；".join(missing_items) + "。"

    def _sources_summary(self, sources: list[PlainSource], data_as_of: str | None) -> str:
        if not sources:
            base = "本次回答暂无可引用的外部资料。"
        else:
            compact = "；".join(f"{item.source}《{item.title}》" for item in sources[:6])
            base = f"主要资料：{compact}。"
        if data_as_of:
            base += f"数据截至 {data_as_of}。"
        base += "所有结果仅作研究观察，不构成投资建议或交易指令。"
        return base

    # ------------------------------------------------------------------
    # Model reading translation
    # ------------------------------------------------------------------
    def _build_observations(self, readings: Mapping[str, Mapping[str, object]]) -> list[PlainReadingObservation]:
        out: list[PlainReadingObservation] = []
        for task in (*_EXCESS_RETURN_TASKS, *_DRAWDOWN_TASKS):
            reading = readings.get(task)
            if not isinstance(reading, Mapping):
                out.append(PlainReadingObservation(
                    label=self._observation_label(task),
                    horizon=_HORIZON_LABEL[task],
                    tendency="尚未生成",
                    interpretation="该观察周期的模型读数尚未生成，等待补齐后再解释，不在此处臆测。",
                    available=False,
                ))
                continue
            out.append(self._translate_reading(task, reading))
        return out

    def observations_from_readings(
        self, readings: Mapping[str, Mapping[str, object]]
    ) -> list[PlainReadingObservation]:
        """Public entry over ``_build_observations`` for the AssetSnapshot
        service (Phase 2): the snapshot needs the same neutral-language
        reading translation the answer uses, so the dashboard tile and the AI
        answer never drift on how a reading is worded."""
        return self._build_observations(readings)

    def _translate_reading(self, task: str, reading: Mapping[str, object]) -> PlainReadingObservation:
        horizon = _HORIZON_LABEL[task]
        data_as_of = self._reading_date(reading)
        if task in _EXCESS_RETURN_TASKS:
            label = "相对基准的长期表现观察"
            tendency, interpretation = self._excess_tendency(reading)
        else:
            label = "潜在下跌幅度观察"
            tendency, interpretation = self._drawdown_tendency(reading)
        return PlainReadingObservation(
            label=label,
            horizon=horizon,
            tendency=tendency,
            interpretation=interpretation,
            available=True,
            data_as_of=data_as_of,
        )

    def _excess_tendency(self, reading: Mapping[str, object]) -> tuple[str, str]:
        centre = self._finite(reading.get("q50"))
        if centre is None:
            return "读数不完整", "模型未给出可用中位读数，暂不形成相对表现倾向。"
        if centre >= 0.04:
            return "相对基准偏强", "该周期读数相对基准偏强，说明长期表现观察暂时不弱；仍需结合行业景气度与盈利变化持续观察。"
        if centre <= -0.04:
            return "相对基准偏弱", "该周期读数相对基准偏弱，说明长期表现观察偏弱；主要需关注行业景气度和盈利变化是否存在分歧。"
        return "相对基准中性", "读数接近基准，长期表现倾向不明显，需要更多周期证据。"

    def _drawdown_tendency(self, reading: Mapping[str, object]) -> tuple[str, str]:
        centre = self._finite(reading.get("q50"))
        if centre is None:
            return "读数不完整", "模型未给出可用中位读数，暂不形成潜在下跌幅度倾向。"
        if centre <= -0.12:
            return "潜在下跌幅度偏大", "该周期潜在下跌幅度偏大，提醒关注波动与负面信息；这是幅度观察，仅供参考，不构成任何操作建议。"
        if centre <= -0.05:
            return "潜在下跌幅度中等", "该周期潜在下跌幅度中等，仍需结合波动率与最新披露理解。"
        return "潜在下跌幅度偏小", "读数显示潜在下跌幅度偏小，但这不是无风险保证，仍需关注新出现的负面信息。"

    # ------------------------------------------------------------------
    # Compliance enforcement
    # ------------------------------------------------------------------
    def _enforce_compliance(self, answer: PlainAnswer, *, symbol: str) -> PlainAnswer:
        text = self._answer_text(answer)
        result = self.compliance.check(text, subject_symbol=symbol or None)
        if result.allowed:
            answer.compliance_allowed = True
            return answer
        # If a section somehow introduced a blocked instruction, replace the
        # offending section with a neutral statement and re-check.  We never
        # silently drop content; we downgrade to a research-only note.
        answer.business_condition = "经营情况：当前仅说明已核验的研究事实，不输出交易指令。"
        answer.possible_risks = "可能的风险：以下为观察线索，不构成买卖或仓位建议。"
        recheck = self.compliance.check(self._answer_text(answer), subject_symbol=symbol or None)
        answer.compliance_allowed = recheck.allowed
        return answer

    @staticmethod
    def _answer_text(answer: PlainAnswer) -> str:
        return " ".join([
            answer.business_condition,
            answer.long_term_changes,
            answer.possible_risks,
            answer.missing_evidence,
            answer.sources_summary,
        ])

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def _fundamental_dimensions(self, card: Mapping[str, object]) -> dict[str, str]:
        mapping = (
            ("long_term_quality", "经营质量"),
            ("growth_stability", "成长稳定性"),
            ("valuation_position", "估值位置"),
            ("shareholder_return", "股东回报"),
            ("long_term_risk", "长期风险"),
            ("evidence_completeness", "证据完整度"),
        )
        out: dict[str, str] = {}
        for field, label in mapping:
            out[label] = self._score_label(card.get(field)) or "暂无可引用读数"
        return out

    def _portfolio_note(self, note: Mapping[str, object] | None) -> PlainPortfolioNote | None:
        if not isinstance(note, Mapping):
            return None
        return PlainPortfolioNote(
            concentration=str(note.get("concentration") or "当前未配置组合或组合信息不足。"),
            possible_impact=str(note.get("possible_impact") or "暂无法评估组合受影响程度，需要补充持仓与行业归属。"),
            missing_info=str(note.get("missing_info") or "仍需补充持仓明细、行业敞口和历史相关性。"),
            is_example_scenario=bool(note.get("is_example_scenario", True)),
        )

    def _next_conditions(self, card: Mapping[str, object], readings: Mapping[str, Mapping[str, object]], status: str) -> list[str]:
        conditions = ["关注下一次定期报告与重大披露后的盈利质量变化"]
        if status == "conflict_present":
            conditions.append("交叉核对存在冲突的来源与发布日期后再下判断")
        if not card:
            conditions.append("等待基本面评分通过核验后刷新")
        if (set(_EXCESS_RETURN_TASKS) | set(_DRAWDOWN_TASKS)) - set(readings.keys()):
            conditions.append("等待缺失的长期模型读数补齐后再形成长期观察")
        return conditions

    def _invalidation_conditions(self, card: Mapping[str, object], readings: Mapping[str, Mapping[str, object]]) -> list[str]:
        conditions = ["出现新的重大披露、财报修订或行业归属变化时重新评估当前观察"]
        if card.get("long_term_risk") is not None:
            conditions.append("长期风险读数出现实质变化时撤回当前研究观察")
        if readings:
            conditions.append("长期模型读数更新后以最新资料日期为准")
        return conditions

    def _result_status(self, abstain: list[str], evidence: list[EvidenceItem], readings: Mapping[str, Mapping[str, object]]) -> Literal["research_observation", "insufficient_evidence", "conflict_present"]:
        if any(item.classification == "conflict" for item in evidence):
            return "conflict_present"
        if abstain or not readings or not all(task in readings for task in (*_EXCESS_RETURN_TASKS, *_DRAWDOWN_TASKS)):
            return "insufficient_evidence"
        return "research_observation"

    def _event_sentences(self, knowledge: list[Mapping[str, object]], web: list[Mapping[str, object]]) -> list[str]:
        sentences: list[str] = []
        for entry in (*knowledge, *web):
            text = self._snippet(entry)
            if text:
                sentences.append(text[:160])
        return sentences

    def _score_label(self, value: object) -> str | None:
        number = self._finite(value)
        if number is None:
            return None
        if number >= 70:
            return f"约 {round(number)} 分（偏稳）"
        if number < 45:
            return f"约 {round(number)} 分（偏弱）"
        return f"约 {round(number)} 分（中等）"

    @staticmethod
    def _finite(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None

    @staticmethod
    def _format_close(value: object) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "n/a"

    @staticmethod
    def _snippet(entry: Mapping[str, object]) -> str:
        for key in ("snippet", "content", "summary", "text"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:400]
        return ""

    @staticmethod
    def _horizon_label(task: str) -> str:
        return _HORIZON_LABEL.get(task, task)

    @staticmethod
    def _observation_label(task: str) -> str:
        if task in _EXCESS_RETURN_TASKS:
            return "相对基准的长期表现观察"
        return "潜在下跌幅度观察"

    @staticmethod
    def _reading_date(reading: Mapping[str, object]) -> str | None:
        for key in ("data_as_of", "as_of_date"):
            value = reading.get(key)
            if isinstance(value, str) and value:
                return value[:10]
        return None

    @staticmethod
    def _human_reason(reason: str) -> str:
        table = {
            "long_term_scorecard_unavailable": "长期评分卡尚未生成",
            "long_term_model_readings_unavailable": "长期模型读数尚未生成",
            "long_term_data_trust_unavailable": "长期数据可信度未通过核验",
            "long_term_evidence_balance_unavailable": "长期证据平衡结果不可用",
            "symbol_scorecard_unavailable": "该标的的评分卡尚未生成",
        }
        return table.get(reason, reason.replace("_", " "))
