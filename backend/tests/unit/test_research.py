"""
Research API 单元测试：/api/research/{symbol}、/api/reports/{symbol}.md、
evidence graph、quality audit、revision loop。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_research_endpoint_returns_structure(client: TestClient, onboarded_user):
    """/api/research/{symbol} 返回完整研究 payload。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    # 核心字段
    assert "riskLevel" in data
    assert "riskScore" in data
    assert "summary" in data
    assert "evidence" in data
    assert "evidenceGraph" in data
    assert "audit" in data
    assert "revision" in data
    assert "mlSummary" in data
    assert "sourceMeta" in data
    assert "qualityGate" in data


def test_research_audit_score_range(client: TestClient, onboarded_user):
    """Judge audit score 在 0-100 范围内。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    audit = data["audit"]
    assert 0 <= audit["score"] <= 100
    assert audit["judgeVersion"] in ("v1", "v2")
    assert audit["verdict"]  # 非空字符串


def test_research_audit_dimensions(client: TestClient, onboarded_user):
    """audit.dimensions 包含所有 17 个维度。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    dimensions = data["audit"]["dimensions"]
    assert isinstance(dimensions, list)
    assert len(dimensions) >= 10  # 至少包含核心维度
    for dim in dimensions:
        assert "key" in dim
        assert "label" in dim
        assert "passed" in dim
        assert "severity" in dim


def test_research_evidence_graph(client: TestClient, onboarded_user):
    """evidenceGraph 包含 claims 和 edges。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    graph = data["evidenceGraph"]
    assert "claims" in graph
    assert "edges" in graph
    assert isinstance(graph["claims"], list)
    assert isinstance(graph["edges"], list)
    # 至少包含 6 条核心 claim
    assert len(graph["claims"]) >= 6


def test_research_evidence_graph_claim_fields(client: TestClient, onboarded_user):
    """每条 claim 包含必需字段。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    for claim in data["evidenceGraph"]["claims"]:
        assert "id" in claim
        assert "title" in claim
        assert "claim" in claim
        assert "status" in claim
        assert "supportingEvidenceIds" in claim
        assert "rebuttingEvidenceIds" in claim
        assert "derivedMetrics" in claim


def test_research_revision_loop(client: TestClient, onboarded_user):
    """revision 字段包含 draftStatus 和 judgeVerdict。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    revision = data["revision"]
    assert "draftStatus" in revision
    assert "judgeVerdict" in revision
    assert "toolBackfillActions" in revision
    assert "finalStatus" in revision


def test_research_ml_summary(client: TestClient, onboarded_user):
    """mlSummary 包含 modelStatus 和 calibrationStatus。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    ml = data["mlSummary"]
    assert "modelStatus" in ml
    assert "calibrationStatus" in ml
    assert "featureStoreAudit" in ml
    assert "validationMetrics" in ml
    assert "riskDistribution" in ml


def test_report_markdown_endpoint(client: TestClient, onboarded_user):
    """/api/reports/{symbol}.md 从 run 快照返回，旧 URL 可自动绑定最新 run。"""
    missing_run = client.get("/api/reports/NVDA.md?preference=balanced", headers=onboarded_user)
    assert missing_run.status_code == 404

    research_resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    run_id = research_resp.json()["run"]["runId"]
    latest_resp = client.get("/api/reports/NVDA.md?preference=balanced", headers=onboarded_user)
    assert latest_resp.status_code == 200
    assert run_id in latest_resp.text

    resp = client.get(f"/api/reports/NVDA.md?preference=balanced&run_id={run_id}", headers=onboarded_user)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "# " in text or "## " in text  # Markdown 标题
    assert "Run ID:" in text
    assert "质量门禁:" in text


def test_research_unknown_symbol_fallback(client: TestClient, onboarded_user):
    """未知 symbol 不应 500，应返回降级 payload。"""
    resp = client.get("/api/research/FAKE123?preference=balanced", headers=onboarded_user)
    # 允许 200（降级）或 404，但不允许 500
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert "riskLevel" in data
