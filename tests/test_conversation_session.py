"""Phase 3 acceptance: multi-turn conversation memory.

Guards the memory layer of the 选股 → 仪表盘 → AI chain:

* ``ConversationSession`` pins one asset + one as_of and accumulates
  ``ConversationMessage`` turns (owner-scoped, sequence-ordered);
* the conversation routes create/list/get a session without triggering an
  AgentRun (cheap read path);
* ``AgentOrchestrator._prior_turns`` loads a session's prior turns so the next
  answer can reference the previous round ("展开刚才...") — the single-turn
  ``AgentRun`` path (no ``conversation_id``) stays byte-identical.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_research.agent.models import AgentRun
from investment_research.agent.service import AgentOrchestrator
from investment_research.domain.base import Provenance
from investment_research.domain.conversation import (
    ConversationMessage,
    ConversationSession,
)
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.asset_snapshot import AssetSnapshotService

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _provenance(at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="competition-demo",
        observed_at=at,
    )


def _make_world(tmp_path: Path, *, ticker: str = "600519", name: str = "示例白酒"):
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "conv.db")
    user = User(
        email="judge@example.com",
        display_name="Judge",
        auth_subject="user:judge",
        provenance=_provenance(now),
    )
    uow.users.add(user, password_hash="test")
    asset = Asset(ticker=ticker, name=name, asset_type=AssetType.EQUITY, provenance=_provenance(now))
    uow.assets.add(asset)
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)
    return uow, user, asset, now


def _load_seeder(project_root: Path):
    scripts_dir = str(project_root / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def test_conversation_session_round_trips_prior_turns(tmp_path: Path) -> None:
    uow, user, asset, _ = _make_world(tmp_path)
    session = ConversationSession(
        user_id=user.id, asset_id=asset.id, as_of=AS_OF, title="经营变化"
    )
    uow.conversations.add_session(session)

    uow.conversations.add_message(
        ConversationMessage(session_id=session.id, role="user", content="盈利拐点？")
    )
    uow.conversations.add_message(
        ConversationMessage(
            session_id=session.id,
            role="assistant",
            content="前一轮结论：盈利拐点尚缺证据，需等待下一期财务科目。",
            snapshot_as_of=AS_OF.isoformat(),
        )
    )
    uow.conversations.add_message(
        ConversationMessage(session_id=session.id, role="user", content="展开刚才说的盈利拐点")
    )

    fetched = uow.conversations.get_session(str(session.id), owner_user_id=user.id)
    assert fetched is not None
    assert fetched.asset_id == asset.id
    assert fetched.as_of == AS_OF
    assert [m.sequence for m in fetched.messages] == [1, 2, 3]
    assert [m.role for m in fetched.messages] == ["user", "assistant", "user"]
    assert fetched.messages[1].snapshot_as_of == AS_OF.isoformat()

    # Owner-scoped: another user cannot read this session.
    other = User(
        email="other@example.com",
        display_name="Other",
        auth_subject="user:other",
        provenance=_provenance(datetime.now(timezone.utc)),
    )
    uow.users.add(other, password_hash="test")
    assert uow.conversations.get_session(str(session.id), owner_user_id=other.id) is None


def test_conversation_routes_crud_without_running_agent(tmp_path: Path) -> None:
    """Creating / listing / getting a conversation is cheap (no AgentRun)."""
    from investment_research.main import app
    from test_api_routes import configure_authenticated_client

    client = configure_authenticated_client(tmp_path, "conv-routes.db")
    try:
        created = client.post(
            "/api/v1/assets",
            json={
                "ticker": "600519",
                "name": "示例白酒",
                "asset_type": AssetType.EQUITY.value,
                "currency": "cny",
                "exchange": "XSHG",
                "data_mode": DataMode.REAL.value,
                "source_type": DataSourceType.REAL.value,
                "source_name": "competition-demo",
                "observed_at": AS_OF.isoformat(),
                "confidence": 0.97,
            },
        )
        assert created.status_code == 201
        asset_id = created.json()["id"]

        # POST /conversations
        conv = client.post(
            "/api/v1/conversations",
            json={"asset_id": asset_id, "as_of": AS_OF.isoformat(), "title": "经营变化"},
        )
        assert conv.status_code == 201
        body = conv.json()
        assert body["asset_id"] == asset_id
        assert body["as_of"].startswith("2026-08-16T00:00:00")
        assert body["title"] == "经营变化"
        assert body["messages"] == []
        session_id = body["id"]

        # GET /conversations/{id}
        got = client.get(f"/api/v1/conversations/{session_id}")
        assert got.status_code == 200
        assert got.json()["id"] == session_id

        # GET /conversations (list)
        listed = client.get("/api/v1/conversations")
        assert listed.status_code == 200
        assert any(item["id"] == session_id for item in listed.json())

        # 404 for unknown session / asset
        assert client.get("/api/v1/conversations/does-not-exist").status_code == 404
        assert client.post(
            "/api/v1/conversations",
            json={"asset_id": "no-such-asset", "as_of": AS_OF.isoformat()},
        ).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_build_plain_answer_references_prior_turn_when_conversation_bound(tmp_path: Path) -> None:
    """An AgentRun bound to a conversation references the previous round's
    conclusion; the single-turn path (no conversation_id) is byte-identical."""
    uow, user, asset, _ = _make_world(tmp_path)
    seeder = _load_seeder(REPO_ROOT)
    seeder._run_seed_into(uow)

    session = ConversationSession(
        user_id=user.id, asset_id=asset.id, as_of=AS_OF, title="经营变化"
    )
    uow.conversations.add_session(session)
    uow.conversations.add_message(
        ConversationMessage(session_id=session.id, role="user", content="盈利拐点？")
    )
    uow.conversations.add_message(
        ConversationMessage(
            session_id=session.id,
            role="assistant",
            content="前一轮结论：盈利拐点尚缺证据，需等待下一期财务科目。",
            snapshot_as_of=AS_OF.isoformat(),
        )
    )

    orchestrator = AgentOrchestrator(uow, project_root=REPO_ROOT)
    prior_turns = orchestrator._prior_turns(str(session.id))
    assert [turn["role"] for turn in prior_turns] == ["user", "assistant"]
    assert "前一轮结论" in prior_turns[-1]["content"]

    snap = AssetSnapshotService(uow, project_root=REPO_ROOT).snapshot(
        str(asset.id), as_of=AS_OF, user=user
    )
    run = AgentRun(
        owner_user_id=user.id,
        asset_id=asset.id,
        task_text="展开刚才说的盈利拐点",
        as_of=AS_OF,
        correlation_id="conv-test",
    )
    context = {
        "function_calls": [],
        "long_term_abstain_reasons": [],
        "prior_turns": prior_turns,
    }
    answer = orchestrator._build_plain_answer(
        run, context, research_pit=None, abstained=False, llm_generated=False, snapshot=snap
    )
    # The prior-round conclusion surfaces in the long-term changes section.
    assert "前一轮" in answer["long_term_changes"]
    assert "盈利拐点尚缺证据" in answer["long_term_changes"]

    # Single-turn path (no prior_turns) is byte-identical — no clause.
    single_context = {"function_calls": [], "long_term_abstain_reasons": []}
    single_answer = orchestrator._build_plain_answer(
        run, single_context, research_pit=None, abstained=False, llm_generated=False, snapshot=snap
    )
    assert "前一轮" not in single_answer["long_term_changes"]
    # Everything else identical between the two answers except the clause.
    assert single_answer["business_condition"] == answer["business_condition"]
    assert single_answer["causal_observations"] == answer["causal_observations"]
