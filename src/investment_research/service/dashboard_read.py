"""Phase 4 (A2) — DashboardReadService: thin read-only facade.

The dashboard tiles and the multi-turn AI path both need the same asset-scoped
read bundle (snapshot + the underlying read-only services).  Rather than have
each caller construct an ``AssetSnapshotService`` + the individual services,
this facade exposes one entry point that the API snapshot route, the
conversation route and (A3) ``ConversationAgentService`` all reuse.  It holds
no run state, no abstain gate and performs no writes — read-only by construction.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from investment_research.service.asset_snapshot import AssetSnapshotService

if TYPE_CHECKING:  # avoid import cycles at runtime
    from investment_research.domain.models import User
    from investment_research.repository.sqlite import SQLiteUnitOfWork
    from investment_research.service.asset_snapshot import AssetSnapshot


class DashboardReadService:
    """Read-only asset-scoped aggregation for the dashboard + AI path."""

    def __init__(
        self,
        uow: "SQLiteUnitOfWork",
        *,
        project_root: Path | None = None,
    ) -> None:
        self._uow = uow
        self._snapshot = AssetSnapshotService(uow, project_root=project_root)

    def snapshot(
        self,
        asset_id: str,
        *,
        as_of,
        user: "User",
    ) -> "AssetSnapshot":
        """The single-source snapshot pinned to ``as_of`` — what the dashboard
        tiles render and what the conversation path feeds to ``_build_plain_answer``
        so the AI answer and the dashboard cannot drift."""
        return self._snapshot.snapshot(asset_id, as_of=as_of, user=user)
