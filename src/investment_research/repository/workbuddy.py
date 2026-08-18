from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID

from investment_research.domain.workbuddy import WorkBuddyConnection, WorkBuddyConnectionIssued


class WorkBuddyConnectionRepository:
    """Persist only a SHA-256 token verifier; plaintext is shown once."""

    def __init__(self, connection) -> None:
        self.connection = connection

    def issue(self, *, owner_user_id: UUID, name: str, scopes: list[str] | None = None) -> WorkBuddyConnectionIssued:
        raw = f"irwb_{secrets.token_urlsafe(32)}"
        now = datetime.now(timezone.utc)
        connection = WorkBuddyConnection(
            owner_user_id=owner_user_id,
            name=name,
            token_prefix=raw[:12],
            scopes=scopes or ["research.read", "knowledge.read", "shadow.read", "lifecycle.read"],  # type: ignore[arg-type]
            created_at=now,
            updated_at=now,
        )
        self.connection.execute(
            "INSERT INTO workbuddy_connections (id,owner_user_id,name,token_hash,token_prefix,scopes_json,enabled,created_at,updated_at,last_used_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(connection.id), str(connection.owner_user_id), connection.name,
                self._hash(raw), connection.token_prefix, json.dumps(connection.scopes), connection.enabled,
                connection.created_at.isoformat(), connection.updated_at.isoformat(), None,
            ),
        )
        self.connection.commit()
        return WorkBuddyConnectionIssued(**connection.model_dump(), token=raw)

    def list_for_owner(self, owner_user_id: UUID) -> list[WorkBuddyConnection]:
        rows = self.connection.execute(
            "SELECT id,owner_user_id,name,token_prefix,scopes_json,enabled,created_at,updated_at,last_used_at FROM workbuddy_connections WHERE owner_user_id=? ORDER BY created_at DESC",
            (str(owner_user_id),),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def revoke(self, connection_id: str, *, owner_user_id: UUID) -> bool:
        cursor = self.connection.execute(
            "UPDATE workbuddy_connections SET enabled=0,updated_at=? WHERE id=? AND owner_user_id=? AND enabled=1",
            (datetime.now(timezone.utc).isoformat(), connection_id, str(owner_user_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def authenticate(self, token: str) -> WorkBuddyConnection | None:
        row = self.connection.execute(
            "SELECT id,owner_user_id,name,token_prefix,scopes_json,enabled,created_at,updated_at,last_used_at FROM workbuddy_connections WHERE token_hash=? AND enabled=1",
            (self._hash(token),),
        ).fetchone()
        if row is None:
            return None
        value = self._from_row(row)
        now = datetime.now(timezone.utc)
        self.connection.execute("UPDATE workbuddy_connections SET last_used_at=? WHERE id=?", (now.isoformat(), str(value.id)))
        self.connection.commit()
        return value.model_copy(update={"last_used_at": now})

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _from_row(row) -> WorkBuddyConnection:
        return WorkBuddyConnection(
            id=UUID(str(row[0])), owner_user_id=UUID(str(row[1])), name=str(row[2]), token_prefix=str(row[3]),
            scopes=json.loads(str(row[4])), enabled=bool(row[5]), created_at=datetime.fromisoformat(str(row[6])),
            updated_at=datetime.fromisoformat(str(row[7])), last_used_at=None if row[8] is None else datetime.fromisoformat(str(row[8])),
        )
