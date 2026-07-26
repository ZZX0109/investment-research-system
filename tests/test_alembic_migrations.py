import os
import sqlite3
import json
import hashlib
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


@pytest.mark.parametrize(
    "starting_revision",
    ["0013_pit_data_catalog", "0014_shadow_run_sessions", "0015_shadow_run_outcomes"],
)
def test_upgrade_from_recent_catalog_revisions(starting_revision: str, tmp_path: Path) -> None:
    database_path = tmp_path / f"upgrade-{starting_revision}.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, starting_revision)
    command.upgrade(config, "head")
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "0017_financial_knowledge",
    )
    assert connection.execute("SELECT COUNT(*) FROM financial_knowledge_documents").fetchone()[0] >= 4
    connection.close()


def test_alembic_upgrade_head_builds_fresh_sqlite_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "alembic-fresh.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    previous = os.environ.get("INVESTMENT_RESEARCH_DATABASE_URL")
    os.environ["INVESTMENT_RESEARCH_DATABASE_URL"] = f"sqlite:///{database_path}"

    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("INVESTMENT_RESEARCH_DATABASE_URL", None)
        else:
            os.environ["INVESTMENT_RESEARCH_DATABASE_URL"] = previous

    connection = sqlite3.connect(database_path)
    tables = {
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    connection.close()

    assert version == ("0017_financial_knowledge",)
    assert {
        "pit_dataset_partitions",
        "standard_event_revisions",
        "historical_universe_memberships",
        "corporate_action_revisions",
        "trading_cost_schedules",
        "pit_dataset_manifests",
        "model_approval_evidence",
        "shadow_run_sessions",
        "shadow_run_outcomes",
        "financial_knowledge_documents",
    } <= tables
    assert {"market_snapshots", "provider_coverage_runs", "model_artifact_sets"} <= tables
    assert {
        "refresh_runs",
        "historical_scenarios",
        "portfolio_risk_snapshots",
        "report_schedules",
        "document_artifacts",
        "research_audits",
        "paper_observations",
        "resource_owners",
        "resource_shares",
        "knowledge_sources",
        "source_documents",
        "source_revisions",
        "knowledge_evidence",
        "claims",
        "research_runs_v2",
        "model_versions",
        "quality_gate_policies",
        "outbox_events",
        "agent_runs",
        "agent_node_executions",
        "agent_tool_calls",
        "llm_provider_profiles",
        "llm_calls",
        "paper_predictions_v2",
        "document_gold_annotations",
        "document_evaluations",
        "market_quotes",
        "market_quote_attempts",
        "observation_revisions",
        "directional_forecasts",
        "security_master",
        "security_state_history",
        "raw_data_batches",
        "versioned_market_bars",
        "market_snapshot_events",
        "ingestion_jobs",
        "research_forecast_bundles",
    }.issubset(tables)
    assert {
        "assets",
        "analysis_runs",
        "users",
        "positions",
        "watchlists",
        "price_series",
        "research_reports",
        "analysis_snapshots",
        "judge_scores",
    }.issubset(tables)


def test_trusted_migration_backfills_real_cn_legacy_rows_without_synthetic(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0010_market_observation")
    connection = sqlite3.connect(database_path)
    observed = "2026-07-14T07:00:00+00:00"
    asset = {"ticker": "600519.SH", "name": "Kweichow Moutai", "asset_type": "equity", "currency": "CNY"}
    connection.execute("INSERT INTO assets VALUES (?,?,?,?,?,?,?,?)", ("asset-1", "active", "1", 1, "real", "real", observed, json.dumps(asset)))
    point = {"timestamp": observed, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000}
    series = {"interval": "1d", "series_role": "asset", "points": [point], "provenance": {"source_name": "legacy-real"}}
    connection.execute("INSERT INTO price_series VALUES (?,?,?,?,?,?,?,?,?)", ("series-1", "asset-1", "active", "1", 1, "real", "real", observed, json.dumps(series)))
    connection.execute("INSERT INTO market_quotes VALUES (?,?,?,?,?,?,?,?,?)", ("quote-1", "asset-1", "legacy-quote", observed, observed, 101, 100, hashlib.sha256(b"quote").hexdigest(), "{}"))
    connection.commit()
    connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM security_master").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM raw_data_batches").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM versioned_market_bars").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM market_snapshot_events").fetchone()[0] == 1
    assert connection.execute("SELECT quality_status FROM versioned_market_bars").fetchone()[0] == "degraded"
    connection.close()


def test_legacy_free_batches_are_downgraded_to_research_pit(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-free.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0015_shadow_run_outcomes")
    connection = sqlite3.connect(database_path)
    payload = {
        "provider": "akshare", "request_id": "free-akshare-daily-1",
        "dataset": "daily_bars_raw", "payload_ref": "file-object://raw.json",
        "payload_hash": "a" * 64, "schema_version": "v1", "symbol": "600519",
        "fetched_at": "2026-07-14T08:00:00+00:00",
        "available_at": "2026-07-14T08:00:00+00:00",
        "quality_status": "passed",
    }
    connection.execute(
        "INSERT INTO raw_data_batches (id,provider,request_id,dataset,fetched_at,available_at,quality_status,payload_json) VALUES (?,?,?,?,?,?,?,?)",
        ("free-1", "akshare", "free-akshare-daily-1", "daily_bars_raw",
         "2026-07-14T08:00:00+00:00", "2026-07-14T08:00:00+00:00", "passed", json.dumps(payload)),
    )
    connection.commit()
    connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(database_path)
    row = connection.execute(
        "SELECT data_tier,time_semantics,quality_status,payload_json FROM raw_data_batches WHERE id='free-1'"
    ).fetchone()
    connection.close()
    assert row[:3] == ("research_pit", "legacy_time_semantics", "degraded")
    migrated = json.loads(row[3])
    assert migrated["data_tier"] == "research_pit"
    assert "historical_available_at_unproven_public_backfill" in migrated["quality_issues"]
