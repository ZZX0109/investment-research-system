from __future__ import annotations

import sqlite3

from investment_research.domain.models import (
    AnalysisRun,
    Asset,
    AuditRecord,
    Evidence,
    Position,
    PriceSeries,
    ResearchReport,
    Watchlist,
)
from investment_research.repository.sqlite_base import SQLiteRepositoryMixin


class SQLiteAssetRepository(SQLiteRepositoryMixin):
    table_name = "assets"
    model_cls = Asset

    def add(self, asset: Asset) -> Asset:
        values = self._serialize_entity(asset)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO assets (
                id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        self.connection.commit()
        return asset

    def list(self, *, source_type: str | None = None) -> list[Asset]:
        if source_type is None:
            rows = self.connection.execute("SELECT payload FROM assets ORDER BY observed_at DESC").fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload FROM assets WHERE source_type = ? ORDER BY observed_at DESC",
                (source_type,),
            ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]

    def get(self, asset_id: str) -> Asset | None:
        row = self.connection.execute(
            "SELECT payload FROM assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        return None if row is None else self._deserialize_entity(self._payload_from_row(row))


class SQLiteEvidenceRepository(SQLiteRepositoryMixin):
    table_name = "evidence"
    model_cls = Evidence

    def add(self, evidence: Evidence) -> Evidence:
        values = self._serialize_entity(evidence)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO evidence (
                id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload, asset_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*values, str(evidence.asset_id)),
        )
        self.connection.commit()
        return evidence

    def list_for_asset(self, asset_id: str) -> list[Evidence]:
        rows = self.connection.execute(
            "SELECT payload FROM evidence WHERE asset_id = ? ORDER BY observed_at DESC",
            (asset_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteWatchlistRepository(SQLiteRepositoryMixin):
    table_name = "watchlists"
    model_cls = Watchlist

    def add(self, watchlist: Watchlist) -> Watchlist:
        values = self._serialize_entity(watchlist)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO watchlists (
                id, user_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(watchlist.user_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return watchlist

    def list_for_user(self, user_id: str) -> list[Watchlist]:
        rows = self.connection.execute(
            "SELECT payload FROM watchlists WHERE user_id = ? ORDER BY observed_at DESC",
            (user_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLitePriceSeriesRepository(SQLiteRepositoryMixin):
    table_name = "price_series"
    model_cls = PriceSeries

    def add(self, series: PriceSeries) -> PriceSeries:
        values = self._serialize_entity(series)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO price_series (
                id, asset_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(series.asset_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return series

    def list_for_asset(self, asset_id: str) -> list[PriceSeries]:
        rows = self.connection.execute(
            "SELECT payload FROM price_series WHERE asset_id = ? ORDER BY observed_at DESC",
            (asset_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteAnalysisRunRepository(SQLiteRepositoryMixin):
    table_name = "analysis_runs"
    model_cls = AnalysisRun

    def add(self, run: AnalysisRun) -> AnalysisRun:
        values = self._serialize_entity(run)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO analysis_runs (
                id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload, asset_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*values, str(run.asset_id)),
        )
        self.connection.commit()
        return run

    def get(self, run_id: str) -> AnalysisRun | None:
        row = self.connection.execute(
            "SELECT payload FROM analysis_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return None if row is None else self._deserialize_entity(self._payload_from_row(row))

    def list_for_asset(self, asset_id: str) -> list[AnalysisRun]:
        rows = self.connection.execute(
            "SELECT payload FROM analysis_runs WHERE asset_id = ? ORDER BY observed_at DESC",
            (asset_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLitePositionRepository(SQLiteRepositoryMixin):
    table_name = "positions"
    model_cls = Position

    def add(self, position: Position) -> Position:
        values = self._serialize_entity(position)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO positions (
                id, user_id, asset_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(position.user_id),
                str(position.asset_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return position

    def list_for_user(self, user_id: str) -> list[Position]:
        rows = self.connection.execute(
            "SELECT payload FROM positions WHERE user_id = ? ORDER BY observed_at DESC",
            (user_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteAuditRecordRepository(SQLiteRepositoryMixin):
    table_name = "audit_records"
    model_cls = AuditRecord

    def add(self, record: AuditRecord) -> AuditRecord:
        values = self._serialize_entity(record)
        self.connection.execute(
            """
            INSERT INTO audit_records (
                id, actor, action, target_type, target_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                record.actor,
                record.action,
                record.target_type,
                str(record.target_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return record

    def list_for_actor(self, actor: str) -> list[AuditRecord]:
        rows = self.connection.execute(
            "SELECT payload FROM audit_records WHERE actor = ? ORDER BY observed_at DESC",
            (actor,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]


class SQLiteResearchReportRepository(SQLiteRepositoryMixin):
    table_name = "research_reports"
    model_cls = ResearchReport

    def add(self, report: ResearchReport) -> ResearchReport:
        values = self._serialize_entity(report)
        self.connection.execute(
            """
            INSERT OR REPLACE INTO research_reports (
                id, asset_id, analysis_run_id, status, schema_version, entity_version, data_mode, source_type, observed_at, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values[0],
                str(report.asset_id),
                str(report.analysis_run_id),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
            ),
        )
        self.connection.commit()
        return report

    def list_for_asset(self, asset_id: str) -> list[ResearchReport]:
        rows = self.connection.execute(
            "SELECT payload FROM research_reports WHERE asset_id = ? ORDER BY observed_at DESC",
            (asset_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]

    def list_for_run(self, run_id: str) -> list[ResearchReport]:
        rows = self.connection.execute(
            "SELECT payload FROM research_reports WHERE analysis_run_id = ? ORDER BY observed_at DESC",
            (run_id,),
        ).fetchall()
        return [self._deserialize_entity(self._payload_from_row(row)) for row in rows]
