"""Phase 6 — tool-progress SSE stream (process visibility).

The left-side AI panel needs to show "正在检索知识库…" / "读模型中…" /
"合并证据" while a run executes.  ``runtime.add_event`` already emits those
events; ``GET /api/v1/agent-runs/{run_id}/events`` is the SSE channel that
streams them.  This test pins the contract: the stream is ``text/event-stream``,
frames are well-formed (``id`` / ``event`` / ``data``), events arrive in
``sequence`` order with their payload intact, and an unknown / foreign run
yields 404 (no cross-user leak).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from investment_research.agent.models import AgentRun
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType
from investment_research.domain.models import Asset, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.api.agent_routes import router as agent_router  # noqa: F401  (import side-effects)

AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _provenance(at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="competition-demo",
        observed_at=at,
    )


def _parse_sse(body: str) -> list[dict]:
    """Parse an SSE body into a list of {id, event, data} frames."""
    frames = []
    for chunk in body.split("\n\n"):
        if not chunk.strip():
            continue
        frame: dict = {"id": None, "event": None, "data": None}
        for line in chunk.splitlines():
            if line.startswith("id:"):
                frame["id"] = line[len("id:"):].strip()
            elif line.startswith("event:"):
                frame["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                frame["data"] = line[len("data:"):]
        frames.append(frame)
    return frames


def test_agent_events_stream_is_ordered_sse(tmp_path: Path) -> None:
    from investment_research.main import app
    from test_api_routes import configure_authenticated_client

    client = configure_authenticated_client(tmp_path, "sse.db")
    try:
        # The same DB the dependency override hands the route.
        uow = SQLiteUnitOfWork(tmp_path / "sse.db")
        auth_user = uow.users.get_by_email("investor@example.com")
        assert auth_user is not None
        user = auth_user.user
        now = datetime.now(timezone.utc)
        asset = Asset(
            ticker="600519", name="示例白酒", asset_type=AssetType.EQUITY,
            provenance=_provenance(now),
        )
        uow.assets.add(asset)
        uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)

        run = AgentRun(
            owner_user_id=user.id,
            asset_id=asset.id,
            task_text="经营变化",
            as_of=AS_OF,
            correlation_id="sse-test",
        )
        uow.agent_runtime.add_run(run)
        # Simulate the progress events the runtime emits during execution.
        seeded = [
            ("run.created", None, {"correlation_id": run.correlation_id}),
            ("tool.started", "knowledge_retrieval", {"query": "经营变化"}),
            ("tool.completed", "knowledge_retrieval", {"hits": 3}),
            ("llm.research_explanation", "report_generation", {"status": "research_only"}),
            ("run.completed", None, {"result": "research_explanation"}),
        ]
        for event_type, node, payload in seeded:
            uow.agent_runtime.add_event(run.id, event_type, node_name=node, payload=payload)

        response = client.get(f"/api/v1/agent-runs/{run.id}/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"

        frames = _parse_sse(response.text)
        assert len(frames) == len(seeded)
        for index, (event_type, _node, payload) in enumerate(seeded):
            frame = frames[index]
            assert frame["event"] == event_type
            assert frame["id"] == str(index + 1)  # sequence is 1-based
            assert json.loads(frame["data"])["event_type"] == event_type
            assert json.loads(frame["data"])["payload"] == payload

        # Unknown run -> 404 (no cross-user / no-data leak).
        missing = client.get("/api/v1/agent-runs/does-not-exist/events")
        assert missing.status_code == 404

        # A run owned by a DIFFERENT user is also 404 (ownership-scoped).
        other = User(
            email="other@example.com", display_name="Other", auth_subject="user:other",
            provenance=_provenance(now),
        )
        uow.users.add(other, password_hash="test")
        foreign = AgentRun(
            owner_user_id=other.id, asset_id=asset.id, task_text="x", as_of=AS_OF,
        )
        uow.agent_runtime.add_run(foreign)
        foreign_resp = client.get(f"/api/v1/agent-runs/{foreign.id}/events")
        assert foreign_resp.status_code == 404
        uow.close()
    finally:
        app.dependency_overrides.clear()
