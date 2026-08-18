"""Phase 4 (A3) — ConversationAgentService: the multi-turn AI path.

Split out of the route (and, structurally, out of the ``AgentOrchestrator``
god-class) so the conversation flow — append question → build the shared
snapshot → run the agent bound to the conversation + snapshot → persist the
assistant answer — lives in one place the dashboard route, the AI panel and
future lightweight-turn optimizations can all target.

The single-turn run path is untouched: it still goes through
``AgentOrchestrator.create_and_execute`` without a ``conversation_id`` /
``snapshot``.  Here we only orchestrate the multi-turn + snapshot-pinned path,
reusing the orchestrator's run execution (abstain gate, tool loop, compliance,
``_build_plain_answer``) so behaviour stays identical to the in-line route.

NOTE — the tool-skip is delivered for the KB-hitting asset-scoped tools
(``get_financial_line_items`` + ``get_long_term_fact_cards``): their values are
carried by the snapshot in the tool's own shaped format, so the override
results are byte-identical and the abstain gate (which reads only the
long-term scorecard/readings/trust/balance tools) is unaffected.  The four
long-term abstain-gate tools are intentionally left to run: they are cheap
derivations off the already-loaded scorecard, and overriding them would require
reconstructing ``long_term_response`` (``data_trust`` / ``evidence_balance`` are
not carried by the snapshot) — a higher-risk snapshot-schema enrichment with
little perf payoff.  This is the safe, high-value slice of the tool-skip.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from investment_research.domain.conversation import ConversationMessage

if TYPE_CHECKING:  # avoid runtime import cycles
    from investment_research.agent.models import AgentRun
    from investment_research.agent.service import AgentOrchestrator
    from investment_research.domain.models import User
    from investment_research.repository.sqlite import SQLiteUnitOfWork
    from investment_research.service.dashboard_read import DashboardReadService


class ConversationAgentService:
    """Multi-turn AI path: snapshot-pinned, conversation-bound runs."""

    def __init__(
        self,
        uow: "SQLiteUnitOfWork",
        *,
        dashboard: "DashboardReadService",
        orchestrator: "AgentOrchestrator",
    ) -> None:
        self._uow = uow
        self._dashboard = dashboard
        self._orchestrator = orchestrator

    def answer(
        self,
        *,
        session_id: str,
        content: str,
        provider_profile_id: str | None,
        user_preference: str,
        user: "User",
    ) -> tuple["AgentRun", object]:
        """Append the user question, run the snapshot-pinned agent turn, persist
        the assistant answer, and return ``(run, refreshed_session)``.

        Raises ``LookupError`` when the session does not exist / is not owned by
        ``user`` (the route maps this to 404).
        """
        session = self._uow.conversations.get_session(session_id, owner_user_id=user.id)
        if session is None:
            raise LookupError("Conversation not found")

        # 1) persist the user's question first, so the run loads it (plus all
        #    prior turns) into context["prior_turns"].
        self._uow.conversations.add_message(
            ConversationMessage(session_id=session.id, role="user", content=content)
        )

        # 2) build the dashboard's single-source snapshot pinned to the session's
        #    as_of and feed it to the run so the AI answer uses the snapshot's
        #    asset-scoped values verbatim — the AI and the dashboard cannot drift,
        #    and the answer stays pinned to the session as_of across turns.
        snapshot = self._dashboard.snapshot(
            str(session.asset_id), as_of=session.as_of, user=user,
        )
        # Phase 4 (A3) tool-skip: short-circuit the KB-hitting asset-scoped tools
        # (financial line items + long-term fact cards) whose values the snapshot
        # already carries, so the multi-turn turn stops re-running them. The
        # snapshot stores these in the tool's own shaped format, so the override
        # results are byte-identical to what the tool would return — the abstain
        # gate (which reads only the long-term scorecard/readings/trust/balance
        # tools, left to run) and _build_plain_answer (which reads from the
        # snapshot) are unaffected.  Lighter turn, no drift.
        tool_overrides = self._snapshot_tool_overrides(snapshot)
        run = self._orchestrator.create_and_execute(
            user=user,
            asset_id=str(session.asset_id),
            task_text=content,
            as_of=session.as_of,
            provider_profile_id=provider_profile_id,
            user_preference=user_preference,
            conversation_id=str(session.id),
            snapshot=snapshot,
            tool_overrides=tool_overrides,
        )

        # 3) persist the assistant answer (the run's plain-answer narrative text)
        #    with the snapshot as_of the turn was pinned to.
        explanation = self._run_explanation_text(str(run.id))
        self._uow.conversations.add_message(
            ConversationMessage(
                session_id=session.id,
                role="assistant",
                content=explanation,
                agent_run_id=run.id,
                snapshot_as_of=session.as_of.isoformat(),
            )
        )
        refreshed = self._uow.conversations.get_session(str(session.id), owner_user_id=user.id)
        return run, refreshed

    @staticmethod
    def _snapshot_tool_overrides(snapshot: object) -> dict[str, dict[str, object]]:
        """Build tool_overrides for the KB-hitting asset-scoped tools whose
        values the snapshot already carries (shaped in the tool's own format).
        The long-term abstain-gate tools (scorecard / readings / data_trust /
        evidence_balance) are intentionally NOT overridden — they are cheap
        derivations off the already-loaded scorecard and overriding them would
        require reconstructing ``long_term_response`` (data_trust /
        evidence_balance are not carried by the snapshot).  Skipping only the
        KB-hitting tools is the safe, high-value slice of the tool-skip.
        """
        symbol = getattr(snapshot.asset, "symbol", None)
        line_items = list(getattr(snapshot, "line_items", []) or [])
        fact_cards = list(getattr(snapshot, "fact_cards", []) or [])
        return {
            "get_financial_line_items": {
                "ok": True,
                "symbol": symbol,
                "count": len(line_items),
                "line_items": line_items,
                "coverage_status": getattr(snapshot, "line_item_coverage_status", "unknown"),
                "coverage_reasons": list(getattr(snapshot, "line_item_coverage_reasons", []) or []),
                "note": "snapshot-pinned: structured financial figures from the shared snapshot.",
            },
            "get_long_term_fact_cards": {
                "ok": True,
                "coverage_status": getattr(snapshot, "fact_card_coverage_status", "unknown"),
                "absence_is_evidence": bool(getattr(snapshot, "fact_card_absence_is_evidence", False)),
                "coverage_reasons": list(getattr(snapshot, "fact_card_coverage_reasons", []) or []),
                "fact_cards": fact_cards,
            },
        }

    def _run_explanation_text(self, run_id: str) -> str:
        """Best-effort extract of the run's plain-answer narrative text."""
        payload: dict[str, object] = {}
        for event in reversed(self._orchestrator.runtime.list_events(run_id)):
            if event.event_type == "llm.research_explanation":
                payload = dict(event.payload)
                break
        if not payload:
            return "（本轮研究未生成可引用解释，请等待下一次工具执行或披露更新。）"
        narrative = payload.get("narrative") if isinstance(payload.get("narrative"), dict) else {}
        summary = narrative.get("summary") or payload.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        plain = payload.get("plain_answer")
        if isinstance(plain, dict):
            business = plain.get("business_condition")
            if isinstance(business, str) and business.strip():
                return business.strip()
        return "（本轮研究未生成可引用解释，请等待下一次工具执行或披露更新。）"
