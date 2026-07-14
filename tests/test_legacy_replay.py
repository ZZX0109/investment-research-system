from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from uuid import uuid4

from investment_research.domain.base import Provenance, utc_now
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork


def _load_replay_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "replay_legacy_backend.py"
    spec = importlib.util.spec_from_file_location("legacy_replay", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _owner() -> User:
    return User(
        email="replay-owner@example.com",
        display_name="Replay owner",
        auth_subject=f"user:{uuid4()}",
        provenance=Provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.REAL,
            source_name="test",
            observed_at=utc_now(),
        ),
    )


def _legacy_fixture() -> sqlite3.Connection:
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    source.executescript(
        """
        CREATE TABLE holdings (symbol TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE evidence_records (
            id TEXT PRIMARY KEY, symbol TEXT NOT NULL, source_type TEXT NOT NULL,
            claim TEXT NOT NULL, source_url TEXT, observed_at TEXT NOT NULL, confidence REAL NOT NULL
        );
        CREATE TABLE research_runs (
            run_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, evidence_ids_json TEXT,
            input_snapshot_hash TEXT, model_version TEXT, reasoning_steps_json TEXT,
            started_at TEXT, finished_at TEXT
        );
        CREATE TABLE report_snapshots (
            run_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, markdown TEXT NOT NULL,
            report_version TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """
    )
    now = utc_now().isoformat()
    source.execute("INSERT INTO holdings VALUES (?,?)", ("AAPL", "Apple Inc."))
    source.execute(
        "INSERT INTO evidence_records VALUES (?,?,?,?,?,?,?)",
        ("ev-1", "AAPL", "news_event", "Revenue growth improved", "https://www.sec.gov/example", now, 0.8),
    )
    source.execute(
        "INSERT INTO research_runs VALUES (?,?,?,?,?,?,?,?)",
        ("run-1", "AAPL", '["ev-1"]', "a" * 64, "legacy-v1", "[]", now, now),
    )
    source.execute(
        "INSERT INTO report_snapshots VALUES (?,?,?,?,?)",
        ("run-1", "AAPL", "# Legacy report", "v1", now),
    )
    source.commit()
    return source


def test_legacy_replay_is_idempotent_with_stable_mappings(tmp_path) -> None:
    module = _load_replay_module()
    source = _legacy_fixture()
    target = SQLiteUnitOfWork(tmp_path / "target.db")
    owner = _owner()
    target.users.add(owner, password_hash="x")
    try:
        first = module.Replay(source=source, target=target, owner=owner).run()
        second = module.Replay(source=source, target=target, owner=owner).run()

        assert first == {"assets": 1, "evidence": 1, "claims": 1, "runs": 1, "reports": 1, "skipped": 0, "failures": 0}
        assert second["assets"] == 0
        assert second["evidence"] == 0
        assert second["runs"] == 0
        assert second["reports"] == 0
        assert second["failures"] == 0
        assert target.connection.execute("SELECT COUNT(*) FROM legacy_replay_mappings").fetchone()[0] == 5
        assert target.connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
        assert target.connection.execute("SELECT COUNT(*) FROM research_runs_v2").fetchone()[0] == 1
    finally:
        source.close()
        target.close()
