from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import UUID

from investment_research.auth.models import AuthenticatedUser, RefreshSession
from investment_research.domain.models import User
from investment_research.repository.sqlite_base import SQLiteRepositoryMixin


class SQLiteUserRepository(SQLiteRepositoryMixin):
    table_name = "users"
    model_cls = User

    def add(self, user: User, *, password_hash: str) -> None:
        values = self._serialize_entity(user)
        self.connection.execute(
            """
            INSERT INTO users (
                id, email, status, schema_version, entity_version, data_mode, source_type, observed_at, password_hash, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                user.email,
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                password_hash,
                values[7],
            ),
        )
        self.connection.commit()

    def get_by_email(self, email: str) -> AuthenticatedUser | None:
        row = self.connection.execute(
            "SELECT payload, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        return None if row is None else AuthenticatedUser(
            user=self._deserialize_entity(str(row[0])),
            password_hash=str(row[1]),
        )

    def get_by_id(self, user_id: str) -> AuthenticatedUser | None:
        row = self.connection.execute(
            "SELECT payload, password_hash FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return None if row is None else AuthenticatedUser(
            user=self._deserialize_entity(str(row[0])),
            password_hash=str(row[1]),
        )


class SQLiteRefreshSessionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, session: RefreshSession) -> None:
        self.connection.execute(
            """
            INSERT INTO refresh_sessions (id, user_id, token_id, expires_at, created_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(session.id),
                str(session.user_id),
                session.token_id,
                session.expires_at.isoformat(),
                session.created_at.isoformat(),
                None if session.revoked_at is None else session.revoked_at.isoformat(),
            ),
        )
        self.connection.commit()

    def get_active(self, token_id: str) -> RefreshSession | None:
        row = self.connection.execute(
            """
            SELECT id, user_id, token_id, expires_at, created_at, revoked_at
            FROM refresh_sessions
            WHERE token_id = ? AND revoked_at IS NULL
            """,
            (token_id,),
        ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(str(row[3]))
        if expires_at <= datetime.now(timezone.utc):
            return None
        return RefreshSession(
            id=UUID(str(row[0])),
            user_id=UUID(str(row[1])),
            token_id=str(row[2]),
            expires_at=expires_at,
            created_at=datetime.fromisoformat(str(row[4])),
            revoked_at=None if row[5] is None else datetime.fromisoformat(str(row[5])),
        )

    def revoke(self, token_id: str, *, revoked_at: datetime) -> None:
        self.connection.execute(
            "UPDATE refresh_sessions SET revoked_at = ? WHERE token_id = ?",
            (revoked_at.isoformat(), token_id),
        )
        self.connection.commit()
