"""§3 market-sentiment function-tool regression tests.

The four new asset-scoped live-fetch tools (``get_fund_flow`` /
``get_margin_data`` / ``get_dragon_tiger`` / ``get_current_regime``) wrap the
fortune/xystock integration adapters.  These tests pin the handler contract:
symbol resolution from the research_pit, adapter result pass-through, graceful
degradation, and recording into ``function_calls``.  Adapters are monkeypatched
so no network is touched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from investment_research.agent.models import AgentRun, AgentRunState
from investment_research.agent.service import (
    FUNCTION_CALL_TOOLS,
    PUBLIC_FUNCTION_CALL_TOOL_NAMES,
    AgentOrchestrator,
)
from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.models import User
from investment_research.integrations.base import FetchResult
from investment_research.integrations.fortune.data_services import (
    dragon_tiger,
    fund_flow,
    margin,
    regime,
    sector_rotation,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork

AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)

SENTIMENT_TOOLS = ("get_fund_flow", "get_margin_data", "get_dragon_tiger", "get_current_regime")
ADAPTERS = {
    "get_fund_flow": (fund_flow, "fetch_northbound_flow"),
    "get_margin_data": (margin, "fetch_margin"),
    "get_dragon_tiger": (dragon_tiger, "fetch_dragon_tiger"),
    "get_current_regime": (regime, "detect_regime"),
}


def _build(uow: SQLiteUnitOfWork):
    now = datetime.now(timezone.utc)
    user = User(
        email="ms@e.com", display_name="MS", auth_subject="user:ms",
        provenance=Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="d", observed_at=now),
    )
    uow.users.add(user, password_hash="t")
    orchestrator = AgentOrchestrator(uow)
    orchestrator._record_tool = lambda *a, **k: None  # type: ignore[assignment]
    run = AgentRun(owner_user_id=user.id, asset_id=UUID(int=1), task_text="x", as_of=AS_OF, state=AgentRunState.RUNNING)
    return orchestrator, run, user


def test_sentiment_tools_registered_and_public() -> None:
    for name in SENTIMENT_TOOLS:
        assert any(t.name == name for t in FUNCTION_CALL_TOOLS), name
        assert name in PUBLIC_FUNCTION_CALL_TOOL_NAMES


def test_each_sentiment_tool_passes_through_adapter_data(
    tmp_path: Path, monkeypatch
) -> None:
    for name in SENTIMENT_TOOLS:
        uow = SQLiteUnitOfWork(tmp_path / f"{name}.db")
        orchestrator, run, user = _build(uow)
        context: dict = {"function_calls": [], "research_pit": {"symbol": "600519"}}
        module, fn_name = ADAPTERS[name]
        sentinel = {"symbol": "600519", "marker": name}
        monkeypatch.setattr(
            module, fn_name,
            lambda sym, _name=name: FetchResult(ok=True, status="ok", provider="mock", data=sentinel_for(_name)),
        )
        result = orchestrator._execute_function_call(run, user, context, name, {})
        assert result["ok"] is True, name
        assert result["status"] == "ok", name
        assert result["symbol"] == "600519", name
        assert result["data"] is not None, name
        assert any(c.get("name") == name for c in context["function_calls"]), name
        uow.close()


def sentinel_for(name: str) -> dict:
    return {"symbol": "600519", "tool": name}


def test_sentiment_tool_degrades_when_adapter_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "ms2.db")
    orchestrator, run, user = _build(uow)
    context: dict = {"function_calls": [], "research_pit": {"symbol": "600519"}}
    module, fn_name = ADAPTERS["get_fund_flow"]
    monkeypatch.setattr(
        module, fn_name,
        lambda sym: FetchResult(ok=False, status="network_unavailable", provider="mock", error="TimeoutError", degraded=True),
    )
    result = orchestrator._execute_function_call(run, user, context, "get_fund_flow", {})
    assert result["ok"] is False
    assert result["status"] == "network_unavailable"
    assert result["degraded"] is True
    uow.close()


def test_sentiment_tool_no_symbol_when_pit_missing_and_asset_unseeded(
    tmp_path: Path, monkeypatch
) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "ms3.db")
    orchestrator, run, user = _build(uow)
    context: dict = {"function_calls": []}  # no research_pit, no seeded asset
    module, fn_name = ADAPTERS["get_current_regime"]
    called: list[str] = []
    monkeypatch.setattr(module, fn_name, lambda sym: called.append(sym) or FetchResult(ok=True, status="ok", provider="mock", data={}))
    result = orchestrator._execute_function_call(run, user, context, "get_current_regime", {})
    assert result["ok"] is False
    assert result["status"] == "no_symbol"
    assert called == []  # adapter never invoked when symbol unresolved


def test_sector_rotation_registered_and_public() -> None:
    """§3 row-2: the 4th market-sentiment dimension (sector rotation) is a
    registered public tool."""
    assert any(t.name == "get_sector_rotation" for t in FUNCTION_CALL_TOOLS)
    assert "get_sector_rotation" in PUBLIC_FUNCTION_CALL_TOOL_NAMES


def test_sector_rotation_tool_is_market_wide_no_symbol(tmp_path: Path, monkeypatch) -> None:
    """get_sector_rotation is market-wide (no symbol arg) — the handler runs
    even without a research_pit symbol + returns symbol=None + the adapter
    readout (top gainers/losers)."""
    uow = SQLiteUnitOfWork(tmp_path / "sr.db")
    orchestrator, run, user = _build(uow)
    context: dict = {"function_calls": []}  # no research_pit, no symbol
    readout = {
        "as_of": "2026-08-19",
        "gainers": [{"sector": "电子", "net_flow": 12.3}, {"sector": "医药", "net_flow": 4.1}],
        "losers": [{"sector": "银行", "net_flow": -8.7}],
    }
    monkeypatch.setattr(
        sector_rotation, "fetch_sector_rotation",
        lambda: FetchResult(ok=True, status="ok", provider="mock", data=readout),
    )
    result = orchestrator._execute_function_call(run, user, context, "get_sector_rotation", {})
    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["symbol"] is None  # market-wide
    assert result["data"] == readout
    assert any(c.get("name") == "get_sector_rotation" for c in context["function_calls"])
    uow.close()


def test_sector_rotation_degrades_when_adapter_unavailable(tmp_path: Path, monkeypatch) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "sr2.db")
    orchestrator, run, user = _build(uow)
    context: dict = {"function_calls": []}
    monkeypatch.setattr(
        sector_rotation, "fetch_sector_rotation",
        lambda: FetchResult(ok=False, status="network_unavailable", provider="mock", error="TimeoutError", degraded=True),
    )
    result = orchestrator._execute_function_call(run, user, context, "get_sector_rotation", {})
    assert result["ok"] is False
    assert result["status"] == "network_unavailable"
    assert result["degraded"] is True
    uow.close()
    uow.close()
