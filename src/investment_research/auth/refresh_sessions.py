from __future__ import annotations

from investment_research.auth.models import RefreshSession
from investment_research.auth.security import utc_now
from investment_research.repository.contracts import RefreshSessionRepository


class RefreshSessionService:
    """Owns refresh-session lifecycle so token rotation stays outside AuthService."""

    def __init__(self, repository: RefreshSessionRepository) -> None:
        self.repository = repository

    def create(self, session: RefreshSession) -> RefreshSession:
        self.repository.add(session)
        return session

    def get_active(self, token_id: str) -> RefreshSession | None:
        return self.repository.get_active(token_id)

    def revoke(self, token_id: str) -> None:
        self.repository.revoke(token_id, revoked_at=utc_now())
