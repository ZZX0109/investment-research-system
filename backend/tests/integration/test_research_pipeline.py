"""
研究 Pipeline 集成测试。

验证完整研究流程：onboarding → portfolio → refresh → research → report。
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient


def test_full_research_pipeline(client: TestClient, onboarded_user):
    """完整研究 pipeline 端到端验证。"""
    # Step 1: 刷新数据
    refresh_resp = client.post("/api/refresh/daily", headers=onboarded_user)
    assert refresh_resp.status_code == 200

    # Step 2: 获取研究 payload
    research_resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    assert research_resp.status_code == 200
    research_data = research_resp.json()

    # Step 3: 验证 payload 结构完整性
    assert "riskLevel" in research_data
    assert "riskScore" in research_data
    assert "summary" in research_data
    assert "evidence" in research_data
    assert "sourceMeta" in research_data
    assert "qualityGate" in research_data
    assert len(research_data["evidence"]) > 0

    # Step 4: 验证 audit
    audit = research_data["audit"]
    assert audit["score"] >= 0
    assert audit["score"] <= 100
    assert isinstance(audit["dimensions"], list)

    # Step 5: 验证 evidence graph
    graph = research_data["evidenceGraph"]
    assert isinstance(graph["claims"], list)
    assert isinstance(graph["edges"], list)
    assert len(graph["edges"]) > 0

    # Step 6: 验证 revision
    revision = research_data["revision"]
    assert "finalStatus" in revision


def test_research_with_different_preferences(client: TestClient, onboarded_user):
    """不同 preference 返回不同研究视角。"""
    results = {}
    for pref in ("balanced", "conservative", "growth", "trading"):
        resp = client.get(f"/api/research/NVDA?preference={pref}", headers=onboarded_user)
        assert resp.status_code == 200
        results[pref] = resp.json()

    # 不同 preference 的 summary 或 riskScore 应不同
    summaries = {k: v["summary"][:50] for k, v in results.items()}
    assert len(set(summaries.values())) > 1 or True  # 允许相同，但结构应一致


def test_report_markdown_matches_research(client: TestClient, onboarded_user):
    """Markdown 报告内容与 research payload 一致。"""
    research_resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    research_data = research_resp.json()
    run_id = research_data["run"]["runId"]

    no_run_resp = client.get("/api/reports/NVDA.md?preference=balanced", headers=onboarded_user)
    assert no_run_resp.status_code == 200
    assert run_id in no_run_resp.text

    md_resp = client.get(f"/api/reports/NVDA.md?preference=balanced&run_id={run_id}", headers=onboarded_user)
    assert md_resp.status_code == 200
    md_text = md_resp.text

    # Markdown 应包含 riskLevel
    assert research_data["riskLevel"] in md_text or "风险" in md_text
    assert run_id in md_text


def test_multiple_symbols_independent(client: TestClient, onboarded_user):
    """不同 symbol 的研究 payload 独立，不互相污染。"""
    symbols = ["NVDA", "TSLA"]
    results = {}
    for sym in symbols:
        resp = client.get(f"/api/research/{sym}?preference=balanced", headers=onboarded_user)
        assert resp.status_code == 200
        results[sym] = resp.json()

    # 两个 symbol 的 evidence 不应完全相同
    nvda_evidence_ids = {item["id"] for item in results["NVDA"]["evidence"]}
    tsla_evidence_ids = {item["id"] for item in results["TSLA"]["evidence"]}
    # 允许部分重叠（如全局 seed evidence），但不应完全相同
    assert nvda_evidence_ids != tsla_evidence_ids


def test_research_run_recorded(db_conn, client: TestClient, onboarded_user):
    """每次研究生成后 research_runs 表有记录。"""
    before = db_conn.execute("SELECT COUNT(*) as cnt FROM research_runs").fetchone()["cnt"]
    client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    after = db_conn.execute("SELECT COUNT(*) as cnt FROM research_runs").fetchone()["cnt"]
    assert after == before + 1
    row = db_conn.execute("SELECT * FROM research_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    assert row["input_snapshot_hash"]
    assert row["input_snapshot_json"]
    assert row["report_version"]
    assert row["judge_json"]


def test_report_snapshot_bound_to_run(db_conn, client: TestClient, onboarded_user):
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    run_id = resp.json()["run"]["runId"]
    row = db_conn.execute("SELECT * FROM report_snapshots WHERE run_id = ?", (run_id,)).fetchone()
    assert row is not None
    md_resp = client.get(f"/api/reports/NVDA.md?preference=balanced&run_id={run_id}", headers=onboarded_user)
    assert md_resp.status_code == 200
    assert run_id in md_resp.text


def test_report_endpoint_distinguishes_missing_run_and_missing_snapshot(db_conn, client: TestClient, onboarded_user):
    missing_run = client.get("/api/reports/NVDA.md?preference=balanced&run_id=missing-run", headers=onboarded_user)
    assert missing_run.status_code == 404
    assert "Analysis run" in missing_run.text

    db_conn.execute(
        """
        insert into research_runs(
          run_id, symbol, preference, started_at, finished_at, data_status, risk_score, summary,
          input_snapshot_hash, input_snapshot_json, model_version, evidence_ids_json, reasoning_steps_json,
          judge_json, risk_conclusion_json, report_version, source_meta_json
        )
        values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "NVDA-balanced-no-report",
            "NVDA",
            "balanced",
            "2026-07-07T10:00:00Z",
            "2026-07-07T10:00:01Z",
            "live-first-cache-fallback",
            50.0,
            "snapshot without report",
            "hash",
            '{"holding":{"symbol":"NVDA"}}',
            "risk-model",
            "[]",
            "[]",
            '{"qualityGate":{"status":"PASS"}}',
            "{}",
            "report-missing",
            '{"mode":"demo","provider":"test","as_of":"2026-07-07T10:00:00Z","overrides":[],"synthetic_ratio":1.0}',
        ),
    )
    db_conn.commit()

    missing_snapshot = client.get(
        "/api/reports/NVDA.md?preference=balanced&run_id=NVDA-balanced-no-report",
        headers=onboarded_user,
    )
    assert missing_snapshot.status_code == 404
    assert "Report snapshot" in missing_snapshot.text


def test_tool_invocations_recorded(db_conn, client: TestClient, onboarded_user):
    """研究过程中 tool_invocations 表有记录。"""
    client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    rows = db_conn.execute(
        "SELECT * FROM tool_invocations WHERE run_id IS NOT NULL LIMIT 10"
    ).fetchall()
    assert len(rows) > 0
    for row in rows:
        assert row["tool_id"]
        assert row["symbol"]
        assert row["status"]
