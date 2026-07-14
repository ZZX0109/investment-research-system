from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from investment_research.domain.models import User


@dataclass(frozen=True)
class AuthenticatedUser:
    user: User
    password_hash: str


@dataclass(frozen=True)
class RefreshSession:
    id: UUID
    user_id: UUID
    token_id: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None
