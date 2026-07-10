from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.analysis_run_service import (
    analysis_run_by_id,
    create_analysis_run,
    get_report_snapshot,
    previous_run_delta,
    recent_analysis_runs,
    stable_snapshot_hash,
    store_report_snapshot,
)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_create_analysis_run_records_snapshot_and_structured_payload(app, test_db_path):
    fixed_now = datetime(2026, 7, 7, 9, 30, 0, tzinfo=timezone.utc)
    connect = make_connect(test_db_path)
    snapshot = {"evidence": [{"id": 2}], "holding": {"symbol": "NVDA"}}

    run = create_analysis_run(
        "NVDA",
        "balanced",
        42.5,
        "research summary",
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        input_snapshot=snapshot,
        model_version="risk-model-v1",
        evidence_ids=[2, 3],
        reasoning_steps=[{"role": "Research Agent", "status": "done"}],
        judge_payload={"qualityGate": {"status": "WARN"}},
        risk_conclusion={"riskScore": 42.5, "gateStatus": "WARN"},
        source_meta={
            "mode": "real",
            "provider": "research_pipeline",
            "as_of": "2026-07-07T09:30:00Z",
            "overrides": [],
            "synthetic_ratio": 0.0,
        },
    )

    assert run["runId"].startswith("NVDA-balanced-20260707093000")
    assert run["inputSnapshotHash"] == stable_snapshot_hash(snapshot)
    assert run["inputSnapshot"] == snapshot
    assert run["modelVersion"] == "risk-model-v1"
    assert run["evidenceIds"] == [2, 3]
    assert run["judge"]["qualityGate"]["status"] == "WARN"
    assert run["sourceMeta"]["provider"] == "research_pipeline"

    recent = recent_analysis_runs("NVDA", connect=connect)
    assert recent[0]["runId"] == run["runId"]
    assert recent[0]["qualityGateStatus"] == "WARN"

    loaded = analysis_run_by_id(connect=connect, run_id=run["runId"])
    assert loaded is not None
    assert loaded["inputSnapshot"] == snapshot
    assert loaded["inputSnapshotHash"] == stable_snapshot_hash(snapshot)

    delta = previous_run_delta("NVDA", 50.0, connect=connect)
    assert delta["hasPrevious"] is True
    assert delta["previousRunId"] == run["runId"]
    assert delta["riskScoreDelta"] == 7.5


def test_report_snapshot_is_bound_to_run(app, test_db_path):
    fixed_now = datetime(2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)
    connect = make_connect(test_db_path)

    store_report_snapshot(
        connect=connect,
        now_utc=lambda: fixed_now,
        iso=iso,
        run_id="NVDA-balanced-run",
        symbol="NVDA",
        preference="balanced",
        report_version="report-1",
        markdown="# NVDA\n\nRun ID: NVDA-balanced-run",
    )

    snapshot = get_report_snapshot(connect=connect, run_id="NVDA-balanced-run")
    assert snapshot is not None
    assert snapshot["run_id"] == "NVDA-balanced-run"
    assert snapshot["markdown"].startswith("# NVDA")
    assert get_report_snapshot(connect=connect, run_id="missing-run") is None
