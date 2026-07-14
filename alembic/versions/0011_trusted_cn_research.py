"""Add trusted A-share data, ingestion jobs and forecast bundles."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "0011_trusted_cn_research"
down_revision = "0010_market_observation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_master",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False, unique=True),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("instrument_type", sa.String(16), nullable=False),
        sa.Column("listed_on", sa.Date, nullable=False),
        sa.Column("delisted_on", sa.Date, nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_table(
        "security_state_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("security_master.id"), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_security_state_effective", "security_state_history", ["security_id", "effective_from"])
    op.create_table(
        "raw_data_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("provider", "request_id", name="uq_raw_batch_provider_request"),
    )
    op.create_index("ix_raw_batch_dataset_time", "raw_data_batches", ["dataset", "fetched_at"])
    op.create_table(
        "versioned_market_bars",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("raw_batch_id", sa.String(36), sa.ForeignKey("raw_data_batches.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("bar_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("adjustment_mode", sa.String(8), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("symbol", "bar_start", "interval", "provider", "adjustment_mode", "revision", name="uq_market_bar_revision"),
    )
    op.create_index("ix_market_bar_active_time", "versioned_market_bars", ["symbol", "interval", "active", "bar_start"])
    op.create_table(
        "market_snapshot_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("raw_batch_id", sa.String(36), sa.ForeignKey("raw_data_batches.id"), nullable=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_snapshot_symbol_time", "market_snapshot_events", ["symbol", "event_time"])
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(256), nullable=False, unique=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_ingestion_jobs_runnable", "ingestion_jobs", ["state", "scheduled_for", "priority"])
    op.create_table(
        "research_forecast_bundles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False, unique=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    _backfill_legacy_records()


def _backfill_legacy_records() -> None:
    bind = op.get_bind()
    assets = bind.execute(sa.text("SELECT id,observed_at,payload FROM assets")).mappings().all()
    symbols: dict[str, str] = {}
    for row in assets:
        try:
            payload = json.loads(str(row["payload"]))
            symbol = str(payload.get("ticker") or "").upper()
            exchange = "XSHG" if symbol.endswith(".SH") else "XSHE" if symbol.endswith(".SZ") else "XBSE" if symbol.endswith(".BJ") else None
            if exchange is None:
                continue
            observed = _aware(str(row["observed_at"]))
            security_id = str(row["id"])
            symbols[security_id] = symbol
            master = {
                "id": security_id, "symbol": symbol, "exchange": exchange,
                "instrument_type": str(payload.get("asset_type") or "equity"),
                "name": str(payload.get("name") or symbol), "listed_on": observed.date().isoformat(),
                "delisted_on": None, "industry": None, "board": None,
                "currency": str(payload.get("currency") or "CNY"), "lot_size": 100,
                "calendar_code": "XSHG", "source_time": observed.isoformat(),
                "ingest_time": observed.isoformat(), "available_at": observed.isoformat(),
            }
            bind.execute(sa.text("INSERT INTO security_master (id,symbol,exchange,instrument_type,listed_on,delisted_on,payload_json) VALUES (:id,:symbol,:exchange,:instrument_type,:listed_on,NULL,:payload)"), {
                "id": security_id, "symbol": symbol, "exchange": exchange,
                "instrument_type": master["instrument_type"], "listed_on": master["listed_on"],
                "payload": json.dumps(master, ensure_ascii=False),
            })
            state_id = str(uuid5(NAMESPACE_URL, f"legacy-security-state:{security_id}"))
            state = {
                "id": state_id, "security_id": security_id, "effective_from": observed.isoformat(),
                "effective_to": None, "is_st": False, "is_suspended": False,
                "is_tradeable": True, "limit_up_rate": 0.10, "limit_down_rate": 0.10,
                "adjustment_policy": "raw", "industry": None, "board": None,
                "source_time": observed.isoformat(), "ingest_time": observed.isoformat(),
                "available_at": observed.isoformat(),
            }
            bind.execute(sa.text("INSERT INTO security_state_history (id,security_id,effective_from,effective_to,payload_json) VALUES (:id,:security_id,:effective_from,NULL,:payload)"), {
                "id": state_id, "security_id": security_id, "effective_from": observed.isoformat(),
                "payload": json.dumps(state, ensure_ascii=False),
            })
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    series_rows = bind.execute(sa.text("SELECT id,asset_id,source_type,observed_at,payload FROM price_series")).mappings().all()
    for row in series_rows:
        try:
            payload = json.loads(str(row["payload"]))
            symbol = symbols.get(str(row["asset_id"]))
            if symbol is None or str(row["source_type"]) != "real" or payload.get("interval") != "1d" or payload.get("series_role", "asset") != "asset":
                continue
            observed = _aware(str(row["observed_at"]))
            raw_payload = str(row["payload"]).encode()
            raw_hash = hashlib.sha256(raw_payload).hexdigest()
            batch_id = str(uuid5(NAMESPACE_URL, f"legacy-raw-batch:{row['id']}"))
            provider = str(payload.get("provenance", {}).get("source_name") or "legacy")
            batch = {
                "id": batch_id, "provider": provider, "request_id": f"legacy:{row['id']}",
                "dataset": "daily_bars", "payload_ref": f"legacy-db://price_series/{row['id']}",
                "payload_hash": raw_hash, "schema_version": "legacy-v1", "symbol": symbol,
                "interval": "1d", "coverage_start": None, "coverage_end": None,
                "market_session": "closed", "fetched_at": observed.isoformat(),
                "source_time": observed.isoformat(), "available_at": observed.isoformat(),
                "quality_status": "degraded", "quality_issues": ["legacy_time_semantics"],
            }
            bind.execute(sa.text("INSERT INTO raw_data_batches (id,provider,request_id,dataset,fetched_at,available_at,quality_status,payload_json) VALUES (:id,:provider,:request_id,'daily_bars',:fetched_at,:available_at,'degraded',:payload)"), {
                "id": batch_id, "provider": provider, "request_id": batch["request_id"],
                "fetched_at": observed.isoformat(), "available_at": observed.isoformat(),
                "payload": json.dumps(batch, ensure_ascii=False),
            })
            for point in payload.get("points", []):
                at = _aware(str(point["timestamp"]))
                bar_id = str(uuid5(NAMESPACE_URL, f"legacy-bar:{row['id']}:{at.isoformat()}"))
                normalized_hash = hashlib.sha256(json.dumps(point, sort_keys=True).encode()).hexdigest()
                bar = {
                    "id": bar_id, "raw_batch_id": batch_id, "symbol": symbol, "provider": provider,
                    "interval": "1d", "bar_start": at.isoformat(), "trade_date": at.date().isoformat(),
                    "adjustment_mode": "raw", "revision": 1, "active": True,
                    "open": point["open"], "high": point["high"], "low": point["low"], "close": point["close"],
                    "volume": point.get("volume"), "amount": None, "turnover_rate": None,
                    "previous_close": None, "limit_up": None, "limit_down": None,
                    "is_suspended": False, "hit_limit_up": False, "hit_limit_down": False,
                    "source_time": at.isoformat(), "ingest_time": observed.isoformat(),
                    "available_at": at.isoformat(), "as_of": at.isoformat(),
                    "quality_status": "degraded", "normalized_hash": normalized_hash,
                }
                bind.execute(sa.text("INSERT INTO versioned_market_bars (id,raw_batch_id,symbol,provider,interval,bar_start,trade_date,adjustment_mode,revision,active,available_at,quality_status,payload_json) VALUES (:id,:batch,:symbol,:provider,'1d',:bar_start,:trade_date,'raw',1,:active,:available_at,'degraded',:payload)"), {
                    "id": bar_id, "batch": batch_id, "symbol": symbol, "provider": provider,
                    "bar_start": at.isoformat(), "trade_date": at.date().isoformat(), "active": True,
                    "available_at": at.isoformat(), "payload": json.dumps(bar, ensure_ascii=False),
                })
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue

    quote_rows = bind.execute(sa.text("SELECT id,asset_id,provider,quote_at,fetched_at,last_price,previous_close,payload_hash FROM market_quotes")).mappings().all()
    for row in quote_rows:
        symbol = symbols.get(str(row["asset_id"]))
        if symbol is None:
            continue
        event_time = _aware(str(row["quote_at"]))
        fetched_at = _aware(str(row["fetched_at"]))
        snapshot = {
            "id": str(row["id"]), "raw_batch_id": None, "symbol": symbol,
            "provider": str(row["provider"]), "event_time": event_time.isoformat(),
            "source_time": event_time.isoformat(), "ingest_time": fetched_at.isoformat(),
            "available_at": fetched_at.isoformat(), "as_of": fetched_at.isoformat(),
            "latest_price": float(row["last_price"]), "previous_close": row["previous_close"],
            "volume": None, "amount": None, "bid_price": None, "ask_price": None,
            "high": None, "low": None, "turnover_rate": None, "is_suspended": False,
            "quality_status": "degraded", "payload_hash": str(row["payload_hash"]),
        }
        bind.execute(sa.text("INSERT INTO market_snapshot_events (id,raw_batch_id,symbol,provider,event_time,available_at,quality_status,payload_json) VALUES (:id,NULL,:symbol,:provider,:event_time,:available_at,'degraded',:payload)"), {
            "id": str(row["id"]), "symbol": symbol, "provider": str(row["provider"]),
            "event_time": event_time.isoformat(), "available_at": fetched_at.isoformat(),
            "payload": json.dumps(snapshot, ensure_ascii=False),
        })


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def downgrade() -> None:
    for table in (
        "research_forecast_bundles", "ingestion_jobs", "market_snapshot_events",
        "versioned_market_bars", "raw_data_batches", "security_state_history", "security_master",
    ):
        op.drop_table(table)
