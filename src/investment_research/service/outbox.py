"""Idempotent local outbox processing for durable domain side effects."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from investment_research.repository.sqlite import SQLiteUnitOfWork


class OutboxService:
    """Marks committed domain events as delivered after deterministic handling.

    External transports can replace ``_handle`` later. Keeping the state change
    here makes retries and duplicate delivery visible without coupling writes to
    the request transaction.
    """

    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def drain(self, *, limit: int = 100) -> dict[str, int]:
        rows = self.uow.connection.execute(
            "SELECT id,event_type,payload_json,attempts FROM outbox_events "
            "WHERE state=? ORDER BY occurred_at LIMIT ?",
            ("pending", limit),
        ).fetchall()
        delivered = 0
        failed = 0
        for row in rows:
            event_id = str(row[0])
            try:
                self._handle(event_type=str(row[1]), payload=json.loads(str(row[2])))
                self.uow.connection.execute(
                    "UPDATE outbox_events SET state=?, attempts=?, processed_at=? WHERE id=? AND state=?",
                    ("delivered", int(row[3]) + 1, datetime.now(timezone.utc).isoformat(), event_id, "pending"),
                )
                delivered += 1
            except Exception:
                self.uow.connection.execute(
                    "UPDATE outbox_events SET state=?, attempts=? WHERE id=? AND state=?",
                    ("failed", int(row[3]) + 1, event_id, "pending"),
                )
                failed += 1
        self.uow.connection.commit()
        return {"delivered": delivered, "failed": failed, "pending": len(rows) - delivered - failed}

    def _handle(self, *, event_type: str, payload: dict[str, Any]) -> None:
        # Domain writes are already committed. The initial consumer validates
        # envelope integrity and leaves external publishing to dedicated workers.
        if not event_type or not isinstance(payload, dict):
            raise ValueError("Invalid outbox event envelope")
