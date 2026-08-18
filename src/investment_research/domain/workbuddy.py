"""Connector identities for external, read-only research assistants."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from investment_research.domain.base import utc_now


WorkBuddyScope = Literal[
    "research.read",
    "knowledge.read",
    "shadow.read",
    "lifecycle.read",
]


class WorkBuddyConnection(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID
    name: str = Field(min_length=1, max_length=128)
    token_prefix: str
    scopes: list[WorkBuddyScope] = Field(default_factory=lambda: ["research.read", "knowledge.read", "shadow.read", "lifecycle.read"])
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime | None = None


class WorkBuddyConnectionIssued(WorkBuddyConnection):
    """Returned exactly once when a connector key is created or rotated."""

    token: str = Field(min_length=24)
