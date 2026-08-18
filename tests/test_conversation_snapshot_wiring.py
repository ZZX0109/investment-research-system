"""Phase 4 (slice 1) — the conversation path consumes the dashboard snapshot.

Guards the承重 fix for "AI 看不到仪表盘刚算出的同一份快照": when a user
posts a message to a conversation, the route builds the dashboard's
single-source ``AssetSnapshot`` pinned to the session's ``as_of`` and feeds it
to the run, so the AI answer uses the snapshot's asset-scoped values verbatim
(price / scorecard / readings / fact cards / line items / causal chain) and
cannot drift from the dashboard across turns.

This is a fast, hermetic wiring test: the orchestrator's
``create_and_execute`` is replaced with a recorder so we assert the route
builds + passes the right snapshot without running the full agent (whose
behavior is already guarded by ``test_asset_snapshot`` for the snapshot
consumption and ``test_conversation_demo_flow`` for the run).
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from investment_research.agent.models import AgentRun, AgentRunState
from investment_research.agent.service import AgentOrchestrator
from investment_research.api.agent_routes import get_agent_service
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import PricePoint, PriceSeries
from investment_research.main import app
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.asset_snapshot import AssetSnapshot

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _provenance(at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="competition-demo",
        observed_at=at,
    )


def _load_seeder(project_root: Path):
    scripts_dir = str(project_root / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


class _RecordingOrchestrator(AgentOrchestrator):
    """Real orchestrator whose create_and_execute records the snapshot kwarg
    instead of running the full agent (keeps the wiring test fast + hermetic)."""

    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        super().__init__(uow)
        self.recorded_snapshot: AssetSnapshot | None = None
        self.recorded_conversation_id: str | None = None

    def create_and_execute(  # type: ignore[override]
        self, *, user, asset_id, task_text, as_of,
        provider_profile_id=None, user_preference="conservative",
        conversation_id=None, snapshot=None, tool_overrides=None,
    ) -> AgentRun:
        self.recorded_snapshot = snapshot
        self.recorded_conversation_id = conversation_id
        return AgentRun(
            owner_user_id=user.id,
            asset_id=UUID(asset_id),
            task_text=task_text,
            as_of=as_of,
            state=AgentRunState.COMPLETED,
            correlation_id="snapshot-wiring-test",
        )


def test_conversation_message_feeds_pinned_snapshot_to_run(tmp_path: Path) -> None:
    from test_api_routes import configure_authenticated_client

    client = configure_authenticated_client(tmp_path, "conv-snapshot.db")
    recorder = _RecordingOrchestrator(SQLiteUnitOfWork(tmp_path / "conv-snapshot.db"))
    app.dependency_overrides[get_agent_service] = lambda: recorder
    try:
        # 1) create the asset via the API (owned by the authed user).
        created = client.post(
            "/api/v1/assets",
            json={
                "ticker": "600519", "name": "示例白酒", "asset_type": AssetType.EQUITY.value,
                "currency": "cny", "exchange": "XSHG",
                "data_mode": DataMode.REAL.value, "source_type": DataSourceType.REAL.value,
                "source_name": "competition-demo", "observed_at": AS_OF.isoformat(), "confidence": 0.97,
            },
        )
        assert created.status_code == 201
        asset_id = created.json()["id"]

        # 2) seed the same DB the route uses: price series (25 points) + KB.
        uow = SQLiteUnitOfWork(tmp_path / "conv-snapshot.db")
        now = datetime.now(timezone.utc)
        points = [
            PricePoint(
                asset_id=UUID(asset_id), timestamp=AS_OF - timedelta(days=24 - i),
                open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i,
                volume=1000.0, provenance=_provenance(now),
            ) for i in range(25)
        ]
        uow.price_series.add(
            PriceSeries(asset_id=UUID(asset_id), interval="1d", points=points, provenance=_provenance(now))
        )
        _load_seeder(REPO_ROOT)._run_seed_into(uow)

        # 3) open a conversation pinned to AS_OF + post a message.
        conv = client.post(
            "/api/v1/conversations",
            json={"asset_id": asset_id, "as_of": AS_OF.isoformat(), "title": "经营变化"},
        )
        assert conv.status_code == 201
        session_id = conv.json()["id"]

        msg = client.post(
            f"/api/v1/conversations/{session_id}/messages",
            json={"content": "经营变化与盈利拐点"},
        )
        assert msg.status_code == 201

        # 4) the route built the dashboard snapshot + passed it to the run,
        #    pinned to the session's as_of — so the AI answer and the dashboard
        #    share one source of truth (no drift across turns).
        assert recorder.recorded_conversation_id == session_id
        snapshot = recorder.recorded_snapshot
        assert isinstance(snapshot, AssetSnapshot)
        assert snapshot.asset.symbol == "600519"
        assert snapshot.as_of == AS_OF
        assert snapshot.market_observation.latest_close == 124.0  # last seeded close
        assert snapshot.market_observation.sessions == 25
        assert snapshot.long_term_status == "available"  # demo scorecard for 600519
        assert snapshot.fact_cards  # KB seeded
        assert snapshot.line_items  # KB seeded
        # The conversation now has the user question + an assistant answer.
        auth_user = uow.users.get_by_email("investor@example.com")
        refreshed = uow.conversations.get_session(session_id, owner_user_id=auth_user.user.id)
        assert refreshed is not None
        assert [m.role for m in refreshed.messages] == ["user", "assistant"]
        uow.close()
    finally:
        app.dependency_overrides.clear()
