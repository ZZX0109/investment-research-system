"""Plain-language portfolio risk explainer for the long-term investment AI assistant.

When a user asks about their portfolio, the assistant must answer three
questions in plain language:

* 组合目前集中在哪里 (where is the portfolio concentrated)
* 可能受到什么影响 (what could affect it)
* 还需要补充哪些信息 (what information is still missing)

It must NOT produce rebalancing, position-sizing or trading instructions.
Stress scenarios are presented only as examples, never as predictions.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from pydantic import BaseModel, Field

from investment_research.service.compliance import ResearchTextComplianceChecker


class PortfolioHolding(BaseModel):
    ticker: str
    name: str
    value: float = 0.0
    quantity: float = 0.0
    industry: str | None = None
    weight: float | None = None  # pre-computed weight; recomputed if absent


class PortfolioScenario(BaseModel):
    name: str
    description: str
    is_example: bool = True


class PortfolioRiskExplanation(BaseModel):
    schema_version: str = "portfolio-risk-explanation-v1"
    concentration: str
    possible_impact: str
    missing_info: str
    scenarios: list[PortfolioScenario] = Field(default_factory=list)
    top_holdings: list[PortfolioHolding] = Field(default_factory=list)
    industry_concentration: dict[str, float] = Field(default_factory=dict)
    single_asset_hhi: float = 0.0
    has_rebalancing_instruction: bool = False
    compliance_allowed: bool = True
    result_status: str = "research_observation"


class PortfolioRiskExplainer:
    """Explain portfolio concentration and risk without trading instructions."""

    def __init__(self, *, compliance: ResearchTextComplianceChecker | None = None) -> None:
        self.compliance = compliance or ResearchTextComplianceChecker()

    def explain(
        self,
        holdings: Iterable[Mapping[str, object]] | None,
        *,
        portfolio_name: str | None = None,
    ) -> PortfolioRiskExplanation:
        items = [self._holding(item) for item in (holdings or []) if isinstance(item, Mapping)]
        items = [item for item in items if item.value > 0 or item.quantity > 0]
        total_value = sum(item.value for item in items)
        if not items or total_value <= 0:
            return PortfolioRiskExplanation(
                concentration="当前未配置组合或组合持仓信息不足，无法判断集中度。",
                possible_impact="暂无法评估组合可能受到的影响，需要补充持仓明细与行业归属。",
                missing_info="仍需补充持仓明细、行业敞口和历史相关性，才能说明组合风险。",
                scenarios=self._example_scenarios(),
            )
        for item in items:
            if item.weight is None:
                item.weight = item.value / total_value if total_value else 0.0
        top = sorted(items, key=lambda h: h.weight or 0.0, reverse=True)[:5]
        industry_map = self._industry_concentration(items)
        hhi = self._hhi(items)
        concentration = self._concentration_text(top, industry_map, hhi, portfolio_name)
        impact = self._impact_text(industry_map, top)
        missing = self._missing_text(items, industry_map)
        scenarios = self._example_scenarios()
        explanation = PortfolioRiskExplanation(
            concentration=concentration,
            possible_impact=impact,
            missing_info=missing,
            scenarios=scenarios,
            top_holdings=top,
            industry_concentration=industry_map,
            single_asset_hhi=hhi,
        )
        return self._enforce_compliance(explanation)

    # ------------------------------------------------------------------
    def _concentration_text(self, top: list[PortfolioHolding], industry: dict[str, float], hhi: float, name: str | None) -> str:
        prefix = f"{name}：" if name else "组合："
        if not top:
            return prefix + "没有可计算的持仓。"
        lead = top[0]
        parts = [f"{prefix}目前集中度最高的标的是{lead.name}（{lead.ticker}），权重约 {self._pct(lead.weight)}。"]
        if industry:
            top_industry, share = max(industry.items(), key=lambda kv: kv[1])
            parts.append(f"行业上相对集中在{top_industry}，约占 {self._pct(share)}。")
        if hhi >= 0.25:
            parts.append("单一标的集中度偏高，整体分散度有限。")
        elif hhi >= 0.15:
            parts.append("单一标的集中度中等，仍可观察分散程度。")
        else:
            parts.append("单一标的集中度相对分散。")
        return "".join(parts)

    def _impact_text(self, industry: dict[str, float], top: list[PortfolioHolding]) -> str:
        if not industry and not top:
            return "暂无法评估组合可能受到的影响，需要补充持仓与行业信息。"
        parts: list[str] = []
        if industry:
            top_industry = max(industry, key=industry.get)
            parts.append(f"如果{top_industry}景气度走弱或出现行业监管变化，组合可能受到较大影响。")
        if top:
            parts.append(f"权重最高的{top[0].name}若出现经营或估值变化，也会放大组合波动。")
        parts.append("以上为观察线索，不构成调仓或仓位建议。")
        return "".join(parts)

    def _missing_text(self, items: list[PortfolioHolding], industry: dict[str, float]) -> str:
        missing: list[str] = []
        if any(item.industry is None for item in items):
            missing.append("部分持仓缺少行业归属，集中度判断可能不完整")
        if len(items) < 3:
            missing.append("持仓数量较少，分散度参考意义有限")
        missing.append("仍需补充持仓成本、历史相关性和压力测试数据")
        return "；".join(missing) + "。"

    def _example_scenarios(self) -> list[PortfolioScenario]:
        return [
            PortfolioScenario(
                name="行业景气度走弱（示例）",
                description="若主要行业景气度下行，组合中相关持仓可能承压。这只是说明性示例，不是预测结果。",
            ),
            PortfolioScenario(
                name="单一标的经营变化（示例）",
                description="若权重最高的标的经营恶化，组合波动可能放大。这只是说明性示例，不是预测结果。",
            ),
        ]

    # ------------------------------------------------------------------
    def _industry_concentration(self, items: list[PortfolioHolding]) -> dict[str, float]:
        totals: dict[str, float] = {}
        unmapped = 0.0
        for item in items:
            industry = (item.industry or "").strip() or None
            if not industry:
                unmapped += item.weight or 0.0
                continue
            totals[industry] = totals.get(industry, 0.0) + (item.weight or 0.0)
        if unmapped > 0:
            totals["未分类"] = totals.get("未分类", 0.0) + unmapped
        return totals

    @staticmethod
    def _hhi(items: list[PortfolioHolding]) -> float:
        return sum((item.weight or 0.0) ** 2 for item in items)

    @staticmethod
    def _holding(item: Mapping[str, object]) -> PortfolioHolding:
        return PortfolioHolding(
            ticker=str(item.get("ticker", "")),
            name=str(item.get("name", item.get("ticker", ""))),
            value=float(item.get("value", item.get("market_value", 0.0)) or 0.0),
            quantity=float(item.get("quantity", 0.0) or 0.0),
            industry=str(item.get("industry") or item.get("sector") or "") or None,
            weight=float(item["weight"]) if isinstance(item.get("weight"), (int, float)) else None,
        )

    @staticmethod
    def _pct(value: float | None) -> str:
        if value is None:
            return "n/a"
        return f"{round(value * 100)}%"

    # ------------------------------------------------------------------
    def _enforce_compliance(self, explanation: PortfolioRiskExplanation) -> PortfolioRiskExplanation:
        text = f"{explanation.concentration} {explanation.possible_impact} {explanation.missing_info}"
        result = self.compliance.check(text)
        explanation.compliance_allowed = result.allowed
        explanation.has_rebalancing_instruction = not result.allowed
        return explanation
