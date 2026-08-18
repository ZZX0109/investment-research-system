from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel

from investment_research.domain.trusted_market import (
    IngestionJob,
    MarketSnapshot,
    MarketSnapshotEvent,
    RawDataBatch,
    SecurityMasterRecord,
    SecurityStateRecord,
    VersionedMarketBar,
)
from investment_research.training.pit_join import PITJoinService

T = TypeVar("T", bound=BaseModel)


class TrustedMarketRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add_security(self, item: SecurityMasterRecord) -> SecurityMasterRecord:
        self.connection.execute(
            "INSERT OR REPLACE INTO security_master (id,symbol,exchange,instrument_type,listed_on,delisted_on,payload_json) VALUES (?,?,?,?,?,?,?)",
            (str(item.id), item.symbol, item.exchange, item.instrument_type, item.listed_on.isoformat(), None if item.delisted_on is None else item.delisted_on.isoformat(), item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def security_as_of(self, symbol: str, as_of: datetime) -> tuple[SecurityMasterRecord, SecurityStateRecord | None] | None:
        row = self.connection.execute("SELECT id,payload_json FROM security_master WHERE symbol=?", (symbol,)).fetchone()
        if row is None:
            return None
        security = SecurityMasterRecord.model_validate_json(str(row[1]))
        if security.available_at > as_of:
            return None
        state_rows = self.connection.execute(
            "SELECT payload_json FROM security_state_history WHERE security_id=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>?)",
            (str(security.id), as_of.isoformat(), as_of.isoformat()),
        ).fetchall()
        states = [SecurityStateRecord.model_validate_json(str(item[0])) for item in state_rows]
        state = PITJoinService().latest_visible(
            states,
            as_of,
            effective_field="effective_from",
            available_field="available_at",
            revision_field="id",
        )
        return security, state

    def add_security_state(self, item: SecurityStateRecord) -> SecurityStateRecord:
        self.connection.execute(
            "INSERT INTO security_state_history (id,security_id,effective_from,effective_to,payload_json) VALUES (?,?,?,?,?)",
            (str(item.id), str(item.security_id), item.effective_from.isoformat(), None if item.effective_to is None else item.effective_to.isoformat(), item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def eligible_universe(self, as_of: datetime) -> list[SecurityMasterRecord]:
        rows = self.connection.execute(
            "SELECT payload_json FROM security_master WHERE listed_on<=? AND (delisted_on IS NULL OR delisted_on>=?) ORDER BY symbol",
            (as_of.date().isoformat(), as_of.date().isoformat()),
        ).fetchall()
        eligible: list[SecurityMasterRecord] = []
        for row in rows:
            security = SecurityMasterRecord.model_validate_json(str(row[0]))
            resolved = self.security_as_of(security.symbol, as_of)
            state = None if resolved is None else resolved[1]
            if state is None or state.is_tradeable:
                eligible.append(security)
        return eligible

    def add_raw_batch(self, item: RawDataBatch) -> RawDataBatch:
        existing = self.raw_batch_by_request(item.provider, item.request_id)
        if existing is not None:
            if existing.payload_hash != item.payload_hash:
                raise ValueError("Provider request_id was reused with different payload bytes")
            return existing
        self.connection.execute(
            "INSERT INTO raw_data_batches (id,provider,request_id,dataset,fetched_at,available_at,quality_status,data_tier,time_semantics,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(item.id), item.provider, item.request_id, item.dataset, item.fetched_at.isoformat(), item.available_at.isoformat(), item.quality_status, item.data_tier.value, item.time_semantics, item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def raw_batch(self, item_id: str) -> RawDataBatch | None:
        return self._one("SELECT payload_json FROM raw_data_batches WHERE id=?", (item_id,), RawDataBatch)

    def raw_batch_by_request(self, provider: str, request_id: str) -> RawDataBatch | None:
        return self._one(
            "SELECT payload_json FROM raw_data_batches WHERE provider=? AND request_id=?",
            (provider, request_id),
            RawDataBatch,
        )

    def raw_batches_by_payload_hashes(self, payload_hashes: list[str]) -> list[RawDataBatch]:
        """Resolve immutable raw lineage without a provider/request fallback."""
        unique = sorted(set(payload_hashes))
        if not unique:
            return []
        # `payload_json` is retained for SQLite/PostgreSQL cutover parity, so
        # do the immutable hash filter after hydration rather than relying on
        # a database-specific JSON operator.
        rows = self.connection.execute(
            "SELECT payload_json FROM raw_data_batches"
        ).fetchall()
        wanted = set(unique)
        return [
            item
            for row in rows
            if (item := RawDataBatch.model_validate_json(str(row[0]))).payload_hash in wanted
        ]

    def raw_batches(
        self, *, dataset: str | None = None, data_tier: str | None = None,
        symbol: str | None = None,
    ) -> list[RawDataBatch]:
        """List immutable raw batches for replay/rebuild workflows.

        Filtering after model hydration keeps SQLite behavior aligned with the
        JSON catalog representation used by the PostgreSQL cutover path.
        """
        rows = self.connection.execute(
            "SELECT payload_json FROM raw_data_batches ORDER BY fetched_at"
        ).fetchall()
        items = [RawDataBatch.model_validate_json(str(row[0])) for row in rows]
        return [
            item for item in items
            if (dataset is None or item.dataset == dataset)
            and (data_tier is None or item.data_tier.value == data_tier)
            and (symbol is None or item.symbol == symbol)
        ]

    def add_bar(self, item: VersionedMarketBar) -> VersionedMarketBar:
        existing = self.connection.execute(
            "SELECT payload_json FROM versioned_market_bars WHERE symbol=? AND bar_start=? AND interval=? AND provider=? AND adjustment_mode=? AND revision=?",
            (item.symbol, item.bar_start.isoformat(), item.interval, item.provider, item.adjustment_mode, item.revision),
        ).fetchone()
        if existing is not None:
            stored = VersionedMarketBar.model_validate_json(str(existing[0]))
            if stored.normalized_hash != item.normalized_hash:
                raise ValueError("Market bar revision is immutable")
            return stored
        if item.active:
            self.connection.execute(
                "UPDATE versioned_market_bars SET active=? WHERE symbol=? AND bar_start=? AND interval=? AND provider=? AND adjustment_mode=? AND active=?",
                (False, item.symbol, item.bar_start.isoformat(), item.interval, item.provider, item.adjustment_mode, True),
            )
        self.connection.execute(
            "INSERT INTO versioned_market_bars (id,raw_batch_id,symbol,provider,interval,bar_start,trade_date,adjustment_mode,revision,active,available_at,quality_status,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(item.id), str(item.raw_batch_id), item.symbol, item.provider, item.interval, item.bar_start.isoformat(), item.trade_date.isoformat(), item.adjustment_mode, item.revision, item.active, item.available_at.isoformat(), item.quality_status, item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def active_bars(self, symbol: str, interval: str, *, as_of: datetime | None = None) -> list[VersionedMarketBar]:
        sql = "SELECT payload_json FROM versioned_market_bars WHERE symbol=? AND interval=? AND active=?"
        params: tuple[object, ...] = (symbol, interval, True)
        if as_of is not None:
            sql += " AND available_at<=?"
            params = (*params, as_of.isoformat())
        sql += " ORDER BY bar_start"
        return [VersionedMarketBar.model_validate_json(str(row[0])) for row in self.connection.execute(sql, params).fetchall()]

    def add_snapshot(self, item: MarketSnapshotEvent) -> MarketSnapshotEvent:
        self.connection.execute(
            "INSERT INTO market_snapshot_events (id,raw_batch_id,symbol,provider,event_time,available_at,quality_status,payload_json) VALUES (?,?,?,?,?,?,?,?)",
            (str(item.id), None if item.raw_batch_id is None else str(item.raw_batch_id), item.symbol, item.provider, item.event_time.isoformat(), item.available_at.isoformat(), item.quality_status, item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def latest_snapshot(self, symbol: str, *, as_of: datetime | None = None) -> MarketSnapshotEvent | None:
        sql = "SELECT payload_json FROM market_snapshot_events WHERE symbol=?"
        params: tuple[object, ...] = (symbol,)
        if as_of is not None:
            sql += " AND available_at<=?"
            params = (*params, as_of.isoformat())
        sql += " ORDER BY event_time DESC LIMIT 1"
        return self._one(sql, params, MarketSnapshotEvent)

    def add_market_snapshot(self, item: MarketSnapshot) -> MarketSnapshot:
        existing = self.market_snapshot(str(item.id))
        if existing is not None:
            if existing.content_hash != item.content_hash:
                raise ValueError("Market snapshot id is immutable")
            return existing
        self.connection.execute(
            "INSERT INTO market_snapshots (id,symbol,decision_context,trade_date,decision_time,content_hash,quality_status,payload_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(item.id), item.symbol, item.decision_context,
                item.trade_date.isoformat(), item.decision_time.isoformat(),
                item.content_hash, item.quality_status, item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def market_snapshot(self, item_id: str) -> MarketSnapshot | None:
        return self._one(
            "SELECT payload_json FROM market_snapshots WHERE id=?",
            (item_id,),
            MarketSnapshot,
        )

    def _one(self, sql: str, params: tuple[object, ...], model: type[T]) -> T | None:
        row = self.connection.execute(sql, params).fetchone()
        return None if row is None else model.model_validate_json(str(row[0]))


class IngestionJobRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add(self, item: IngestionJob) -> IngestionJob:
        self.connection.execute(
            "INSERT OR REPLACE INTO ingestion_jobs (id,idempotency_key,job_type,state,priority,scheduled_for,next_attempt_at,cancel_requested,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (str(item.id), item.idempotency_key, item.job_type, item.state, item.priority, item.scheduled_for.isoformat(), None if item.next_attempt_at is None else item.next_attempt_at.isoformat(), item.cancel_requested, item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def get(self, item_id: str) -> IngestionJob | None:
        row = self.connection.execute("SELECT payload_json FROM ingestion_jobs WHERE id=?", (item_id,)).fetchone()
        return None if row is None else IngestionJob.model_validate_json(str(row[0]))

    def by_idempotency_key(self, key: str) -> IngestionJob | None:
        row = self.connection.execute("SELECT payload_json FROM ingestion_jobs WHERE idempotency_key=?", (key,)).fetchone()
        return None if row is None else IngestionJob.model_validate_json(str(row[0]))

    def runnable(self, now: datetime, *, limit: int = 20) -> list[IngestionJob]:
        rows = self.connection.execute(
            "SELECT payload_json FROM ingestion_jobs WHERE state IN (?,?) AND scheduled_for<=? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY priority,scheduled_for LIMIT ?",
            ("queued", "retrying", now.isoformat(), now.isoformat(), limit),
        ).fetchall()
        return [IngestionJob.model_validate_json(str(row[0])) for row in rows]

    def list_recent(self, *, limit: int = 100) -> list[IngestionJob]:
        rows = self.connection.execute("SELECT payload_json FROM ingestion_jobs ORDER BY scheduled_for DESC LIMIT ?", (limit,)).fetchall()
        return [IngestionJob.model_validate_json(str(row[0])) for row in rows]
