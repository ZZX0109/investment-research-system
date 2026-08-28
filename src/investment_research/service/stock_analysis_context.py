"""One bounded, read-only context bundle for an asset-scoped AI answer.

The assistant must not assemble a retail answer by independently choosing a
long-term scorecard, a live flow endpoint and a market endpoint.  This service
keeps that composition server-owned: frozen research facts come from the
conversation snapshot, while each live market source is refreshed per call and
can fail independently.
"""
from __future__ import annotations

import math
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from investment_research.integrations.base import FetchResult
from investment_research.service.long_term_research import long_term_evidence_balance

if TYPE_CHECKING:
    from investment_research.agent.models import AgentRun
    from investment_research.domain.models import User
    from investment_research.repository.sqlite import SQLiteUnitOfWork


class StockAnalysisContextService:
    """Build the single context payload supplied to a right-side AI turn."""

    def __init__(self, uow: "SQLiteUnitOfWork") -> None:
        self._uow = uow

    def build(
        self,
        *,
        run: "AgentRun",
        user: "User",
        snapshot: object | None,
        research_pit: dict[str, object] | None,
    ) -> dict[str, object]:
        del user  # Scope has already been fixed by AgentRun + conversation.
        symbol, name = self._asset_identity(run, snapshot, research_pit)
        frozen = self._frozen_context(snapshot, research_pit, symbol=symbol, as_of=run.as_of)
        anomaly = self._detect_anomaly(str(run.asset_id), run.as_of)
        # Live reads are intentionally a conversation feature.  Single-run
        # backend/audit callers keep their frozen context and never cause an
        # unexpected outbound request merely by replaying an old run.
        live = self._live_context(symbol) if snapshot is not None else {
            key: self._unavailable("not_refreshed_outside_conversation")
            for key in ("fund_flow", "margin", "dragon_tiger", "regime", "sector_rotation")
        }
        sources = self._sources(snapshot, research_pit, live, anomaly)
        unavailable = [
            key for key, value in live.items()
            if isinstance(value, dict) and value.get("status") != "ok"
        ]
        if anomaly.get("status") != "ok":
            unavailable.append("anomaly_detection")
        return {
            "ok": bool(symbol),
            "status": "partial" if unavailable else "ok",
            "asset": {"symbol": symbol or None, "name": name},
            "requested_as_of": run.as_of.isoformat(),
            "long_term": frozen["long_term"],
            "short_term_market": frozen["short_term_market"],
            "market_news": frozen["market_news"],
            "evidence": frozen["evidence"],
            "live_market": live,
            "anomaly_detection": anomaly,
            "sources": sources,
            "coverage": {
                "unavailable_components": unavailable,
                "long_term_status": frozen["long_term"].get("status"),
                "data_as_of": frozen["data_as_of"],
            },
        }

    def _asset_identity(
        self, run: "AgentRun", snapshot: object | None, research_pit: dict[str, object] | None,
    ) -> tuple[str, str | None]:
        if snapshot is not None:
            asset = getattr(snapshot, "asset", None)
            symbol = str(getattr(asset, "symbol", "") or "").strip().upper()
            if symbol:
                return symbol, getattr(asset, "name", None)
        if isinstance(research_pit, dict):
            symbol = str(research_pit.get("symbol") or "").strip().upper()
            if symbol:
                return symbol, str(research_pit.get("asset_name") or "") or None
        asset = self._uow.assets.get(str(run.asset_id))
        return ((str(asset.ticker).strip().upper(), asset.name) if asset is not None else ("", None))

    def _frozen_context(self, snapshot: object | None, research_pit: dict[str, object] | None, *, symbol: str, as_of: datetime) -> dict[str, object]:
        pit_long_term = research_pit.get("long_term_scorecard") if isinstance(research_pit, dict) else {}
        pit_long_term = pit_long_term if isinstance(pit_long_term, dict) else {}
        scorecard = getattr(snapshot, "scorecard", None) if snapshot is not None else pit_long_term.get("scorecard")
        readings = getattr(snapshot, "model_readings", None) if snapshot is not None else pit_long_term.get("long_term_model_readings")
        status = getattr(snapshot, "long_term_status", None) if snapshot is not None else pit_long_term.get("status")
        data_as_of = getattr(snapshot, "data_as_of", None) if snapshot is not None else None
        fact_cards = list(getattr(snapshot, "fact_cards", []) or []) if snapshot is not None else []
        line_items = list(getattr(snapshot, "line_items", []) or []) if snapshot is not None else []
        if snapshot is None and symbol:
            try:
                from investment_research.service.financial_knowledge import FinancialKnowledgeService
                result = FinancialKnowledgeService(self._uow).retrieve_line_items(symbol=symbol, as_of=as_of, market="CN")
                line_items = [item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item) for item in result.line_items]
            except Exception:
                line_items = []
        from investment_research.agent.evaluation import fundamental_coverage
        coverage = fundamental_coverage(line_items)
        critical_missing = [item for item in coverage.get("missing", []) if item in {"revenue", "net_profit"}]
        balance = long_term_evidence_balance(pit_long_term) if pit_long_term else {"available": False}
        market = getattr(snapshot, "market_observation", None) if snapshot is not None else None
        directional = getattr(snapshot, "directional_forecast", None) if snapshot is not None else None
        path = getattr(snapshot, "price_path_forecast", None) if snapshot is not None else None
        market_news = [
            item for item in list(getattr(snapshot, "market_news", []) or [])[:12]
            if isinstance(item, dict)
        ] if snapshot is not None else []
        blocking_reasons = list(getattr(snapshot, "long_term_blocking_reasons", []) or pit_long_term.get("blocking_reasons", []) or [])
        blocking_reasons.extend(f"fundamental_coverage_missing_{item}" for item in critical_missing)
        return {
            "data_as_of": None if data_as_of is None else str(data_as_of),
            "long_term": {
                "status": str(status or "unavailable"),
                "scorecard": scorecard,
                "model_readings": readings,
                "evidence_balance": balance,
                "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
                "fundamental_coverage": coverage,
            },
            "short_term_market": {
                "price": None if market is None else {
                    "latest_close": getattr(market, "latest_close", None),
                    "trade_date": getattr(market, "trade_date", None),
                    "return_20d": getattr(market, "return_20d", None),
                    "volatility_20d": getattr(market, "volatility_20d", None),
                    "source": getattr(market, "source", None),
                },
                "directional_forecasts": None if directional is None else {
                    "available": getattr(directional, "available", False),
                    "direction_1d": getattr(directional, "direction_1d", None),
                    "direction_5d": getattr(directional, "direction_5d", None),
                    "return_20d": getattr(directional, "return_20d", None),
                    "drawdown_20d": getattr(directional, "drawdown_20d", None),
                },
                "catboost_horizons": getattr(snapshot, "catboost_short_term_horizons", None) if snapshot is not None else None,
                "price_path": None if path is None else {
                    "status": getattr(path, "status", None), "model": getattr(path, "model", None),
                    "horizon_days": getattr(path, "horizon_days", None),
                    "mean_abs_error_pct": getattr(path, "mean_abs_error_pct", None),
                },
            },
            "market_news": market_news,
            "evidence": {"fact_cards": fact_cards[:12], "financial_line_items": line_items[:12]},
        }

    def _live_context(self, symbol: str) -> dict[str, dict[str, object]]:
        if not symbol:
            return {key: self._unavailable("no_symbol") for key in ("fund_flow", "margin", "dragon_tiger", "regime", "sector_rotation")}
        from investment_research.integrations.fortune.data_services import (
            dragon_tiger, fund_flow, margin, regime, sector_rotation,
        )
        fetches: dict[str, Callable[[], FetchResult]] = {
            "fund_flow": lambda: fund_flow.fetch_northbound_flow(symbol),
            "margin": lambda: margin.fetch_margin(symbol),
            "dragon_tiger": lambda: dragon_tiger.fetch_dragon_tiger(symbol),
            "regime": lambda: regime.detect_regime(symbol),
            "sector_rotation": sector_rotation.fetch_sector_rotation,
        }
        results: dict[str, dict[str, object]] = {}
        with ThreadPoolExecutor(max_workers=len(fetches)) as executor:
            futures = {executor.submit(fetch): key for key, fetch in fetches.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    fetched = future.result()
                    results[key] = self._fetch_payload(fetched)
                except Exception as exc:  # adapter boundary: one source cannot abort the answer
                    results[key] = self._unavailable("error", type(exc).__name__)
        return results

    @staticmethod
    def _fetch_payload(fetched: FetchResult) -> dict[str, object]:
        captured = datetime.now().astimezone().isoformat()
        return {
            "status": fetched.status, "available": fetched.available, "degraded": fetched.degraded,
            "provider": fetched.provider, "captured_at": captured, "data": fetched.data,
            "error": fetched.error,
        }

    @staticmethod
    def _unavailable(status: str, error: str | None = None) -> dict[str, object]:
        return {"status": status, "available": False, "degraded": True, "provider": None, "captured_at": None, "data": None, "error": error}

    def _detect_anomaly(self, asset_id: str, as_of: datetime) -> dict[str, object]:
        points = sorted(
            [point for series in self._uow.price_series.list_for_asset(asset_id)
             if series.interval == "1d" and series.series_role in {None, "asset"}
             for point in series.points if point.timestamp <= as_of and point.close > 0],
            key=lambda point: point.timestamp,
        )[-60:]
        if len(points) < 21:
            return {"status": "insufficient_data", "available": False, "message": "近期有效交易数据不足，暂无法判断异常。", "signals": []}
        returns = [math.log(points[i].close / points[i - 1].close) for i in range(1, len(points)) if points[i - 1].close > 0]
        baseline_returns = returns[-21:-1]
        current_return = returns[-1] if returns else None
        return_z = self._zscore(current_return, baseline_returns)
        volumes = [float(point.volume or 0.0) for point in points]
        prior_volumes = volumes[-21:-1]
        current_volume = volumes[-1]
        volume_mean = statistics.fmean(prior_volumes) if prior_volumes else 0.0
        volume_sd = statistics.pstdev(prior_volumes) if len(prior_volumes) > 1 else 0.0
        price_abnormal = return_z is not None and abs(return_z) >= 2.5
        volume_abnormal = (current_volume > volume_mean + 2.5 * volume_sd) if volume_sd > 0 else (volume_mean > 0 and current_volume >= 2 * volume_mean)
        signals: list[dict[str, object]] = []
        if price_abnormal:
            signals.append({"type": "price_move", "message": "当日价格变化明显偏离近期常态。", "z_score": round(return_z, 2)})
        if volume_abnormal:
            signals.append({"type": "volume_surge", "message": "当日成交量明显高于近期常态。", "ratio_to_20d_average": round(current_volume / volume_mean, 2) if volume_mean else None})
        return {
            "status": "ok", "available": True, "as_of": points[-1].timestamp.isoformat(),
            "signals": signals, "summary": "未发现明显价格或成交量异常。" if not signals else "发现需要结合后续信息观察的市场异常。",
            "metrics": {"return_z_score": None if return_z is None else round(return_z, 2), "volume_ratio_to_20d_average": round(current_volume / volume_mean, 2) if volume_mean else None},
        }

    @staticmethod
    def _zscore(value: float | None, values: list[float]) -> float | None:
        if value is None or len(values) < 2:
            return None
        deviation = statistics.pstdev(values)
        return 0.0 if deviation == 0 else (value - statistics.fmean(values)) / deviation

    @staticmethod
    def _sources(snapshot: object | None, research_pit: dict[str, object] | None, live: dict[str, dict[str, object]], anomaly: dict[str, object]) -> list[dict[str, object]]:
        sources: list[dict[str, object]] = []
        for card in list(getattr(snapshot, "fact_cards", []) or [])[:12]:
            if not isinstance(card, dict):
                continue
            sources.append({"citation_id": card.get("citation_id") or f"fact:{card.get('revision_id', '')}", "title": card.get("claim") or card.get("topic") or "公司经营事实", "source": card.get("source_name") or "知识库", "url": card.get("source_url"), "published_at": card.get("published_at"), "kind": "knowledge"})
        for index, item in enumerate(list(getattr(snapshot, "market_news", []) or [])[:12]):
            if not isinstance(item, dict) or not item.get("title"):
                continue
            is_notice = item.get("kind") == "notice"
            sources.append({
                "citation_id": f"market-news:{index}:{str(item.get('title'))[:32]}",
                "title": item.get("title"),
                "source": item.get("source") or ("公司公告" if is_notice else "个股新闻"),
                "url": item.get("url"),
                "published_at": item.get("published_at") or item.get("date"),
                "kind": "announcement" if is_notice else "news",
            })
        long_term = research_pit.get("long_term_scorecard") if isinstance(research_pit, dict) else None
        if isinstance(long_term, dict):
            sources.append({"citation_id": "long-term-scorecard", "title": "长期研究评分卡", "source": "本地长期研究快照", "url": long_term.get("source_ref"), "published_at": getattr(snapshot, "data_as_of", None), "kind": "model"})
        for key, value in live.items():
            if value.get("available"):
                sources.append({"citation_id": f"live:{key}", "title": {"fund_flow": "北向资金", "margin": "融资融券", "dragon_tiger": "龙虎榜", "regime": "市场状态", "sector_rotation": "行业轮动"}[key], "source": value.get("provider") or "实时市场数据", "url": None, "published_at": value.get("captured_at"), "kind": "market"})
        if anomaly.get("available"):
            sources.append({"citation_id": "market-anomaly", "title": "价格与成交量异常检测", "source": "本地日线数据", "url": None, "published_at": anomaly.get("as_of"), "kind": "calculation"})
        return sources
