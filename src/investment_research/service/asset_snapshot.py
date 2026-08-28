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
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from datetime import date, datetime
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
from investment_research.service.portfolio_research import PortfolioResearchService


_MARKET_NEWS_CACHE_TTL_SECONDS = 300
_MARKET_NEWS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_MARKET_NEWS_CACHE_LOCK = RLock()
_SNAPSHOT_CACHE_TTL_SECONDS = 60
_SNAPSHOT_CACHE_MAX_ENTRIES = 256
_SNAPSHOT_CACHE: dict[tuple[str, str, str], tuple[float, "AssetSnapshot"]] = {}
_SNAPSHOT_CACHE_LOCK = RLock()


def _xystock_kline_closes(symbol: str, as_of: datetime) -> list[tuple[str, float]]:
    """Live kline fallback for ``_market_observation_facts``.

    Returns ``(date, close)`` tuples for bars on or before ``as_of`` so the
    snapshot stays as_of-pinned even when sourced from a live fetch.  An empty
    list means akshare was gated or the symbol had no recent history; the
    caller leaves ``latest_close`` null rather than synthesizing a number.
    """
    from investment_research.integrations.xystock.quote_fetcher import fetch_kline

    result = fetch_kline(symbol, days=120)
    if not result.available:
        return []
    cutoff = as_of.date().isoformat()
    out: list[tuple[str, float]] = []
    for bar in result.data:
        date_str = str(bar.get("date") or "")[:10]
        close = bar.get("close")
        if date_str and date_str <= cutoff and close is not None and close > 0:
            out.append((date_str, float(close)))
    return out


class _FrozenPriceBarRepository:
    """Small adapter that lets temporal models use the same frozen price
    series rendered by the dashboard instead of a stale training catalog."""

    def __init__(self, points: list[object]) -> None:
        self._points = points

    def active_bars(self, _symbol: str, _interval: str, *, as_of: datetime | None = None) -> list[object]:
        points = self._points
        if as_of is not None:
            points = [point for point in points if point.timestamp <= as_of]
        return [
            type("FrozenBar", (), {
                "bar_start": point.timestamp,
                "trade_date": point.timestamp.date(),
                "close": float(point.close),
            })()
            for point in points
            if point.close > 0
        ]


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


class PricePathPoint(BaseModel):
    """One day of the predicted-vs-actual price path."""

    date: str
    actual: float | None = None
    predicted: float | None = None
    q10: float | None = None
    q90: float | None = None


class PricePathForecast(BaseModel):
    """Predicted price path (p50 + q10/q90 band) vs realized close.

    Populated by the kittenCN price-path runner once ported (§1 step 6).  Until
    then it degrades to ``status="unavailable"`` so the dashboard's
    predicted-vs-actual chart shows an honest empty state rather than a
    fabricated path — mirroring the accuracy-surface honesty for the path model.
    """

    status: str = "unavailable"
    model: str | None = None
    horizon_days: int | None = None
    mean_abs_error_pct: float | None = None
    generated_at: str | None = None
    path_mode: str | None = None
    metrics: dict[str, object] | None = None
    # §1 row-5 (训练说清楚): the kittenCN temporal prereq state when the path
    # degrades to the quantile projection — {vendored_source, torch,
    # trained_weights, ready, blocking}. None when the temporal model produced
    # the path (ready) or the runner didn't inject it.
    temporal_model_status: dict[str, object] | None = None
    points: list[PricePathPoint] = Field(default_factory=list)
    historical_points: list[PricePathPoint] = Field(default_factory=list)


class ModelHistoryPoint(BaseModel):
    """One archived out-of-sample model reading and its realized outcome."""

    decision_date: str
    predicted_return: float
    actual_return: float
    model_count: int = 1


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
    model_history: list[ModelHistoryPoint] = Field(default_factory=list)
    walk_forward_daily: dict | None = None
    directional_forecast: DirectionalForecastObservation | None = None
    price_path_forecast: PricePathForecast | None = None
    fact_cards: list[dict] = Field(default_factory=list)
    fact_card_coverage_status: str = "unknown"
    fact_card_absence_is_evidence: bool = False
    fact_card_coverage_reasons: list[str] = Field(default_factory=list)
    line_items: list[dict] = Field(default_factory=list)
    line_item_coverage_status: str = "unknown"
    fundamental_coverage: dict | None = None
    line_item_coverage_reasons: list[str] = Field(default_factory=list)
    # §1 row-2 / §2 three-piece (snapshot field): the CatBoost research-model
    # readout (direction + OOF accuracy + feature importance) so the dashboard
    # shows it alongside the LLM plain-answer (同源: dashboard + LLM sync).
    catboost_readout: dict | None = None
    # §1 row-2 (round 27): price-based 1/5/20d CatBoost horizon forecasts —
    # the fortune ml_trading_model short-term piece, trained on real daily
    # bars (versioned_market_bars, round 26). ADDITIVE to the 240d readout.
    catboost_short_term_horizons: dict | None = None
    # §1 row-3 (round 28): per-asset walk-forward daily for the 1/5/20d CatBoost
    # horizons — realized directional accuracy replayed over THIS symbol's
    # history (训练说清楚 WHERE per-asset for the short-term model).
    catboost_horizon_walk_forward_daily: dict | None = None
    evidence_merge_result: EvidenceMergeResult | None = None
    causal_observations: list[CausalObservation] = Field(default_factory=list)
    # Round 34 — intraday spot (盘中行情) so the dashboard + LLM both sense
    # the same-day price/change (同源: polled hourly by the async worker into
    # intraday_quote_spot).  Lets the user see today's move when picking a
    # stock, and lets the LLM answer with the live same-day quote.
    intraday_quote: dict | None = None
    # Round 34 — per-asset news + notices (个股新闻 + 公告) fetched from
    # akshare (stock_news_em + stock_individual_notice_report) so the LLM
    # plain-answer can cite same-day news/announcements alongside the quote.
    market_news: list[dict] = Field(default_factory=list)


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

    def _forecast_market_repository(self, asset_id: str, as_of: datetime) -> object:
        series = [
            series
            for series in self.uow.price_series.list_for_asset(asset_id)
            if series.interval == "1d" and series.series_role in {None, "asset"}
        ]
        if not series:
            asset = self.uow.assets.get(asset_id)
            if asset is not None:
                fallback = PortfolioResearchService(self.uow)._load_cn_research_price_series(asset)
                if fallback is not None:
                    series = [fallback]
        points = sorted(
            [point for item in series for point in item.points if point.timestamp <= as_of],
            key=lambda point: point.timestamp,
        )
        if len(points) >= 22:
            return _FrozenPriceBarRepository(points)
        return self.uow.trusted_market

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
        import time

        # The snapshot contains one user's research-run context, so the cache
        # is explicitly user-scoped. Bucketing as_of to a minute lets a new
        # page reuse the same short-lived result without exposing a stale
        # timestamp to the caller.
        cache_key = (
            str(user.id),
            str(asset_id),
            as_of.replace(second=0, microsecond=0).isoformat(),
        )
        now = time.monotonic()
        with _SNAPSHOT_CACHE_LOCK:
            cached = _SNAPSHOT_CACHE.get(cache_key)
            if cached and now - cached[0] < _SNAPSHOT_CACHE_TTL_SECONDS:
                return cached[1].model_copy(update={"as_of": as_of})
        symbol = (asset.ticker or "").upper()

        market = self._market_observation_facts(asset_id, as_of)
        long_term = self._long_term_scorecard(symbol)
        card = long_term.get("scorecard")
        readings = long_term.get("long_term_model_readings")
        readings_map = readings if isinstance(readings, Mapping) else None
        model_history = self._model_prediction_history(symbol)
        # §1 step 7 / §3 get_model_walkforward_daily: per-asset daily accuracy +
        # error from the archived predicted-vs-actual readings (mirrors fortune's
        # walk_forward, adapted to this repo's ModelHistoryPoint). Surfaces "for
        # this stock the model's directional calls were right X of N times" to
        # the dashboard + the LLM budget context (训练说清楚, per-asset).
        from investment_research.agent.evaluation import summarize_walk_forward

        walk_forward_daily = summarize_walk_forward(model_history)

        # §1 row-2 / §2 three-piece (snapshot field): compute the CatBoost
        # research-model readout (direction + OOF accuracy + feature
        # importance) for THIS symbol so the dashboard shows it alongside the
        # LLM plain-answer (同源: dashboard + LLM sync). Degrades to None when
        # no model / no OOF row (训练说清楚, never fabricated).
        catboost_readout: dict | None = None
        try:
            from investment_research.training.short_term import CatBoostShortTermRunner

            cb_runner = CatBoostShortTermRunner(self.project_root)
            if cb_runner.is_available():
                direction = cb_runner.calibrated_direction_for_symbol(symbol)
                catboost_readout = {
                    "direction": direction,
                    "accuracy": cb_runner.accuracy_summary(),
                    "feature_importance": cb_runner.feature_importance(),
                }
        except Exception:
            catboost_readout = None

        # §1 row-2 (round 27) / §2 three-piece (snapshot field): the price-based
        # 1/5/20d CatBoost horizon forecasts for THIS symbol — trained on real
        # daily bars. ADDITIVE to the 240d readout above; degrades to None when
        # no model / no bars (训练说清楚, never fabricated).
        catboost_short_term_horizons: dict | None = None
        catboost_horizon_walk_forward_daily: dict | None = None
        try:
            from investment_research.training.short_term.catboost_horizon_runner import (
                CatBoostHorizonRunner,
            )

            hz_runner = CatBoostHorizonRunner(self.project_root)
            if hz_runner.is_available():
                catboost_short_term_horizons = hz_runner.horizon_forecast_for_symbol(self.uow.trusted_market, symbol)
                # §1 row-3 (round 28): per-asset walk-forward daily for the
                # 1/5/20d horizons — realized accuracy replayed over this
                # symbol's bars (训练说清楚 WHERE per-asset short-term).
                catboost_horizon_walk_forward_daily = hz_runner.walk_forward_daily_for_symbol(self.uow.trusted_market, symbol)
        except Exception:
            catboost_short_term_horizons = None

        # §1 step 6 price-path: route through the price-path adapter
        # (``training/price_path``), the §1 row-5 mandated location. Default =
        # the EXISTING trained long-term model's q10/q50/q90 fan (real data,
        # no synthesis); the kittenCN temporal hook upgrades it to a daily
        # temporal path once vendored + trained. Anchored at latest_close; the
        # realized MAE comes from this asset's walk-forward record so the
        # chart's error readout is grounded, not guessed.
        from investment_research.training.price_path import forecast as forecast_price_path

        price_path_proj = forecast_price_path(
            symbol,
            readings if isinstance(readings, Mapping) else {},
            market.latest_close,
            as_of,
            realized_mae=walk_forward_daily.get("mean_abs_error"),
            task="excess_return_240d",
            repo=self._forecast_market_repository(asset_id, as_of),
            project_root=self.project_root,
            anchor_date=market.trade_date,
        )
        price_path_forecast = PricePathForecast(
            status=price_path_proj.get("status", "unavailable"),
            model=price_path_proj.get("model"),
            horizon_days=price_path_proj.get("horizon_days"),
            mean_abs_error_pct=price_path_proj.get("mean_abs_error_pct"),
            generated_at=price_path_proj.get("generated_at"),
            path_mode=price_path_proj.get("path_mode"),
            metrics=price_path_proj.get("metrics"),
            temporal_model_status=price_path_proj.get("temporal_model_status"),
            points=[
                PricePathPoint(
                    date=p["date"],
                    actual=p.get("actual"),
                    predicted=p.get("predicted"),
                    q10=p.get("q10"),
                    q90=p.get("q90"),
                )
                for p in price_path_proj.get("points", [])
            ],
            historical_points=[
                PricePathPoint(
                    date=p["date"],
                    actual=p.get("actual"),
                    predicted=p.get("predicted"),
                    q10=p.get("q10"),
                    q90=p.get("q90"),
                )
                for p in price_path_proj.get("historical_points", [])
            ],
        )

        line_items_result = self._knowledge_service().retrieve_line_items(
            symbol=symbol, as_of=as_of, market="CN",
        )
        line_items = [self._line_item_figure(item) for item in line_items_result.line_items]
        # §3 数据可信度细化: per-asset fundamental coverage — which of the §6③
        # six core pillars (revenue/net_profit/gross_margin/operating_profit/
        # roe/roa) are present in this asset's line_items, so the LLM can cite
        # concrete per-asset data-trust gaps ("茅台 缺 ROE/ROA") instead of a
        # blank completeness=100.
        from investment_research.agent.evaluation import fundamental_coverage

        fund_coverage = fundamental_coverage(line_items)

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

        # Round 34 — intraday quote (盘中实时) + per-asset news/notices, so the
        # dashboard + LLM both sense same-day price move + news (同源).  Both
        # degrade to None/[] on a flaky akshare call (never block the snapshot).
        intraday_quote = self._intraday_quote_facts(symbol)
        market_news = self._market_news_facts(symbol)

        snapshot = AssetSnapshot(
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
            model_history=model_history,
            walk_forward_daily=walk_forward_daily,
            directional_forecast=forecast,
            price_path_forecast=price_path_forecast,
            fact_cards=fact_cards,
            fact_card_coverage_status=str(fact_cards_result.coverage_status),
            fact_card_absence_is_evidence=bool(fact_cards_result.absence_is_evidence),
            fact_card_coverage_reasons=[
                str(r) for r in (fact_cards_result.coverage_reasons or []) if r
            ],
            line_items=line_items,
            line_item_coverage_status=str(line_items_result.coverage_status),
            fundamental_coverage=fund_coverage,
            catboost_readout=catboost_readout,
            catboost_short_term_horizons=catboost_short_term_horizons,
            catboost_horizon_walk_forward_daily=catboost_horizon_walk_forward_daily,
            line_item_coverage_reasons=[
                str(r) for r in (line_items_result.coverage_reasons or []) if r
            ],
            evidence_merge_result=evidence_merge,
            causal_observations=causal,
            intraday_quote=intraday_quote,
            market_news=market_news,
        )
        with _SNAPSHOT_CACHE_LOCK:
            _SNAPSHOT_CACHE[cache_key] = (time.monotonic(), snapshot)
            if len(_SNAPSHOT_CACHE) > _SNAPSHOT_CACHE_MAX_ENTRIES:
                oldest_key = min(_SNAPSHOT_CACHE, key=lambda key: _SNAPSHOT_CACHE[key][0])
                _SNAPSHOT_CACHE.pop(oldest_key, None)
        return snapshot

    # ------------------------------------------------------------------
    # Round 34 — intraday quote (盘中实时) + per-asset news/notices
    # ------------------------------------------------------------------
    def _intraday_quote_facts(self, symbol: str) -> dict | None:
        """Read THIS symbol's latest spot row from ``intraday_quote_spot``
        (polled hourly by the async worker).  Returns None when no spot has
        been captured yet (e.g. before the worker's first tick) — never blocks
        the snapshot, never fabricates.  Gated on ``INVESTMENT_RESEARCH_
        INTRADAY_NEWS_ENABLED`` (or competition mode) so tests that build a
        snapshot never hit the network."""
        import os

        if not (
            os.environ.get("INVESTMENT_RESEARCH_INTRADAY_NEWS_ENABLED")
            or os.environ.get("INVESTMENT_RESEARCH_COMPETITION_MODE")
        ):
            return None
        try:
            from investment_research.service.intraday_spot import latest_market_snapshot

            rows = latest_market_snapshot(None, symbols=[symbol], limit=1)
            if not rows:
                return None
            r = rows[0]
            return {
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "latest_price": r.get("latest_price"),
                "change_pct": r.get("change_pct"),
                "volume": r.get("volume"),
                "amount": r.get("amount"),
                "captured_at": r.get("captured_at"),
            }
        except Exception:
            return None

    def _market_news_facts(self, symbol: str) -> list[dict]:
        """Fetch latest per-asset news (``stock_news_em``) + official notices
        (``stock_individual_notice_report``) for THIS symbol.  Each degrades
        to [] via ``safe_fetch`` on a flaky akshare call; the two are merged
        into one news list so the LLM plain-answer can cite same-day news +
        announcements alongside the intraday quote.  Gated on the same env
        flag as ``_intraday_quote_facts`` so tests never hit the network.
        Results are cached per-symbol for 5 minutes at process scope so a new
        snapshot request does not re-fetch network news immediately (news +
        notices take ~6s). A failed pair is not cached, allowing a later retry."""
        import os
        import time

        if not (
            os.environ.get("INVESTMENT_RESEARCH_INTRADAY_NEWS_ENABLED")
            or os.environ.get("INVESTMENT_RESEARCH_COMPETITION_MODE")
        ):
            return []
        now = time.time()
        with _MARKET_NEWS_CACHE_LOCK:
            hit = _MARKET_NEWS_CACHE.get(symbol)
            if hit and now - hit[0] < _MARKET_NEWS_CACHE_TTL_SECONDS:
                return hit[1]
        from investment_research.integrations.xystock.quote_fetcher import (
            fetch_stock_news,
            fetch_stock_notices,
        )

        news: list[dict] = []
        # These providers are independent network calls. Run them together so
        # the slower notice endpoint no longer waits for the news endpoint.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="asset-news") as pool:
            news_future = pool.submit(fetch_stock_news, symbol, limit=8)
            notice_future = pool.submit(fetch_stock_notices, symbol, limit=5, days=7)
            nr = news_future.result()
            tr = notice_future.result()
        if nr.available and nr.data:
            for n in nr.data:
                news.append({
                    "kind": "news",
                    "title": n.get("title"),
                    "published_at": n.get("published_at"),
                    "source": n.get("source"),
                    "url": n.get("url"),
                })
        if tr.available and tr.data:
            for n in tr.data:
                news.append({
                    "kind": "notice",
                    "title": n.get("title"),
                    "notice_type": n.get("notice_type"),
                    "date": n.get("date"),
                    "source": "cninfo",
                    "url": n.get("url"),
                })
        # Do not turn a temporary provider outage into a five-minute blank
        # result. Cache only when at least one provider returned usable data.
        if nr.available or tr.available:
            with _MARKET_NEWS_CACHE_LOCK:
                _MARKET_NEWS_CACHE[symbol] = (now, news)
        return news

    # ------------------------------------------------------------------
    # as_of-pinned price facts (frozen series slice, NOT live quote)
    # ------------------------------------------------------------------
    def _market_observation_facts(
        self, asset_id: str, as_of: datetime
    ) -> MarketObservationFacts:
        asset = self.uow.assets.get(asset_id)
        series = [
            series
            for series in self.uow.price_series.list_for_asset(asset_id)
            if series.interval == "1d" and series.series_role in {None, "asset"}
        ]
        if not series and asset is not None:
            # The downloaded PIT parquet is intentionally not copied into the
            # SQLite UI table. Reuse the read-only bridge used by the chart API
            # so the dashboard snapshot can still display local market data.
            fallback = PortfolioResearchService(self.uow)._load_cn_research_price_series(asset)
            if fallback is not None:
                series = [fallback]
        points = sorted(
            [
                point
                for series in series
                for point in series.points
                if point.timestamp <= as_of
            ],
            key=lambda item: item.timestamp,
        )[-90:]
        closes = [float(p.close) for p in points if p.close > 0]
        trade_date = points[-1].timestamp.date().isoformat() if points else None
        source = "frozen_price_series"
        if not closes and asset is not None:
            # Last-resort live kline fallback: fetch recent daily bars and
            # keep only those <= as_of so the snapshot stays as_of-pinned.
            # Degrades to network_unavailable when akshare is gated; never
            # synthesizes a number.  Only recent as_of yields data (akshare
            # returns recent bars).
            kline = _xystock_kline_closes(asset.ticker, as_of)
            if kline:
                closes = [close for _, close in kline]
                trade_date = kline[-1][0]
                source = "xystock_kline_fallback"
        returns = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        return MarketObservationFacts(
            latest_close=closes[-1] if closes else None,
            trade_date=trade_date,
            return_20d=None if len(closes) < 21 else closes[-1] / closes[-21] - 1,
            volatility_20d=(
                None if len(returns) < 20 else statistics.pstdev(returns[-20:]) * math.sqrt(252)
            ),
            sessions=len(closes),
            source=source,
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

    def _model_prediction_history(self, symbol: str) -> list[ModelHistoryPoint]:
        """Read archived evaluation predictions when the local artifact exists.

        This is deliberately a small, read-only view for the chart. It uses
        OOF/holdout rows only, groups the archived candidate models by decision
        date, and returns their mean prediction beside the realized outcome.
        If the compact Parquet artifact is not present, the chart simply keeps
        its current/future reference path.
        """
        path = self.project_root / "artifacts" / "long_term_training" / "latest.predictions.parquet"
        try:
            import pyarrow.parquet as parquet

            table = parquet.read_table(
                path,
                columns=["split", "symbol", "decision_date", "target", "score"],
            )
        except (ImportError, OSError, ValueError, KeyError):
            return []
        requested = "".join(ch for ch in symbol.upper() if ch.isalnum()).zfill(6)
        grouped: dict[str, list[tuple[float, float]]] = {}
        for row in table.to_pylist():
            split = str(row.get("split") or "")
            if split not in {"oof", "holdout"}:
                continue
            candidate = "".join(ch for ch in str(row.get("symbol") or "").upper() if ch.isalnum()).zfill(6)
            if candidate != requested:
                continue
            decision_date = str(row.get("decision_date") or "")[:10]
            try:
                predicted = float(row["score"])
                actual = float(row["target"])
            except (KeyError, TypeError, ValueError):
                continue
            if not decision_date or not math.isfinite(predicted) or not math.isfinite(actual):
                continue
            grouped.setdefault(decision_date, []).append((predicted, actual))
        return [
            ModelHistoryPoint(
                decision_date=date,
                predicted_return=statistics.fmean(item[0] for item in values),
                actual_return=statistics.fmean(item[1] for item in values),
                model_count=len(values),
            )
            for date, values in sorted(grouped.items())
        ]

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
    "ModelHistoryPoint",
    "AssetSnapshot",
    "AssetSnapshotService",
]
