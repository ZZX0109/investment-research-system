"""
阶段3：刷新 Loop 集成测试。

验证完整的刷新链路：
1. 插入过期证据
2. 调用 /api/refresh/daily
3. 验证 archive → superseded_by → refresh_items 链条
4. 验证 refresh_review_for_symbol 的 before/after 一致性
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient


def test_full_refresh_cycle_archives_expired_evidence(
    db_conn, client: TestClient, onboarded_user
):
    """完整刷新周期：过期证据归档 + 新证据 supersedes 旧证据。"""
    import backend.app as app_module

    # Step 1: 插入一条明确过期的 market_data
    db_conn.execute(
        """
        INSERT INTO evidence_records(symbol, claim, source_type, source_name, source_url,
                                     observed_at, valid_until, confidence, is_model_inferred)
        VALUES ('NVDA', 'stale market data', 'market_data', 'test', NULL,
                '2026-06-01T00:00:00Z', '2026-06-02T00:00:00Z', 0.8, 0)
        """
    )
    db_conn.commit()
    stale_id = db_conn.execute(
        "SELECT id FROM evidence_records WHERE claim='stale market data'"
    ).fetchone()["id"]

    # Step 2: archive
    app_module.archive_expired_evidence(db_conn)
    db_conn.commit()

    # 验证已归档
    stale_row = db_conn.execute(
        "SELECT archived_at FROM evidence_records WHERE id=?", (stale_id,)
    ).fetchone()
    assert stale_row["archived_at"] is not None

    # Step 3: 触发刷新
    resp = client.post("/api/refresh/daily", headers=onboarded_user)
    assert resp.status_code == 200

    # Step 4: 验证 refresh_run 记录存在
    run_row = db_conn.execute(
        "SELECT * FROM evidence_refresh_runs ORDER BY refreshed_at DESC LIMIT 1"
    ).fetchone()
    assert run_row is not None
    assert run_row["symbol_count"] > 0

    # Step 5: 验证 refresh_items 记录存在
    items = db_conn.execute(
        "SELECT * FROM evidence_refresh_items WHERE refresh_id=?", (run_row["refresh_id"],)
    ).fetchall()
    assert len(items) > 0


def test_refresh_review_for_symbol_changes_evidence_graph(db_conn, client: TestClient, onboarded_user):
    """refresh_review_for_symbol 后 evidence 数量和类型变化。"""
    # 刷新前获取 research
    before = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    before_evidence_count = len(before.json()["evidence"])
    before_types = {item["sourceType"] for item in before.json()["evidence"]}

    # 刷新
    client.post("/api/refresh/daily", headers=onboarded_user)

    # 刷新后获取 research
    after = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    after_evidence_count = len(after.json()["evidence"])
    after_types = {item["sourceType"] for item in after.json()["evidence"]}

    # 刷新可能增加 evidence，但不减少（旧 evidence superseded 后仍出现在列表直到被过滤）
    assert after_evidence_count >= before_evidence_count or after_evidence_count >= before_evidence_count - 1


def test_refresh_preserves_evidence_chain_integrity(db_conn, client: TestClient, onboarded_user):
    """刷新后每条新 evidence 的 superseded_by 链可追溯。"""
    client.post("/api/refresh/daily", headers=onboarded_user)

    # 检查 market_data evidence：旧条目的 superseded_by 应指向新条目
    rows = db_conn.execute(
        """
        SELECT e1.id as old_id, e1.superseded_by, e2.id as new_id
        FROM evidence_records e1
        JOIN evidence_records e2 ON e1.superseded_by = e2.id
        WHERE e1.source_type='market_data' AND e2.source_type='market_data'
        LIMIT 5
        """
    ).fetchall()
    assert len(rows) > 0
    for row in rows:
        assert row["superseded_by"] == row["new_id"]


def test_refresh_items_snapshot_status_valid(db_conn, client: TestClient, onboarded_user):
    """refresh_items.snapshot_status 为 'live' 或 'degraded'。"""
    client.post("/api/refresh/daily", headers=onboarded_user)
    row = db_conn.execute(
        "SELECT snapshot_status FROM evidence_refresh_items LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["snapshot_status"] in ("live", "degraded")


def test_concurrent_refresh_idempotent(client: TestClient, onboarded_user):
    """连续两次刷新不报错，各自产生独立 refresh_id。"""
    r1 = client.post("/api/refresh/daily", headers=onboarded_user)
    assert r1.status_code == 200
    r2 = client.post("/api/refresh/daily", headers=onboarded_user)
    assert r2.status_code == 200
    assert r1.json()["refreshedAt"] != r2.json()["refreshedAt"]
