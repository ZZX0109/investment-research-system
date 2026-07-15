from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from investment_research.domain.pit import (
    CorporateActionRevision,
    HistoricalUniverseMembership,
    ModelApprovalEvidence,
    PITDatasetManifest,
    PITDatasetPartition,
    StandardEventRevision,
    TradingCostSchedule,
)

T = TypeVar("T", bound=BaseModel)


class PITCatalogRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add_partition(self, item: PITDatasetPartition) -> PITDatasetPartition:
        existing = self.partition_by_payload_hash(item.payload_hash)
        if existing is not None:
            if (
                existing.schema_hash != item.schema_hash
                or existing.row_count != item.row_count
                or existing.dataset != item.dataset
            ):
                raise ValueError("PIT partition payload hash was reused with different metadata")
            return existing
        self.connection.execute(
            "INSERT INTO pit_dataset_partitions (id,market,dataset,schema_version,trade_year,object_ref,payload_hash,schema_hash,row_count,quality_status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(item.id),
                item.market,
                item.dataset,
                item.schema_version,
                item.trade_year,
                item.object_ref,
                item.payload_hash,
                item.schema_hash,
                item.row_count,
                item.quality_status,
                item.created_at.isoformat(),
            ),
        )
        self.connection.commit()
        return item

    def partition_by_payload_hash(self, payload_hash: str) -> PITDatasetPartition | None:
        row = self.connection.execute(
            "SELECT id,market,dataset,schema_version,trade_year,object_ref,payload_hash,"
            "schema_hash,row_count,quality_status,created_at FROM pit_dataset_partitions WHERE payload_hash=?",
            (payload_hash,),
        ).fetchone()
        return None if row is None else PITDatasetPartition(
            id=row[0], market=row[1], dataset=row[2], schema_version=row[3], trade_year=row[4],
            object_ref=row[5], payload_hash=row[6], schema_hash=row[7], row_count=row[8],
            quality_status=row[9], created_at=row[10],
        )

    def add_event_revision(self, item: StandardEventRevision) -> StandardEventRevision:
        self.connection.execute(
            "INSERT INTO standard_event_revisions (id,logical_event_id,revision,market,symbol,available_at,active,payload_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(item.id),
                item.logical_event_id,
                item.revision,
                item.market,
                item.symbol,
                item.available_at.isoformat(),
                item.active,
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def events_as_of(self, symbol: str, as_of: datetime) -> list[StandardEventRevision]:
        rows = self.connection.execute(
            "SELECT payload_json FROM standard_event_revisions WHERE symbol=? AND available_at<=? ORDER BY logical_event_id,revision",
            (symbol, as_of.isoformat()),
        ).fetchall()
        latest: dict[str, StandardEventRevision] = {}
        for row in rows:
            item = StandardEventRevision.model_validate_json(str(row[0]))
            latest[item.logical_event_id] = item
        return sorted(
            latest.values(), key=lambda item: (item.available_at, item.logical_event_id)
        )

    def add_universe_membership(
        self, item: HistoricalUniverseMembership
    ) -> HistoricalUniverseMembership:
        self._insert_payload(
            "historical_universe_memberships",
            item,
            (
                "market",
                "symbol",
                "effective_from",
                "effective_to",
                "available_at",
                "revision",
            ),
            (
                item.market,
                item.symbol,
                item.effective_from.isoformat(),
                None if item.effective_to is None else item.effective_to.isoformat(),
                item.available_at.isoformat(),
                item.revision,
            ),
        )
        return item

    def universe_as_of(
        self, market: str, as_of: datetime
    ) -> list[HistoricalUniverseMembership]:
        rows = self.connection.execute(
            "SELECT payload_json FROM historical_universe_memberships WHERE market=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>?) AND available_at<=? ORDER BY symbol,revision",
            (market, as_of.isoformat(), as_of.isoformat(), as_of.isoformat()),
        ).fetchall()
        latest: dict[str, HistoricalUniverseMembership] = {}
        for row in rows:
            item = HistoricalUniverseMembership.model_validate_json(str(row[0]))
            latest[item.symbol] = item
        return sorted(latest.values(), key=lambda item: item.symbol)

    def add_corporate_action(
        self, item: CorporateActionRevision
    ) -> CorporateActionRevision:
        self._insert_payload(
            "corporate_action_revisions",
            item,
            ("market", "symbol", "ex_date", "revision", "available_at"),
            (
                item.market,
                item.symbol,
                item.ex_date.isoformat(),
                item.revision,
                item.available_at.isoformat(),
            ),
        )
        return item

    def add_cost_schedule(self, item: TradingCostSchedule) -> TradingCostSchedule:
        self._insert_payload(
            "trading_cost_schedules",
            item,
            ("market", "effective_from", "effective_to", "version", "verified"),
            (
                item.market,
                item.effective_from.isoformat(),
                None if item.effective_to is None else item.effective_to.isoformat(),
                item.version,
                item.verified,
            ),
        )
        return item

    def add_manifest(self, item: PITDatasetManifest) -> PITDatasetManifest:
        self._insert_payload(
            "pit_dataset_manifests",
            item,
            (
                "training_run_id",
                "market",
                "decision_context",
                "task",
                "dataset_hash",
                "quality_status",
            ),
            (
                item.training_run_id,
                item.market,
                item.decision_context,
                item.task,
                item.dataset_hash,
                item.quality_status,
            ),
        )
        return item

    def partitions(
        self,
        *,
        market: str,
        dataset: str | None = None,
        schema_version: str | None = None,
        trade_year: int | None = None,
    ) -> list[PITDatasetPartition]:
        clauses = ["market=?"]
        params: list[object] = [market]
        for column, value in (
            ("dataset", dataset),
            ("schema_version", schema_version),
            ("trade_year", trade_year),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        rows = self.connection.execute(
            "SELECT id,market,dataset,schema_version,trade_year,object_ref,payload_hash,"
            "schema_hash,row_count,quality_status,created_at FROM pit_dataset_partitions "
            f"WHERE {' AND '.join(clauses)} ORDER BY trade_year,created_at,id",
            tuple(params),
        ).fetchall()
        return [
            PITDatasetPartition(
                id=row[0], market=row[1], dataset=row[2], schema_version=row[3],
                trade_year=row[4], object_ref=row[5], payload_hash=row[6],
                schema_hash=row[7], row_count=row[8], quality_status=row[9], created_at=row[10],
            )
            for row in rows
        ]

    def manifest(
        self,
        *,
        training_run_id: str,
        market: str,
        decision_context: str,
        task: str,
    ) -> PITDatasetManifest | None:
        row = self.connection.execute(
            "SELECT payload_json FROM pit_dataset_manifests "
            "WHERE training_run_id=? AND market=? AND decision_context=? AND task=?",
            (training_run_id, market, decision_context, task),
        ).fetchone()
        return None if row is None else PITDatasetManifest.model_validate_json(str(row[0]))

    def manifests(
        self,
        *,
        training_run_id: str | None = None,
        market: str | None = None,
        decision_context: str | None = None,
        task: str | None = None,
    ) -> list[PITDatasetManifest]:
        clauses: list[str] = []
        params: list[object] = []
        for column, value in (
            ("training_run_id", training_run_id), ("market", market),
            ("decision_context", decision_context), ("task", task),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        sql = "SELECT payload_json FROM pit_dataset_manifests"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY training_run_id,market,decision_context,task"
        return [
            PITDatasetManifest.model_validate_json(str(row[0]))
            for row in self.connection.execute(sql, tuple(params)).fetchall()
        ]

    def add_approval_evidence(
        self, item: ModelApprovalEvidence
    ) -> ModelApprovalEvidence:
        existing = self.connection.execute(
            "SELECT id,training_run_id,market,decision_context,task,evidence_type,artifact_ref,artifact_hash,created_at "
            "FROM model_approval_evidence WHERE training_run_id=? AND market=? "
            "AND decision_context=? AND task=? AND evidence_type=?",
            (
                item.training_run_id, item.market, item.decision_context,
                item.task, item.evidence_type,
            ),
        ).fetchone()
        if existing is not None:
            stored = ModelApprovalEvidence(
                id=existing[0], training_run_id=existing[1], market=existing[2],
                decision_context=existing[3], task=existing[4], evidence_type=existing[5],
                artifact_ref=existing[6], artifact_hash=existing[7], created_at=existing[8],
            )
            if (
                stored.artifact_hash != item.artifact_hash
                or stored.artifact_ref != item.artifact_ref
            ):
                raise ValueError("approval evidence is immutable for scope and type")
            return stored
        self.connection.execute(
            "INSERT INTO model_approval_evidence (id,training_run_id,market,decision_context,task,evidence_type,artifact_ref,artifact_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(item.id),
                item.training_run_id,
                item.market,
                item.decision_context,
                item.task,
                item.evidence_type,
                item.artifact_ref,
                item.artifact_hash,
                item.created_at.isoformat(),
            ),
        )
        self.connection.commit()
        return item

    def approval_evidence(
        self, training_run_id: str, market: str, context: str, task: str
    ) -> list[ModelApprovalEvidence]:
        rows = self.connection.execute(
            "SELECT id,training_run_id,market,decision_context,task,evidence_type,artifact_ref,artifact_hash,created_at FROM model_approval_evidence WHERE training_run_id=? AND market=? AND decision_context=? AND task=? ORDER BY created_at",
            (training_run_id, market, context, task),
        ).fetchall()
        return [
            ModelApprovalEvidence(
                id=row[0],
                training_run_id=row[1],
                market=row[2],
                decision_context=row[3],
                task=row[4],
                evidence_type=row[5],
                artifact_ref=row[6],
                artifact_hash=row[7],
                created_at=row[8],
            )
            for row in rows
        ]

    def _insert_payload(
        self,
        table: str,
        item: BaseModel,
        columns: tuple[str, ...],
        values: tuple[object, ...],
    ) -> None:
        names = ("id", *columns, "payload_json")
        placeholders = ",".join("?" for _ in names)
        self.connection.execute(
            f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})",
            (str(getattr(item, "id")), *values, item.model_dump_json()),
        )
        self.connection.commit()
