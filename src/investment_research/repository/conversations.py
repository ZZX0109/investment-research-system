"""SQLite repository for conversation sessions + messages (Phase 3)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from investment_research.domain.base import utc_now
from investment_research.domain.conversation import (
    ConversationMessage,
    ConversationSession,
)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


class ConversationRepository:
    """Persistence for multi-turn conversation memory."""

    def __init__(self, connection) -> None:
        self.connection = connection

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def add_session(self, session: ConversationSession) -> ConversationSession:
        self.connection.execute(
            """
            INSERT INTO conversations (id, user_id, asset_id, as_of, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(session.id),
                str(session.user_id),
                str(session.asset_id),
                _iso(session.as_of),
                session.title,
                _iso(session.created_at),
                _iso(session.updated_at),
            ),
        )
        self.connection.commit()
        return session

    def get_session(self, session_id: str, *, owner_user_id: UUID | None = None) -> ConversationSession | None:
        if owner_user_id is not None:
            row = self.connection.execute(
                "SELECT id, user_id, asset_id, as_of, title, created_at, updated_at FROM conversations WHERE id=? AND user_id=?",
                (session_id, str(owner_user_id)),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT id, user_id, asset_id, as_of, title, created_at, updated_at FROM conversations WHERE id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._session_from_row(row)

    def list_sessions_for_user(self, user_id: str | UUID) -> list[ConversationSession]:
        rows = self.connection.execute(
            "SELECT id, user_id, asset_id, as_of, title, created_at, updated_at FROM conversations WHERE user_id=? ORDER BY created_at DESC",
            (str(user_id),),
        ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def touch(self, session_id: str) -> None:
        self.connection.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?",
            (_iso(utc_now()), session_id),
        )
        self.connection.commit()

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    def add_message(self, message: ConversationMessage) -> ConversationMessage:
        if message.sequence == 0:
            existing = self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM conversation_messages WHERE session_id=?",
                (str(message.session_id),),
            ).fetchone()
            message = message.model_copy(update={"sequence": int(existing[0]) + 1})
        self.connection.execute(
            """
            INSERT INTO conversation_messages (id, session_id, sequence, role, content, agent_run_id, snapshot_as_of, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(message.id),
                str(message.session_id),
                message.sequence,
                message.role,
                message.content,
                None if message.agent_run_id is None else str(message.agent_run_id),
                message.snapshot_as_of,
                _iso(message.created_at),
            ),
        )
        self.connection.commit()
        self.touch(str(message.session_id))
        return message

    def list_messages(self, session_id: str) -> list[ConversationMessage]:
        rows = self.connection.execute(
            "SELECT id, session_id, sequence, role, content, agent_run_id, snapshot_as_of, created_at FROM conversation_messages WHERE session_id=? ORDER BY sequence",
            (session_id,),
        ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def get_message(self, message_id: str) -> ConversationMessage | None:
        row = self.connection.execute(
            "SELECT id, session_id, sequence, role, content, agent_run_id, snapshot_as_of, created_at FROM conversation_messages WHERE id=?",
            (message_id,),
        ).fetchone()
        return None if row is None else self._message_from_row(row)

    # ------------------------------------------------------------------
    # Row mappers
    # ------------------------------------------------------------------
    def _session_from_row(self, row) -> ConversationSession:
        session = ConversationSession(
            id=UUID(str(row[0])),
            user_id=UUID(str(row[1])),
            asset_id=UUID(str(row[2])),
            as_of=_parse_iso(str(row[3])),
            title=None if row[4] is None else str(row[4]),
            created_at=_parse_iso(str(row[5])),
            updated_at=_parse_iso(str(row[6])),
        )
        session.messages = self.list_messages(str(session.id))
        return session

    def _message_from_row(self, row) -> ConversationMessage:
        return ConversationMessage(
            id=UUID(str(row[0])),
            session_id=UUID(str(row[1])),
            sequence=int(row[2]),
            role=str(row[3]),  # type: ignore[arg-type]
            content=str(row[4]),
            agent_run_id=None if row[5] is None else UUID(str(row[5])),
            snapshot_as_of=None if row[6] is None else str(row[6]),
            created_at=_parse_iso(str(row[7])),
        )


__all__ = ["ConversationRepository"]
