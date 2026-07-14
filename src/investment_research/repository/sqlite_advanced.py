from __future__ import annotations

import sqlite3

from investment_research.domain.models import (
    DocumentArtifact,
    HistoricalScenario,
    PaperObservation,
    PortfolioRiskSnapshot,
    RefreshRun,
    ReportSchedule,
    ResearchAudit,
)


def _payload(row) -> str:
    return str(row[0])


class SQLiteRefreshRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: RefreshRun) -> RefreshRun:
        self.connection.execute(
            "INSERT OR REPLACE INTO refresh_runs (id,asset_id,user_id,observed_at,payload) VALUES (?,?,?,?,?)",
            (
                str(item.id),
                str(item.asset_id),
                item.triggered_by,
                item.provenance.observed_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def get(self, item_id: str) -> RefreshRun | None:
        row = self.connection.execute(
            "SELECT payload FROM refresh_runs WHERE id=?", (item_id,)
        ).fetchone()
        return None if row is None else RefreshRun.model_validate_json(_payload(row))

    def list_for_asset(self, asset_id: str) -> list[RefreshRun]:
        rows = self.connection.execute(
            "SELECT payload FROM refresh_runs WHERE asset_id=? ORDER BY observed_at DESC",
            (asset_id,),
        ).fetchall()
        return [RefreshRun.model_validate_json(_payload(r)) for r in rows]


class SQLiteHistoricalScenarioRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: HistoricalScenario) -> HistoricalScenario:
        self.connection.execute(
            "INSERT OR REPLACE INTO historical_scenarios (id,asset_id,analysis_run_id,observed_at,payload) VALUES (?,?,?,?,?)",
            (
                str(item.id),
                str(item.asset_id),
                None if item.analysis_run_id is None else str(item.analysis_run_id),
                item.provenance.observed_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def list_for_asset(
        self, asset_id: str, *, limit: int = 20
    ) -> list[HistoricalScenario]:
        rows = self.connection.execute(
            "SELECT payload FROM historical_scenarios WHERE asset_id=? ORDER BY observed_at DESC LIMIT ?",
            (asset_id, limit),
        ).fetchall()
        return [HistoricalScenario.model_validate_json(_payload(r)) for r in rows]


class SQLitePortfolioRiskRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: PortfolioRiskSnapshot) -> PortfolioRiskSnapshot:
        self.connection.execute(
            "INSERT OR REPLACE INTO portfolio_risk_snapshots (id,user_id,observed_at,payload) VALUES (?,?,?,?)",
            (
                str(item.id),
                str(item.user_id),
                item.provenance.observed_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def latest_for_user(self, user_id: str) -> PortfolioRiskSnapshot | None:
        row = self.connection.execute(
            "SELECT payload FROM portfolio_risk_snapshots WHERE user_id=? ORDER BY observed_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return (
            None
            if row is None
            else PortfolioRiskSnapshot.model_validate_json(_payload(row))
        )


class SQLiteReportScheduleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: ReportSchedule) -> ReportSchedule:
        self.connection.execute(
            "INSERT OR REPLACE INTO report_schedules (id,user_id,asset_id,observed_at,payload) VALUES (?,?,?,?,?)",
            (
                str(item.id),
                str(item.user_id),
                None if item.asset_id is None else str(item.asset_id),
                item.provenance.observed_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def get(self, item_id: str) -> ReportSchedule | None:
        row = self.connection.execute(
            "SELECT payload FROM report_schedules WHERE id=?", (item_id,)
        ).fetchone()
        return (
            None if row is None else ReportSchedule.model_validate_json(_payload(row))
        )

    def list_for_user(self, user_id: str) -> list[ReportSchedule]:
        rows = self.connection.execute(
            "SELECT payload FROM report_schedules WHERE user_id=? ORDER BY observed_at DESC",
            (user_id,),
        ).fetchall()
        return [ReportSchedule.model_validate_json(_payload(r)) for r in rows]

    def delete(self, item_id: str) -> None:
        self.connection.execute("DELETE FROM report_schedules WHERE id=?", (item_id,))
        self.connection.commit()

    def list_due(self, as_of: str) -> list[ReportSchedule]:
        rows = self.connection.execute(
            "SELECT payload FROM report_schedules ORDER BY observed_at"
        ).fetchall()
        items = [ReportSchedule.model_validate_json(_payload(r)) for r in rows]
        return [
            item
            for item in items
            if item.enabled
            and item.frequency not in {"manual", "event_triggered"}
            and item.next_run_at is not None
            and item.next_run_at.isoformat() <= as_of
        ]

    def list_active(self) -> list[ReportSchedule]:
        rows = self.connection.execute(
            "SELECT payload FROM report_schedules ORDER BY observed_at"
        ).fetchall()
        return [
            item
            for item in (ReportSchedule.model_validate_json(_payload(r)) for r in rows)
            if item.enabled
        ]


class SQLiteDocumentArtifactRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: DocumentArtifact) -> DocumentArtifact:
        self.connection.execute(
            "INSERT OR REPLACE INTO document_artifacts (id,user_id,asset_id,observed_at,payload) VALUES (?,?,?,?,?)",
            (
                str(item.id),
                str(item.user_id),
                None if item.asset_id is None else str(item.asset_id),
                item.provenance.observed_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def get(self, item_id: str) -> DocumentArtifact | None:
        row = self.connection.execute(
            "SELECT payload FROM document_artifacts WHERE id=?", (item_id,)
        ).fetchone()
        return (
            None if row is None else DocumentArtifact.model_validate_json(_payload(row))
        )

    def list_for_user(self, user_id: str) -> list[DocumentArtifact]:
        rows = self.connection.execute(
            "SELECT payload FROM document_artifacts WHERE user_id=? ORDER BY observed_at DESC",
            (user_id,),
        ).fetchall()
        return [DocumentArtifact.model_validate_json(_payload(r)) for r in rows]


class SQLiteResearchAuditRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: ResearchAudit) -> ResearchAudit:
        self.connection.execute(
            "INSERT OR REPLACE INTO research_audits (id,analysis_run_id,observed_at,payload) VALUES (?,?,?,?)",
            (
                str(item.id),
                str(item.analysis_run_id),
                item.provenance.observed_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def get_for_run(self, run_id: str) -> ResearchAudit | None:
        row = self.connection.execute(
            "SELECT payload FROM research_audits WHERE analysis_run_id=? ORDER BY observed_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return None if row is None else ResearchAudit.model_validate_json(_payload(row))


class SQLitePaperObservationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, item: PaperObservation) -> PaperObservation:
        self.connection.execute(
            "INSERT OR REPLACE INTO paper_observations (id,asset_id,analysis_run_id,observed_at,payload) VALUES (?,?,?,?,?)",
            (
                str(item.id),
                str(item.asset_id),
                str(item.analysis_run_id),
                item.evaluation_due_at.isoformat(),
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def list_due(self, as_of: str) -> list[PaperObservation]:
        rows = self.connection.execute(
            "SELECT payload FROM paper_observations WHERE observed_at<=?", (as_of,)
        ).fetchall()
        return [PaperObservation.model_validate_json(_payload(r)) for r in rows]

    def list_for_asset(self, asset_id: str) -> list[PaperObservation]:
        rows = self.connection.execute(
            "SELECT payload FROM paper_observations WHERE asset_id=? ORDER BY observed_at DESC", (asset_id,)
        ).fetchall()
        return [PaperObservation.model_validate_json(_payload(r)) for r in rows]

    def list_pending(self) -> list[PaperObservation]:
        rows = self.connection.execute("SELECT payload FROM paper_observations").fetchall()
        return [item for item in (PaperObservation.model_validate_json(_payload(row)) for row in rows) if item.state == "pending"]

    def pending_asset_ids(self) -> set[str]:
        return {str(item.asset_id) for item in self.list_pending()}

    def list_all(self) -> list[PaperObservation]:
        rows = self.connection.execute("SELECT payload FROM paper_observations ORDER BY observed_at DESC").fetchall()
        return [PaperObservation.model_validate_json(_payload(row)) for row in rows]
