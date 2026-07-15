"""Qualify legacy free payloads as research-only data."""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "0016_research_data_qualification"
down_revision = "0015_shadow_run_outcomes"
branch_labels = None
depends_on = None


FREE_PROVIDERS = {
    "akshare", "akshare_cninfo_notices", "baostock", "yfinance", "sec",
    "sec_edgar", "hkex", "hkexnews", "fred", "fred_public_csv", "edinet", "tdnet",
}


def upgrade() -> None:
    op.add_column(
        "raw_data_batches",
        sa.Column("data_tier", sa.String(24), nullable=False, server_default="formal_pit"),
    )
    op.add_column(
        "raw_data_batches",
        sa.Column("time_semantics", sa.String(48), nullable=False, server_default="legacy_time_semantics"),
    )
    bind = op.get_bind()
    metadata = sa.MetaData()
    table = sa.Table("raw_data_batches", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(table.c.id, table.c.provider, table.c.request_id, table.c.payload_json)
    ).mappings()
    for row in rows:
        provider = str(row["provider"]).lower()
        request_id = str(row["request_id"]).lower()
        free = provider in FREE_PROVIDERS or request_id.startswith("free-")
        tier = "research_pit" if free else "formal_pit"
        payload = json.loads(str(row["payload_json"]))
        payload["data_tier"] = tier
        payload["time_semantics"] = "legacy_time_semantics"
        if free:
            payload["quality_status"] = "degraded"
            payload["quality_issues"] = sorted(set([
                *payload.get("quality_issues", []),
                "legacy_time_semantics",
                "historical_available_at_unproven_public_backfill",
            ]))
        values = {
            "data_tier": tier,
            "time_semantics": "legacy_time_semantics",
            "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        }
        if free:
            values["quality_status"] = "degraded"
        bind.execute(table.update().where(table.c.id == row["id"]).values(**values))
    op.create_index("ix_raw_batch_data_tier", "raw_data_batches", ["data_tier", "provider"])


def downgrade() -> None:
    op.drop_index("ix_raw_batch_data_tier", table_name="raw_data_batches")
    op.drop_column("raw_data_batches", "time_semantics")
    op.drop_column("raw_data_batches", "data_tier")
