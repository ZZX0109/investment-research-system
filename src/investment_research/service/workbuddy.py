"""Read-only research facade shared by REST, MCP, and LLM tools.

This module intentionally contains no model-training, deployment, file-system,
or arbitrary URL capability.  It is the external assistant boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.research_forecasts import ResearchForecastService
from investment_research.service.research_lifecycle import ResearchPromotionStore
from investment_research.service.research_shadow import FileResearchShadowStore


WORKBUDDY_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_research_overview",
        "description": "Read the current research-only lifecycle, data tier, primary/fallback state, and blocking reasons.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "scope": "research.read",
    },
    {
        "name": "get_asset_research",
        "description": "Read an existing A-share research snapshot for one configured symbol. Returns data quality and abstain reasons when no conclusion is available.",
        "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "minLength": 3, "maxLength": 16}}, "required": ["symbol"], "additionalProperties": False},
        "scope": "research.read",
    },
    {
        "name": "compare_research_assets",
        "description": "Compare two existing configured research symbols using their latest frozen research snapshots.",
        "inputSchema": {"type": "object", "properties": {"left_symbol": {"type": "string"}, "right_symbol": {"type": "string"}}, "required": ["left_symbol", "right_symbol"], "additionalProperties": False},
        "scope": "research.read",
    },
    {
        "name": "get_price_trend",
        "description": "Read a bounded 90-session daily close and drawdown trend for an existing configured symbol.",
        "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "minLength": 3, "maxLength": 16}}, "required": ["symbol"], "additionalProperties": False},
        "scope": "research.read",
    },
    {
        "name": "get_shadow_performance",
        "description": "Read immutable research Shadow session and outcome progress, not a trading performance claim.",
        "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string", "maxLength": 16}}, "additionalProperties": False},
        "scope": "shadow.read",
    },
    {
        "name": "search_financial_knowledge",
        "description": "Search time-filtered financial knowledge with source URLs, availability time, and copyright-aware metadata.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 500}, "symbol": {"type": "string", "maxLength": 16}}, "required": ["query"], "additionalProperties": False},
        "scope": "knowledge.read",
    },
)


class WorkBuddyReadService:
    def __init__(self, uow: SQLiteUnitOfWork, *, shadow_root: Path | None = None) -> None:
        self.uow = uow
        self.shadow_root = shadow_root or Path.cwd() / "artifacts" / "research_shadow"

    def call(self, name: str, arguments: dict[str, Any], *, scopes: set[str]) -> dict[str, Any]:
        definition = next((item for item in WORKBUDDY_TOOLS if item["name"] == name), None)
        if definition is None:
            raise ValueError("tool_not_allowed")
        if definition["scope"] not in scopes:
            raise PermissionError("connector_scope_missing")
        if name == "get_research_overview":
            return self._overview()
        if name == "get_asset_research":
            return self._asset_research(self._symbol(arguments, "symbol"))
        if name == "compare_research_assets":
            return {
                "left": self._asset_research(self._symbol(arguments, "left_symbol")),
                "right": self._asset_research(self._symbol(arguments, "right_symbol")),
                "data_tier": "research_pit",
                "notice": "Comparison is research-only and is not a trading recommendation.",
            }
        if name == "get_price_trend":
            return self._price_trend(self._symbol(arguments, "symbol"))
        if name == "get_shadow_performance":
            symbol = arguments.get("symbol")
            if symbol is not None and not isinstance(symbol, str):
                raise ValueError("invalid_symbol")
            return self._shadow(symbol)
        if name == "search_financial_knowledge":
            query = arguments.get("query")
            if not isinstance(query, str) or len(query.strip()) < 2:
                raise ValueError("invalid_query")
            symbol = arguments.get("symbol")
            if symbol is not None and not isinstance(symbol, str):
                raise ValueError("invalid_symbol")
            return self._knowledge(query, symbol)
        raise ValueError("tool_not_allowed")

    @staticmethod
    def _symbol(arguments: dict[str, Any], key: str) -> str:
        value = arguments.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 16:
            raise ValueError("invalid_symbol")
        return value.strip().upper()

    def _overview(self) -> dict[str, Any]:
        jobs = [item for item in self.uow.ingestion_jobs.list_recent(limit=250) if str(item.job_type).startswith("research_")]
        latest: dict[str, Any] = {}
        for item in jobs:
            if str(item.job_type) not in latest:
                latest[str(item.job_type)] = item
        promotion_root = Path(__file__).resolve().parents[3] / "artifacts" / "research_promotions"
        primary: list[str] = []
        fallback: list[str] = []
        if promotion_root.is_dir():
            store = ResearchPromotionStore(promotion_root)
            for pointer in sorted(promotion_root.glob("*/current.json")):
                payload = store.read_current(scope=pointer.parent.name)
                if not payload:
                    continue
                candidate = payload.get("candidate") or {}
                previous = payload.get("previous") or {}
                if candidate.get("model_version"):
                    primary.append(f"{pointer.parent.name}:{candidate['model_version']}")
                if previous.get("model_version"):
                    fallback.append(f"{pointer.parent.name}:{previous['model_version']}")
        return {
            "data_tier": "research_pit", "status": "research_only", "deployment_ready": False,
            "latest_data_update": self._time(latest.get("research_daily_close"), "completed_at"),
            "latest_trade_date": self._time(latest.get("research_daily_close"), "trade_date"),
            "last_monitor": self._time(latest.get("research_weekly_monitor"), "completed_at"),
            "last_training": self._time(latest.get("research_monthly_training"), "completed_at"),
            "current_primary": primary, "current_fallback": fallback,
            "blocking_reasons": sorted({reason for item in jobs for reason in item.quality_issues}),
            "notice": "Models are updated by deterministic lifecycle jobs, not by the assistant.",
        }

    @staticmethod
    def _time(item: Any, field: str) -> str | None:
        value = getattr(item, field, None) if item is not None else None
        return None if value is None else str(value)

    def _asset_research(self, symbol: str) -> dict[str, Any]:
        asset = next((item for item in self.uow.assets.list() if item.ticker.upper() == symbol), None)
        if asset is None:
            return self._unavailable(symbol, "symbol_not_in_configured_research_workspace")
        runs = self.uow.analysis_runs.list_for_asset(str(asset.id))
        if not runs:
            return self._unavailable(symbol, "research_snapshot_missing")
        run = runs[0]
        try:
            bundle = ResearchForecastService(self.uow).for_run(str(run.id))
        except ValueError:
            return self._unavailable(symbol, "research_forecast_missing")
        return {
            "symbol": asset.ticker, "name": asset.name, "asset_type": asset.asset_type.value,
            "as_of": bundle.as_of, "data_tier": bundle.data_tier.value,
            "status": bundle.prediction_status, "training_status": bundle.training_status,
            "model_status": bundle.model_status, "evidence_status": bundle.evidence_status,
            "data_status": bundle.data_status.model_dump(mode="json"),
            "tasks": [item.model_dump(mode="json") for item in bundle.tasks],
            "direction_1d": None if bundle.direction_1d is None else bundle.direction_1d.model_dump(mode="json"),
            "direction_5d": None if bundle.direction_5d is None else bundle.direction_5d.model_dump(mode="json"),
            "return_20d": None if bundle.return_20d is None else bundle.return_20d.model_dump(mode="json"),
            "drawdown_20d": None if bundle.drawdown_20d is None else bundle.drawdown_20d.model_dump(mode="json"),
            "risk_level": bundle.risk_level, "influence_facts": bundle.influence_facts[:8],
            "model_disagreement": bundle.model_disagreement, "abstain_reasons": bundle.abstain_reasons,
            "blocking_reasons": bundle.blocking_reasons,
            "notice": "Research-only reference. It is not an investment recommendation or executable trading instruction.",
        }

    def _price_trend(self, symbol: str) -> dict[str, Any]:
        asset = next((item for item in self.uow.assets.list() if item.ticker.upper() == symbol), None)
        if asset is None:
            return self._unavailable(symbol, "symbol_not_in_configured_research_workspace")
        series = next((item for item in self.uow.price_series.list_for_asset(str(asset.id)) if item.interval == "1d"), None)
        if series is None or not series.points:
            return self._unavailable(symbol, "daily_price_series_missing")
        points = sorted(series.points, key=lambda item: item.timestamp)[-90:]
        close0 = points[0].close
        peak = close0
        values = []
        for point in points:
            peak = max(peak, point.close)
            values.append({"date": point.timestamp.date().isoformat(), "close": point.close, "return_pct": round((point.close / close0 - 1) * 100, 4), "drawdown_pct": round((point.close / peak - 1) * 100, 4)})
        return {"symbol": asset.ticker, "data_tier": "research_pit", "points": values, "source_notice": "Daily delayed research data; not real-time market data."}

    def _shadow(self, symbol: str | None) -> dict[str, Any]:
        summary = FileResearchShadowStore(self.shadow_root).summarize(market="cn", decision_context="close_confirmed", symbol=symbol)
        return {**summary.model_dump(mode="json"), "notice": "Shadow is an immutable forward research validation record, not a trading track record."}

    def _knowledge(self, query: str, symbol: str | None) -> dict[str, Any]:
        results = self.uow.financial_knowledge.search(query, as_of=datetime.now(timezone.utc), market="CN", symbol=symbol, limit=6)
        return {
            "data_tier": "research_pit", "query": query,
            "results": [{"title": item.document.title, "source_name": item.document.source_name, "source_url": item.document.source_url, "published_at": item.document.published_at, "available_at": item.document.available_at, "document_type": item.document.document_type, "matched_terms": item.matched_terms, "excerpt": item.document.content[:500]} for item in results],
            "notice": "Sources are reference material. Verify original documents before relying on them.",
        }

    @staticmethod
    def _unavailable(symbol: str, reason: str) -> dict[str, Any]:
        return {"symbol": symbol, "data_tier": "research_pit", "status": "unavailable", "blocking_reasons": [reason], "notice": "No result was inferred from missing data."}
