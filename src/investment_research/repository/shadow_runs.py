from __future__ import annotations

from investment_research.domain.pit import ShadowRunOutcome, ShadowRunSession


class ShadowRunRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add(self, item: ShadowRunSession) -> ShadowRunSession:
        existing = self.get_scope_day(
            training_run_id=item.training_run_id,
            market=item.market,
            decision_context=item.decision_context,
            task=item.task,
            trade_date=item.trade_date.isoformat(),
        )
        if existing is not None:
            if existing.model_dump(mode="json") != item.model_dump(mode="json"):
                raise ValueError("shadow session scope/day is immutable")
            return existing
        self.connection.execute(
            "INSERT INTO shadow_run_sessions "
            "(id,training_run_id,market,decision_context,task,trade_date,valid,payload_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                str(item.id), item.training_run_id, item.market, item.decision_context,
                item.task, item.trade_date.isoformat(), item.valid, item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def get_scope_day(self, *, training_run_id: str, market: str, decision_context: str, task: str, trade_date: str) -> ShadowRunSession | None:
        row = self.connection.execute(
            "SELECT payload_json FROM shadow_run_sessions WHERE training_run_id=? AND market=? "
            "AND decision_context=? AND task=? AND trade_date=?",
            (training_run_id, market, decision_context, task, trade_date),
        ).fetchone()
        return None if row is None else ShadowRunSession.model_validate_json(str(row[0]))

    def list_scope(self, *, training_run_id: str, market: str, decision_context: str, task: str) -> list[ShadowRunSession]:
        rows = self.connection.execute(
            "SELECT payload_json FROM shadow_run_sessions WHERE training_run_id=? AND market=? "
            "AND decision_context=? AND task=? ORDER BY trade_date",
            (training_run_id, market, decision_context, task),
        ).fetchall()
        return [ShadowRunSession.model_validate_json(str(row[0])) for row in rows]


class ShadowRunOutcomeRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add(self, item: ShadowRunOutcome) -> ShadowRunOutcome:
        row = self.connection.execute(
            "SELECT payload_json FROM shadow_run_outcomes WHERE shadow_session_id=? AND horizon_sessions=?",
            (str(item.shadow_session_id), item.horizon_sessions),
        ).fetchone()
        if row is not None:
            existing = ShadowRunOutcome.model_validate_json(str(row[0]))
            if existing.model_dump(mode="json") != item.model_dump(mode="json"):
                raise ValueError("shadow outcome is immutable for session/horizon")
            return existing
        self.connection.execute(
            "INSERT INTO shadow_run_outcomes (id,shadow_session_id,horizon_sessions,payload_json) VALUES (?,?,?,?)",
            (str(item.id), str(item.shadow_session_id), item.horizon_sessions, item.model_dump_json()),
        )
        self.connection.commit()
        return item
