"""Asset snapshot — the single source of truth shared by the dashboard tiles
and the AI answer (Phase 2, the load-bearing piece of the
选股 → 仪表盘 → AI chain).

The snapshot is **asset-scoped and as_of-pinned**: it composes the same
read-only, frozen-as-of services the Agent's tools use (frozen price series,
immutable long-term scorecard + model readings, PIT-visible fact cards and
line items, the latest research forecast) plus a BASELINE evidence merge and
causal-observation pass built from the asset's own knowledge (no
question-specific web search).  The dashboard renders this snapshot; the AI
``_build_plain_answer`` consumes it as budget context so it does NOT re-run the
price / forecast / line-item / fact-card tools — eliminating the
dashboard-sees-one-number / AI-answers-another drift.

Question-specific knowledge / web retrieval still runs per AI turn on top of
this baseline (that is legitimately question-scoped, not drift).

Constraints (unchanged from the rest of the platform):
* research_pit / research_demonstration_not_validated only — never touches the
  active ``long_term_training/latest.json`` except through the read-only
  ``load_long_term_scorecard`` loader.
* no AgentRun, no abstain gate, no writes — purely read-only aggregation.
* missing data degrades to ``coverage_status="unknown"`` / ``available=False``
  / empty lists; it never synthesizes a number.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Mapping
from uuid import UUID

from pydantic import BaseModel, Field

from investment_research.agent.answer_models import (
    CausalObservation,
    EvidenceMergeResult,
    PlainReadingObservation,
)
from investment_research.agent.evidence_merge import EvidenceMerger
from investment_research.agent.plain_answer import PlainAnswerBuilder
from investment_research.agent.prediction_framing import frame_prediction_as_observation
from investment_research.agent.reasoning_chain import ReasoningChainBuilder
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService
from investment_research.service.long_term_research import (
    load_long_term_scorecard,
    load_long_term_scorecard_demo,
)


class AssetRef(BaseModel):
    asset_id: str
    symbol: str
    name: str | None = None


class MarketObservationFacts(BaseModel):
    """as_of-pinned price facts computed from the frozen daily series.

    Deliberately NOT the live quote: the snapshot must reproduce the same
    number the AI sees, so it uses the same ``point.timestamp <= as_of`` slice
    the Agent's ``get_price_trend`` tool uses.
    """

    latest_close: float | None = None
    trade_date: str | None = None
    return_20d: float | None = None
    volatility_20d: float | None = None
    sessions: int = 0
    source: str = "frozen_price_series"


class DirectionalForecastObservation(BaseModel):
    """Research-framed directional forecast for the asset's latest run.

    ``tile_text`` is the shared, compliance-safe wording produced by
    ``frame_prediction_as_observation`` (Phase 5): direction probabilities and
    relative-benchmark return quantiles with a ``research_demonstration_not_validated``
    disclaimer, never a buy/sell/target-price/guaranteed-return instruction.  The
    dashboard tile and the AI answer surface the same ``tile_text`` so they
    cannot drift on forecast wording, and the wording passes
    ``ResearchTextComplianceChecker``.
    """

    available: bool = False
    research_run_id: str | None = None
    tile_text: str = ""
    framing_status: str = "research_demonstration_not_validated"
    direction_1d: dict | None = None
    direction_5d: dict | None = None
    return_20d: dict | None = None
    drawdown_20d: dict | None = None
    gating_reasons: list[str] = Field(default_factory=list)


class AssetSnapshot(BaseModel):
    """Single source of truth for one asset at one as_of."""

    schema_version: str = "asset-snapshot-v1"
    asset: AssetRef
    as_of: datetime
    data_as_of: str | None = None
    market_observation: MarketObservationFacts
    long_term_status: str = "unavailable"
    long_term_blocking_reasons: list[str] = Field(default_factory=list)
    scorecard: dict | None = None
    model_readings: dict | None = None
    directional_forecast: DirectionalForecastObservation | None = None
    fact_cards: list[dict] = Field(default_factory=list)
    fact_card_coverage_status: str = "unknown"
    fact_card_absence_is_evidence: bool = False
    fact_card_coverage_reasons: list[str] = Field(default_factory=list)
    line_items: list[dict] = Field(default_factory=list)
    line_item_coverage_status: str = "unknown"
    line_item_coverage_reasons: list[str] = Field(default_factory=list)
    evidence_merge_result: EvidenceMergeResult | None = None
    causal_observations: list[CausalObservation] = Field(default_factory=list)


class AssetSnapshotService:
    """Read-only as_of-pinned asset snapshot composer."""

    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        project_root: Path | None = None,
        knowledge: FinancialKnowledgeService | None = None,
    ) -> None:
        self.uow = uow
        self.project_root = (project_root or Path.cwd()).resolve()
        self._knowledge = knowledge

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def snapshot(
        self,
        asset_id: str,
        *,
        as_of: datetime,
        user: User,
    ) -> AssetSnapshot:
        asset = self.uow.assets.get(asset_id)
        if asset is None:
            raise ValueError("Asset not found")
        symbol = (asset.ticker or "").upper()

        market = self._market_observation_facts(asset_id, as_of)
        long_term = self._long_term_scorecard(symbol)
        card = long_term.get("scorecard")
        readings = long_term.get("long_term_model_readings")
        readings_map = readings if isinstance(readings, Mapping) else None

        line_items_result = self._knowledge_service().retrieve_line_items(
            symbol=symbol, as_of=as_of, market="CN",
        )
        line_items = [self._line_item_figure(item) for item in line_items_result.line_items]

        fact_cards_result = self._knowledge_service().retrieve_fact_cards(
            symbol=symbol, as_of=as_of, owner_user_id=user.id,
        )
        fact_cards = [self._fact_card_figure(c) for c in fact_cards_result.cards[:12]]

        forecast = self._directional_forecast(asset_id, user=user, symbol=symbol)

        data_as_of = self._data_as_of(card, market, long_term)

        # Baseline evidence merge: the asset's own fact cards as confirmed
        # knowledge (no question-specific web).  This is what the dashboard
        # evidence tile shows; the AI re-runs EvidenceMerger per question with
        # question-specific knowledge+web on top of these same asset-scoped
        # readings/price/scorecard.
        evidence_merge = EvidenceMerger().merge(
            knowledge=[self._fact_card_as_knowledge(c) for c in fact_cards],
            web=None,
            readings=readings_map,
            price_facts={
                "latest_close": market.latest_close,
                "trade_date": market.trade_date,
            },
            scorecard=card if isinstance(card, Mapping) else None,
            abstain_reasons=None,
        )

        # Causal observations from the SAME translation the answer uses, so the
        # dashboard and the AI never drift on how a reading is reasoned about.
        observations = PlainAnswerBuilder().observations_from_readings(
            readings_map if isinstance(readings_map, Mapping) else {}
        )
        causal = ReasoningChainBuilder().build(
            scorecard=card if isinstance(card, Mapping) else None,
            observations=observations,
            fact_cards=fact_cards,
            line_items=line_items,
            arbitrations=[a.model_dump(mode="json") for a in evidence_merge.arbitrations],
            data_as_of=data_as_of,
        )

        return AssetSnapshot(
            asset=AssetRef(asset_id=str(asset.id), symbol=symbol, name=asset.name),
            as_of=as_of,
            data_as_of=data_as_of,
            market_observation=market,
            long_term_status=str(long_term.get("status") or "unavailable"),
            long_term_blocking_reasons=[
                str(r) for r in (long_term.get("blocking_reasons") or []) if r
            ],
            scorecard=card if isinstance(card, Mapping) else None,
            model_readings=readings if isinstance(readings, Mapping) else None,
            directional_forecast=forecast,
            fact_cards=fact_cards,
            fact_card_coverage_status=str(fact_cards_result.coverage_status),
            fact_card_absence_is_evidence=bool(fact_cards_result.absence_is_evidence),
            fact_card_coverage_reasons=[
                str(r) for r in (fact_cards_result.coverage_reasons or []) if r
            ],
            line_items=line_items,
            line_item_coverage_status=str(line_items_result.coverage_status),
            line_item_coverage_reasons=[
                str(r) for r in (line_items_result.coverage_reasons or []) if r
            ],
            evidence_merge_result=evidence_merge,
            causal_observations=causal,
        )

    # ------------------------------------------------------------------
    # as_of-pinned price facts (frozen series slice, NOT live quote)
    # ------------------------------------------------------------------
    def _market_observation_facts(
        self, asset_id: str, as_of: datetime
    ) -> MarketObservationFacts:
        points = sorted(
            [
                point
                for series in self.uow.price_series.list_for_asset(asset_id)
                if series.interval == "1d" and series.series_role in {None, "asset"}
                for point in series.points
                if point.timestamp <= as_of
            ],
            key=lambda item: item.timestamp,
        )[-90:]
        closes = [float(p.close) for p in points if p.close > 0]
        returns = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        latest_close = closes[-1] if closes else None
        trade_date = (
            points[-1].timestamp.date().isoformat() if points else None
        )
        return MarketObservationFacts(
            latest_close=latest_close,
            trade_date=trade_date,
            return_20d=None if len(closes) < 21 else closes[-1] / closes[-21] - 1,
            volatility_20d=(
                None if len(returns) < 20 else statistics.pstdev(returns[-20:]) * math.sqrt(252)
            ),
            sessions=len(closes),
        )

    # ------------------------------------------------------------------
    # Long-term scorecard + model readings (read-only loader, demo fallback)
    # ------------------------------------------------------------------
    def _long_term_scorecard(self, symbol: str) -> dict[str, object]:
        response = load_long_term_scorecard(project_root=self.project_root, symbol=symbol)
        if response.get("status") != "available":
            demo = load_long_term_scorecard_demo(project_root=self.project_root, symbol=symbol)
            if demo.get("status") == "available":
                return demo
        return response

    # ------------------------------------------------------------------
    # Directional forecast from the asset's latest run (read-only)
    # ------------------------------------------------------------------
    def _directional_forecast(
        self, asset_id: str, *, user: User, symbol: str
    ) -> DirectionalForecastObservation | None:
        runs = [
            run
            for run in self.uow.analysis_runs.list_for_asset(asset_id)
            if run.triggered_by == user.auth_subject
        ]
        if not runs:
            return None
        run = runs[0]
        forecast = self.uow.research_forecasts.for_run(str(run.id))
        # Phase 5: route the raw forecast through the shared, compliance-safe
        # framing so the dashboard tile and the AI answer surface the same
        # wording (direction probabilities / relative-benchmark return
        # quantiles + research_demonstration_not_validated disclaimer), and so
        # the wording passes ResearchTextComplianceChecker.
        framed = frame_prediction_as_observation(
            forecast, research_run_id=str(run.id), symbol=symbol,
        )
        return DirectionalForecastObservation(**framed)

    # ------------------------------------------------------------------
    # Field shapers (mirror the Agent tool result shapes exactly so the AI can
    # consume the snapshot fields in place of the tool outputs)
    # ------------------------------------------------------------------
    @staticmethod
    def _line_item_figure(item) -> dict:
        return {
            "period": item.period,
            "metric": item.metric,
            "metric_label": item.metric_label,
            "value": item.value,
            "unit": item.unit,
            "scale": item.scale,
            "yoy_pct": item.yoy_pct,
            "qoq_pct": item.qoq_pct,
            "source_name": item.source_name,
            "source_url": item.source_url,
            "source_doc_id": None if item.source_doc_id is None else str(item.source_doc_id),
            "published_at": item.published_at.isoformat(),
            "available_at": item.available_at.isoformat(),
            "authority_level": item.authority_level,
            "citation_id": f"fin:{item.symbol}:{item.period}:{item.metric}:{item.content_hash[:12]}",
            "content_hash": item.content_hash,
        }

    @staticmethod
    def _fact_card_figure(card) -> dict:
        return {
            "revision_id": str(card.revision_id),
            "stance": card.stance,
            "topic": card.topic,
            "claim": card.claim[:800],
            "source_name": card.source_name,
            "source_url": card.source_url,
            "published_at": card.published_at.isoformat(),
            "available_at": card.available_at.isoformat(),
            "confidence": card.confidence,
            "authority_level": card.authority_level,
            "citation_id": f"fact:{card.revision_id}",
        }

    @staticmethod
    def _fact_card_as_knowledge(figure: Mapping[str, object]) -> dict[str, object]:
        """Adapt a fact-card figure to the knowledge-entry shape EvidenceMerger
        expects (``snippet`` / ``document`` / ``citation_id``) so the asset's
        own facts become the baseline confirmed evidence."""
        return {
            "snippet": str(figure.get("claim") or ""),
            "document": {
                "title": str(figure.get("topic") or "长期事实卡"),
                "source_name": str(figure.get("source_name") or "知识库"),
                "source_url": str(figure.get("source_url") or "internal://knowledge"),
                "published_at": str(figure.get("published_at") or "")[:10] or None,
            },
            "citation_id": str(figure.get("citation_id") or ""),
            "verified": True,
        }

    @staticmethod
    def _data_as_of(
        card: object,
        market: MarketObservationFacts,
        long_term: Mapping[str, object],
    ) -> str | None:
        if isinstance(card, Mapping):
            as_of_date = card.get("as_of_date")
            if isinstance(as_of_date, str) and as_of_date:
                return as_of_date
        if market.trade_date:
            return market.trade_date
        return None

    def _knowledge_service(self) -> FinancialKnowledgeService:
        if self._knowledge is None:
            self._knowledge = FinancialKnowledgeService(self.uow)
        return self._knowledge


__all__ = [
    "AssetRef",
    "MarketObservationFacts",
    "DirectionalForecastObservation",
    "AssetSnapshot",
    "AssetSnapshotService",
]
