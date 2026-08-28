"""§5 ``web_search(query)`` function tool regression tests.

The LLM-callable general web search that lets the assistant fill a perceived
knowledge boundary with its OWN query + rationale, distinct from
``search_latest_news`` (asset-scoped, auto-query, news-only).  These tests pin
the handler contract: argument-bearing (the only such public tool), query
required, sourced results recorded into ``function_calls`` for evidence_merge.
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
from investment_research.agent.web_search import DuckDuckGoLiteSearchProvider
from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork

AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _build(uow: SQLiteUnitOfWork):
    now = datetime.now(timezone.utc)
    user = User(
        email="ws@e.com",
        display_name="WS",
        auth_subject="user:ws",
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="d",
            observed_at=now,
        ),
    )
    uow.users.add(user, password_hash="t")
    orchestrator = AgentOrchestrator(uow)
    # _record_tool writes to the DB (run FK); stub it so the test isolates the
    # handler logic without persisting a full run.
    orchestrator._record_tool = lambda *a, **k: None  # type: ignore[assignment]
    run = AgentRun(
        owner_user_id=user.id,
        asset_id=UUID(int=1),
        task_text="x",
        as_of=AS_OF,
        state=AgentRunState.RUNNING,
    )
    context: dict = {"function_calls": []}
    return orchestrator, run, user, context


def test_web_search_is_registered_public_and_takes_arguments() -> None:
    tool = next((t for t in FUNCTION_CALL_TOOLS if t.name == "web_search"), None)
    assert tool is not None, "web_search must be a registered function tool"
    assert "web_search" in PUBLIC_FUNCTION_CALL_TOOL_NAMES
    props = tool.parameters.get("properties", {})
    assert "query" in props and "rationale" in props
    assert "query" in tool.parameters.get("required", [])


def test_web_search_returns_sourced_results_for_llm_query(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "ws.db")
    orchestrator, run, user, context = _build(uow)
    result = orchestrator._execute_function_call(
        run,
        user,
        context,
        "web_search",
        {
            "query": "境外机构投资者持股比例限制 2026",
            "rationale": "knowledge base 未覆盖该规则",
        },
    )
    assert result["ok"] is True
    assert isinstance(result.get("results"), list)
    assert result["query"] == "境外机构投资者持股比例限制 2026"
    assert result["rationale"] == "knowledge base 未覆盖该规则"
    # recorded into function_calls so evidence_merge / answer builder can cite it
    assert any(c.get("name") == "web_search" for c in context["function_calls"])


def test_web_search_requires_non_empty_query(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "ws2.db")
    orchestrator, run, user, context = _build(uow)
    result = orchestrator._execute_function_call(
        run, user, context, "web_search", {"query": "   "}
    )
    assert result["ok"] is False
    assert result["error"] == "query_required"


def test_web_search_bypasses_zero_arguments_guard(tmp_path: Path) -> None:
    """web_search is the only public tool that may carry arguments; every other
    zero-arg tool still gets rejected when the LLM passes stray arguments."""
    uow = SQLiteUnitOfWork(tmp_path / "ws3.db")
    orchestrator, run, user, context = _build(uow)
    result = orchestrator._execute_function_call(
        run, user, context, "get_price_trend", {"bogus": "args"}
    )
    assert result["ok"] is False
    assert result["error"] == "arguments_not_permitted"


def test_public_web_search_parses_original_url_date_and_snippet(monkeypatch) -> None:
    page = b"""
    <a rel='nofollow' href='//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Freport&amp;rut=x' class='result-link'>
      Example Bank 2026 interim report
    </a>
    <td class='result-snippet'>2026-08-14 revenue increased &amp; profit improved.</td>
    """

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return page

    monkeypatch.setattr("investment_research.agent.web_search.urlopen", lambda *args, **kwargs: Response())
    results = DuckDuckGoLiteSearchProvider().search("Example Bank latest report", limit=3)

    assert len(results) == 1
    assert results[0].url == "https://example.com/report"
    assert results[0].source == "example.com"
    assert results[0].published_at == "2026-08-14"
    assert "revenue increased" in results[0].snippet
    assert results[0].citation_id and results[0].citation_id.startswith("web:")
    assert results[0].mode == "http"
