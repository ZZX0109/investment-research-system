"""Phase 4 (A3) — ConversationAgentService is the multi-turn AI path split out
of the route / orchestrator god-class.

Guards the structural split: the service appends the user question, builds the
shared snapshot, runs the snapshot-pinned turn, persists the assistant answer,
and returns (run, refreshed_session).  Uses a recording orchestrator so the
flow is verified fast + hermetic (the run-execution behaviour itself is guarded
by test_conversation_snapshot_wiring + test_competition_demo_flow).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from investment_research.agent.models import AgentRun, AgentRunState
from investment_research.agent.service import AgentOrchestrator
from investment_research.domain.conversation import ConversationMessage, ConversationSession
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.conversation_agent import ConversationAgentService
from investment_research.service.dashboard_read import DashboardReadService

AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


class _RecordingOrchestrator(AgentOrchestrator):
    """Records the snapshot + conversation_id passed to create_and_execute and
    returns a stub completed run (keeps the test fast + hermetic)."""

    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        super().__init__(uow)
        self.recorded_snapshot = None
        self.recorded_conversation_id: str | None = None
        self.recorded_tool_overrides: dict | None = None

    def create_and_execute(  # type: ignore[override]
        self, *, user, asset_id, task_text, as_of,
        provider_profile_id=None, user_preference="conservative",
        conversation_id=None, snapshot=None, tool_overrides=None,
    ) -> AgentRun:
        self.recorded_snapshot = snapshot
        self.recorded_conversation_id = conversation_id
        self.recorded_tool_overrides = tool_overrides
        return AgentRun(
            owner_user_id=user.id, asset_id=UUID(asset_id), task_text=task_text,
            as_of=as_of, state=AgentRunState.COMPLETED, correlation_id="cas-test",
        )


def _make_session(uow: SQLiteUnitOfWork, *, user_id, asset_id) -> ConversationSession:
    session = ConversationSession(
        user_id=user_id, asset_id=asset_id, as_of=AS_OF, title="cas",
    )
    uow.conversations.add_session(session)
    # touch to persist + return a fetched copy with messages=[]
    return uow.conversations.get_session(str(session.id), owner_user_id=user_id)


def test_conversation_agent_service_answer_round_trip(tmp_path: Path) -> None:
    from test_api_routes import configure_authenticated_client

    client = configure_authenticated_client(tmp_path, "cas.db")
    uow = SQLiteUnitOfWork(tmp_path / "cas.db")
    auth_user = uow.users.get_by_email("investor@example.com").user

    # create an owned asset via the API so the snapshot service can read it.
    import json
    created = client.post(
        "/api/v1/assets",
        json={
            "ticker": "600519", "name": "示例白酒", "asset_type": "equity",
            "currency": "cny", "exchange": "XSHG",
            "data_mode": "real", "source_type": "real", "source_name": "d",
            "observed_at": AS_OF.isoformat(), "confidence": 0.9,
        },
    )
    assert created.status_code == 201
    asset_id = created.json()["id"]

    session = _make_session(uow, user_id=auth_user.id, asset_id=UUID(asset_id))

    recorder = _RecordingOrchestrator(uow)
    service = ConversationAgentService(
        uow,
        dashboard=DashboardReadService(uow, project_root=Path(__file__).resolve().parent.parent),
        orchestrator=recorder,
    )
    run, refreshed = service.answer(
        session_id=str(session.id), content="经营变化与盈利拐点",
        provider_profile_id=None, user_preference="conservative", user=auth_user,
    )

    # The snapshot was built (pinned to session as_of) + fed to the run.
    assert recorder.recorded_conversation_id == str(session.id)
    assert recorder.recorded_snapshot is not None
    assert recorder.recorded_snapshot.as_of == AS_OF
    assert recorder.recorded_snapshot.asset.symbol == "600519"
    # Phase 4 (A3) tool-skip: the KB-hitting asset-scoped tools are short-circuited
    # via tool_overrides built from the snapshot (so the turn stops re-running them).
    overrides = recorder.recorded_tool_overrides
    assert overrides is not None
    assert set(overrides) == {"get_financial_line_items", "get_long_term_fact_cards"}
    assert overrides["get_financial_line_items"]["ok"] is True
    assert overrides["get_financial_line_items"]["line_items"] == recorder.recorded_snapshot.line_items
    assert overrides["get_long_term_fact_cards"]["fact_cards"] == recorder.recorded_snapshot.fact_cards
    # The assistant answer was persisted as the 2nd message (after the user Q).
    assert [m.role for m in refreshed.messages] == ["user", "assistant"]
    assert run.state == AgentRunState.COMPLETED
    uow.close()


def test_conversation_agent_service_unknown_session_raises(tmp_path: Path) -> None:
    from test_api_routes import configure_authenticated_client

    configure_authenticated_client(tmp_path, "cas-unknown.db")
    uow = SQLiteUnitOfWork(tmp_path / "cas-unknown.db")
    auth_user = uow.users.get_by_email("investor@example.com").user
    recorder = _RecordingOrchestrator(uow)
    service = ConversationAgentService(
        uow,
        dashboard=DashboardReadService(uow, project_root=Path(__file__).resolve().parent.parent),
        orchestrator=recorder,
    )
    import pytest
    with pytest.raises(LookupError):
        service.answer(
            session_id="00000000-0000-0000-0000-000000000000",
            content="x", provider_profile_id=None, user_preference="conservative",
            user=auth_user,
        )
    uow.close()


def test_tool_overrides_short_circuit_kb_tools_without_running_them(tmp_path: Path) -> None:
    """Phase 4 (A3) acceptance (1): the conversation path does not trigger the
    KB-hitting asset-scoped tools when tool_overrides is present.  This unit-tests
    the _execute_function_call injection point directly: with overrides set, the
    tool returns the override verbatim and the underlying KB service is never
    called.
    """
    from investment_research.agent.service import AgentOrchestrator
    from investment_research.service import conversation_agent as ca_mod

    uow = SQLiteUnitOfWork(tmp_path / "tool-override.db")
    now = datetime.now(timezone.utc)
    from investment_research.domain.base import Provenance
    from investment_research.domain.enums import DataMode, DataSourceType
    from investment_research.domain.models import User
    prov = Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="d", observed_at=now)
    user = User(email="to@e.com", display_name="TO", auth_subject="user:to", provenance=prov)
    uow.users.add(user, password_hash="t")
    orchestrator = AgentOrchestrator(uow)
    # _record_tool writes to the DB (run FK); stub it so the test isolates the
    # injection logic without persisting a full run.
    orchestrator._record_tool = lambda *a, **k: None  # type: ignore

    # A stub run + an empty context carrying the override for the line-items tool.
    run = AgentRun(owner_user_id=user.id, asset_id=UUID(int=1), task_text="x", as_of=AS_OF, state=AgentRunState.RUNNING)
    override = {"ok": True, "symbol": "600519", "count": 0, "line_items": [], "coverage_status": "complete"}
    context = {"tool_overrides": {"get_financial_line_items": override}, "function_calls": []}

    # Spy on the KB service so we can prove it was never called.
    called: list[str] = []

    class _SpyKB:
        def retrieve_line_items(self, *a, **k):
            called.append("retrieve_line_items")
            from investment_research.service.financial_knowledge import LineItemQueryResult
            return LineItemQueryResult(line_items=[], coverage_status="complete", coverage_reasons=[])

    import investment_research.agent.service as svc_mod
    orig = svc_mod.FinancialKnowledgeService
    svc_mod.FinancialKnowledgeService = lambda uow: _SpyKB()  # type: ignore
    try:
        result = orchestrator._execute_function_call(run, user, context, "get_financial_line_items", {})
    finally:
        svc_mod.FinancialKnowledgeService = orig  # type: ignore

    # The override short-circuited the tool; the KB service was never called.
    assert result == override
    assert called == []
    # The override result was recorded into function_calls (so the abstain gate /
    # answer builder see it as if the tool had run).
    assert context["function_calls"] == [{"name": "get_financial_line_items", "result": override}]
    uow.close()
