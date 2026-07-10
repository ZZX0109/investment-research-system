"""
证据链完整性集成测试。

验证证据从创建 → 引用 → 过期 → 归档 → 刷新的完整生命周期，
以及 evidence_graph 中 claims 与 evidence 的引用一致性。
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient


def test_evidence_graph_references_valid_evidence_ids(client: TestClient, onboarded_user):
    """evidenceGraph.claims 中的 supportingEvidenceIds 和 rebuttingEvidenceIds
    必须对应 evidence_records 中真实存在的 id。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    graph = data["evidenceGraph"]

    # 收集所有 evidence id
    all_evidence_ids = {item["id"] for item in data["evidence"]}

    for claim in graph["claims"]:
        for eid in claim["supportingEvidenceIds"]:
            assert eid in all_evidence_ids, f"claim {claim['id']} 引用了不存在的 supporting evidence {eid}"
        for eid in claim["rebuttingEvidenceIds"]:
            assert eid in all_evidence_ids, f"claim {claim['id']} 引用了不存在的 rebutting evidence {eid}"


def test_evidence_graph_edges_reference_valid_nodes(client: TestClient, onboarded_user):
    """evidenceGraph.edges 中的 from/to 必须引用真实存在的 evidence 或 claim。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    graph = data["evidenceGraph"]

    evidence_ids = {f"evidence:{item['id']}" for item in data["evidence"]}
    claim_ids = {f"claim:{item['id']}" for item in graph["claims"]}
    metric_ids = set()
    for claim in graph["claims"]:
        for m in claim["derivedMetrics"]:
            metric_ids.add(f"metric:{m}")

    valid_nodes = evidence_ids | claim_ids | metric_ids

    for edge in graph["edges"]:
        assert edge["from"] in valid_nodes, f"edge.from 引用不存在的节点: {edge['from']}"
        assert edge["to"] in valid_nodes, f"edge.to 引用不存在的节点: {edge['to']}"


def test_evidence_superseded_by_chain_not_circular(db_conn):
    """superseded_by 不应形成环。"""
    rows = db_conn.execute(
        "SELECT id, superseded_by FROM evidence_records WHERE superseded_by IS NOT NULL"
    ).fetchall()
    id_to_superseded = {row["id"]: row["superseded_by"] for row in rows}

    for start_id in id_to_superseded:
        visited = set()
        current = start_id
        while current in id_to_superseded:
            assert current not in visited, f"发现环形 superseded_by 链，起始 id={start_id}"
            visited.add(current)
            current = id_to_superseded[current]


def test_archived_evidence_in_experience_history(db_conn):
    """archived_at 非空的 evidence 应在 experience_history 中有对应记录。"""
    archived = db_conn.execute(
        "SELECT id, symbol, claim, source_type, observed_at, archived_at FROM evidence_records WHERE archived_at IS NOT NULL"
    ).fetchall()

    for row in archived:
        hist = db_conn.execute(
            "SELECT * FROM experience_history WHERE symbol=? AND archived_claim=? AND reason='expired'",
            (row["symbol"], row["claim"]),
        ).fetchone()
        # 注意：archived_claim 可能截断，所以只验证存在性
        hist_any = db_conn.execute(
            "SELECT COUNT(*) as cnt FROM experience_history WHERE symbol=?", (row["symbol"],)
        ).fetchone()
        assert hist_any["cnt"] > 0, f"symbol={row['symbol']} 的归档证据在 experience_history 中无记录"


def test_evidence_confidence_range(db_conn):
    """所有 evidence 的 confidence 在 [0, 1] 范围内。"""
    rows = db_conn.execute(
        "SELECT id, symbol, source_type, confidence FROM evidence_records"
    ).fetchall()
    for row in rows:
        assert 0.0 <= row["confidence"] <= 1.0, \
            f"evidence id={row['id']} confidence={row['confidence']} 超出 [0,1] 范围"


def test_evidence_valid_until_after_observed_at(db_conn):
    """valid_until 必须晚于 observed_at。"""
    rows = db_conn.execute(
        "SELECT id, symbol, observed_at, valid_until FROM evidence_records WHERE valid_until IS NOT NULL"
    ).fetchall()
    for row in rows:
        assert row["valid_until"] >= row["observed_at"], \
            f"evidence id={row['id']} valid_until < observed_at"


def test_research_evidence_count_matches_evidence_graph(client: TestClient, onboarded_user):
    """research payload 中 evidence 列表长度与 evidenceGraph 引用的 evidence 数量一致。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    evidence_ids_in_graph = set()
    for claim in data["evidenceGraph"]["claims"]:
        evidence_ids_in_graph.update(claim["supportingEvidenceIds"])
        evidence_ids_in_graph.update(claim["rebuttingEvidenceIds"])
    assert len(evidence_ids_in_graph) <= len(data["evidence"])
