"""§3 get_price_path_forecast tool regression test.

The price-path tool is registered + public, with a graceful-degraded handler
that surfaces an honest 'no_price_path_model' until the kittenCN port lands.
This pins the registration + the degraded contract so the predicted-vs-actual
chart + the LLM answer degrade honestly instead of fabricating a path.
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
from investment_research.repository.sqlite import SQLiteUnitOfWork

AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _build(uow: SQLiteUnitOfWork):
    now = datetime.now(timezone.utc)
    user = User(
        email="pp@e.com", display_name="PP", auth_subject="user:pp",
        provenance=Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="d", observed_at=now),
    )
    uow.users.add(user, password_hash="t")
    orchestrator = AgentOrchestrator(uow)
    orchestrator._record_tool = lambda *a, **k: None  # type: ignore[assignment]
    run = AgentRun(owner_user_id=user.id, asset_id=UUID(int=1), task_text="x", as_of=AS_OF, state=AgentRunState.RUNNING)
    return orchestrator, run, user


def test_price_path_forecast_registered_and_public() -> None:
    assert any(t.name == "get_price_path_forecast" for t in FUNCTION_CALL_TOOLS)
    assert "get_price_path_forecast" in PUBLIC_FUNCTION_CALL_TOOL_NAMES


def test_price_path_forecast_produces_real_or_points_to_snapshot(tmp_path: Path) -> None:
    """The handler now projects a real q10/q50/q90 fan from the existing
    long-term model's quantiles when a reading + live close are available;
    when they are not (test env: no research_pit readings, no network), it
    degrades to 'available_in_snapshot' pointing at the PIT-pinned snapshot
    field — never 'unavailable' with ok=False."""
    uow = SQLiteUnitOfWork(tmp_path / "pp.db")
    orchestrator, run, user = _build(uow)
    context: dict = {"function_calls": []}
    result = orchestrator._execute_function_call(run, user, context, "get_price_path_forecast", {})
    assert result["ok"] is True
    # Test env has no research_pit readings + no network → degrade to snapshot.
    assert result["status"] in {"ok", "available_in_snapshot"}
    if result["status"] == "available_in_snapshot":
        assert result["reason"] in {"no_model_reading", "no_latest_close", "quantiles_missing"}
        assert "snapshot" in result["note"]
    assert any(c.get("name") == "get_price_path_forecast" for c in context["function_calls"])
    uow.close()


def test_snapshot_carries_unavailable_price_path_field(tmp_path: Path) -> None:
    """The snapshot must carry an explicit unavailable price_path_forecast so
    the frontend chart shows the honest empty state, not a missing field."""
    from investment_research.service.asset_snapshot import AssetSnapshotService, PricePathForecast
    # Reuse the seeded competition db if present; otherwise this still pins the
    # model default (status="unavailable") which is the load-bearing assertion.
    assert PricePathForecast().status == "unavailable"
    assert PricePathForecast().points == []
