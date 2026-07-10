"""
阶段3：刷新与复盘 Loop 单元测试。
覆盖 archive_expired_evidence、refresh_review_for_symbol、refresh_user_data。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _insert_test_evidence(db_conn, symbol: str, source_type: str, valid_until: str, claim: str = "test claim"):
    """向 evidence_records 插入一条测试证据。"""
    db_conn.execute(
        """
        INSERT INTO evidence_records(symbol, claim, source_type, source_name, source_url,
                                     observed_at, valid_until, confidence, is_model_inferred)
        VALUES (?, ?, ?, 'test_source', NULL, '2026-07-01T00:00:00Z', ?, 0.8, 0)
        """,
        (symbol, claim, source_type, valid_until),
    )
    db_conn.commit()


def test_archive_expired_evidence(db_conn):
    """过期的 evidence 被归档到 experience_history。"""
    import backend.app as app_module

    # 插入一条已过期证据
    _insert_test_evidence(db_conn, "NVDA", "market_data", "2026-06-01T00:00:00Z")

    before = db_conn.execute("SELECT COUNT(*) as cnt FROM experience_history").fetchone()["cnt"]
    app_module.archive_expired_evidence(db_conn)
    after = db_conn.execute("SELECT COUNT(*) as cnt FROM experience_history").fetchone()["cnt"]

    assert after == before + 1
    # 验证 archived_at 已设置
    row = db_conn.execute(
        "SELECT archived_at FROM evidence_records WHERE symbol='NVDA' AND source_type='market_data' AND claim='test claim' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["archived_at"] is not None


def test_refresh_daily_endpoint(client: TestClient, onboarded_user):
    """POST /api/refresh/daily 触发刷新。"""
    resp = client.post("/api/refresh/daily", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    assert "refreshedAt" in data
    assert "count" in data
    assert isinstance(data["count"], int)


def test_refresh_creates_refresh_run_record(db_conn, client: TestClient, onboarded_user):
    """刷新后 evidence_refresh_runs 表有记录。"""
    before = db_conn.execute("SELECT COUNT(*) as cnt FROM evidence_refresh_runs").fetchone()["cnt"]
    client.post("/api/refresh/daily", headers=onboarded_user)
    after = db_conn.execute("SELECT COUNT(*) as cnt FROM evidence_refresh_runs").fetchone()["cnt"]
    assert after == before + 1


def test_refresh_creates_refresh_items(db_conn, client: TestClient, onboarded_user):
    """刷新后 evidence_refresh_items 表有记录。"""
    before = db_conn.execute("SELECT COUNT(*) as cnt FROM evidence_refresh_items").fetchone()["cnt"]
    client.post("/api/refresh/daily", headers=onboarded_user)
    after = db_conn.execute("SELECT COUNT(*) as cnt FROM evidence_refresh_items").fetchone()["cnt"]
    assert after > before


def test_refresh_items_have_score_delta(db_conn, client: TestClient, onboarded_user):
    """refresh_items 包含 before_score 和 after_score。"""
    client.post("/api/refresh/daily", headers=onboarded_user)
    row = db_conn.execute(
        "SELECT before_score, after_score, risk_score_delta FROM evidence_refresh_items LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["before_score"] is not None
    assert row["after_score"] is not None


def test_refresh_items_have_evidence_changes(db_conn, client: TestClient, onboarded_user):
    """refresh_items.evidence_changes 是合法 JSON。"""
    import json

    client.post("/api/refresh/daily", headers=onboarded_user)
    row = db_conn.execute(
        "SELECT evidence_changes FROM evidence_refresh_items LIMIT 1"
    ).fetchone()
    assert row is not None
    changes = json.loads(row["evidence_changes"])
    assert isinstance(changes, dict)
    assert "newEvidenceIds" in changes


def test_refresh_items_have_conclusion_changes(db_conn, client: TestClient, onboarded_user):
    """refresh_items.conclusion_changes 是合法 JSON 或字符串列表。"""
    import json

    client.post("/api/refresh/daily", headers=onboarded_user)
    row = db_conn.execute(
        "SELECT conclusion_changes FROM evidence_refresh_items LIMIT 1"
    ).fetchone()
    assert row is not None
    changes = json.loads(row["conclusion_changes"])
    assert isinstance(changes, list)


def test_refresh_preserves_old_evidence_with_superseded_by(db_conn, client: TestClient, onboarded_user):
    """刷新后旧 evidence 的 superseded_by 指向新 evidence。"""
    # 先插入一条证据
    _insert_test_evidence(db_conn, "TSLA", "news_event", "2099-12-31T00:00:00Z", "pre-refresh news")
    db_conn.commit()

    old_id = db_conn.execute(
        "SELECT id FROM evidence_records WHERE symbol='TSLA' AND source_type='news_event' AND archived_at IS NULL"
    ).fetchone()["id"]

    client.post("/api/refresh/daily", headers=onboarded_user)

    row = db_conn.execute(
        "SELECT superseded_by FROM evidence_records WHERE id=?", (old_id,)
    ).fetchone()
    assert row["superseded_by"] is not None
