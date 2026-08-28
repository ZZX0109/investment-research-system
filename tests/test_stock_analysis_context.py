"""Regression tests for the one-call right-sidebar stock context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from investment_research.agent.models import AgentRun, AgentRunState
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, PricePoint, PriceSeries, User
from investment_research.integrations.base import FetchResult
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.stock_analysis_context import StockAnalysisContextService


def _setup(tmp_path, *, volume_spike: bool = False, price_spike: bool = False, days: int = 60):
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    provenance = Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="test", observed_at=now)
    uow = SQLiteUnitOfWork(tmp_path / "context.db")
    user = User(email="context@example.com", display_name="Context", auth_subject="context", provenance=provenance)
    uow.users.add(user, password_hash="x")
    asset = Asset(ticker="600519", name="测试公司", asset_type=AssetType.EQUITY, provenance=provenance)
    uow.assets.add(asset)
    points = []
    close = 100.0
    for index in range(days):
        if index == days - 1 and price_spike:
            close *= 1.2
        else:
            close *= 1.001 if index % 2 else 0.999
        points.append(PricePoint(asset_id=asset.id, timestamp=now - timedelta(days=days - 1 - index), open=close, high=close, low=close, close=close, volume=10_000 if not (volume_spike and index == days - 1) else 100_000, provenance=provenance))
    uow.price_series.add(PriceSeries(asset_id=asset.id, interval="1d", points=points, provenance=provenance))
    run = AgentRun(owner_user_id=user.id, asset_id=asset.id, task_text="长期风险", as_of=now, state=AgentRunState.RUNNING)
    snapshot = SimpleNamespace(
        asset=SimpleNamespace(symbol="600519", name="测试公司"), scorecard={"long_term_quality": 70},
        model_readings={}, long_term_status="available", long_term_blocking_reasons=[], data_as_of="2026-08-20",
        fact_cards=[], line_items=[], market_observation=SimpleNamespace(latest_close=close, trade_date="2026-08-20", return_20d=0.01, volatility_20d=0.2, source="frozen_price_series"),
        directional_forecast=None, price_path_forecast=None, catboost_short_term_horizons=None,
    )
    return uow, user, run, snapshot


def _mock_live(monkeypatch, *, fund_ok: bool = True) -> None:
    from investment_research.integrations.fortune.data_services import dragon_tiger, fund_flow, margin, regime, sector_rotation

    monkeypatch.setattr(fund_flow, "fetch_northbound_flow", lambda _symbol: FetchResult(ok=fund_ok, status="ok" if fund_ok else "network_unavailable", provider="mock", data={"value": 1} if fund_ok else None, degraded=not fund_ok))
    monkeypatch.setattr(margin, "fetch_margin", lambda _symbol: FetchResult(ok=True, status="ok", provider="mock", data={"balance": 1}))
    monkeypatch.setattr(dragon_tiger, "fetch_dragon_tiger", lambda _symbol: FetchResult(ok=True, status="ok", provider="mock", data=[]))
    monkeypatch.setattr(regime, "detect_regime", lambda _symbol: FetchResult(ok=True, status="ok", provider="mock", data={"trend": "sideways", "volatility": "normal"}))
    monkeypatch.setattr(sector_rotation, "fetch_sector_rotation", lambda: FetchResult(ok=True, status="ok", provider="mock", data={"gainers": []}))


def test_context_collects_all_sections_and_degrades_one_live_source(tmp_path, monkeypatch) -> None:
    uow, user, run, snapshot = _setup(tmp_path)
    _mock_live(monkeypatch, fund_ok=False)
    result = StockAnalysisContextService(uow).build(run=run, user=user, snapshot=snapshot, research_pit={"long_term_scorecard": {"status": "available", "scorecard": {}}})
    assert result["status"] == "partial"
    assert set(result["live_market"]) == {"fund_flow", "margin", "dragon_tiger", "regime", "sector_rotation"}
    assert result["live_market"]["fund_flow"]["status"] == "network_unavailable"
    assert result["long_term"]["status"] == "available"
    assert result["short_term_market"]["price"]["latest_close"] is not None
    uow.close()


def test_context_detects_price_and_volume_anomalies(tmp_path, monkeypatch) -> None:
    uow, user, run, snapshot = _setup(tmp_path, volume_spike=True, price_spike=True)
    _mock_live(monkeypatch)
    result = StockAnalysisContextService(uow).build(run=run, user=user, snapshot=snapshot, research_pit=None)
    types = {signal["type"] for signal in result["anomaly_detection"]["signals"]}
    assert {"price_move", "volume_surge"}.issubset(types)
    uow.close()


def test_context_marks_anomaly_as_unavailable_with_short_history(tmp_path, monkeypatch) -> None:
    uow, user, run, snapshot = _setup(tmp_path, days=20)
    _mock_live(monkeypatch)
    result = StockAnalysisContextService(uow).build(run=run, user=user, snapshot=snapshot, research_pit=None)
    assert result["anomaly_detection"]["status"] == "insufficient_data"
    uow.close()
