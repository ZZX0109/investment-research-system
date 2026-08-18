"""Multi-turn conversation memory for the long-term investment AI assistant
(Phase 3).

A ``ConversationSession`` pins one asset + one as_of and accumulates
``ConversationMessage`` turns so the left-side AI panel can support
"展开刚才说的盈利拐点" — the agent reads the session's prior turns and the
prior-turn snapshot when answering the next question.

Design notes:

* Sessions are asset-scoped and as_of-pinned: the dashboard and the AI share
  one ``asset_id`` + ``as_of`` for the whole conversation, so context does not
  get rebuilt per question.
* Each assistant message links to the ``agent_run_id`` that produced it and
  records the ``snapshot_as_of`` the turn was pinned to, so a later phase can
  rebuild the exact snapshot the AI saw (the dashboard↔AI single-source
  guarantee from Phase 2 extends across turns).
* The single-turn ``AgentRun`` path (no ``conversation_id``) stays fully
  backward-compatible; conversations are an opt-in memory layer on top.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from investment_research.domain.base import utc_now

MessageRole = Literal["user", "assistant", "system"]


class ConversationMessage(BaseModel):
    """One turn in a conversation (a user question or an assistant answer)."""

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    sequence: int = 0
    role: MessageRole
    content: str
    agent_run_id: UUID | None = None
    snapshot_as_of: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ConversationSession(BaseModel):
    """An asset-scoped, as_of-pinned multi-turn conversation."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    asset_id: UUID
    as_of: datetime
    title: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    messages: list[ConversationMessage] = Field(default_factory=list)


__all__ = ["ConversationMessage", "ConversationSession", "MessageRole"]
