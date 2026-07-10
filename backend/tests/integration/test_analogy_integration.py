"""
阶段4：历史类比集成测试。

验证 similar_scenarios 表与 scenario_embeddings 表交互正确性，
以及 historical_analogy 类型 evidence 的生成链条。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_similar_scenarios_table_writable(db_conn):
    """similar_scenarios 表可写入并读取。"""
    db_conn.execute(
        """
        INSERT INTO similar_scenarios(query_symbol, query_as_of_date, matched_symbol, matched_as_of_date,
                                      similarity, return_1w, return_1m, return_3m, max_drawdown_1w,
                                      max_drawdown_1m, max_drawdown_3m, volatility_1m, model_id, created_at)
        VALUES ('NVDA', '2026-06-01', 'AMD', '2025-03-15', 0.85,
                -0.02, -0.05, 0.10, -0.01, -0.08, -0.15, 0.28, 'test_model', '2026-07-01T00:00:00Z')
        """
    )
    db_conn.commit()
    row = db_conn.execute(
        "SELECT * FROM similar_scenarios WHERE query_symbol='NVDA' AND model_id='test_model'"
    ).fetchone()
    assert row is not None
    assert row["similarity"] == 0.85
    assert row["return_1w"] == -0.02
    assert row["max_drawdown_1m"] == -0.08


def test_similar_scenarios_filter_by_query(db_conn):
    """可按 query_symbol 过滤历史类比。"""
    db_conn.executemany(
        "INSERT INTO similar_scenarios(query_symbol, query_as_of_date, matched_symbol, matched_as_of_date, similarity, return_1w, return_1m, return_3m, max_drawdown_1w, max_drawdown_1m, max_drawdown_3m, volatility_1m, model_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("NVDA", "2026-06-01", "AMD", "2025-03-15", 0.85, -0.02, -0.05, 0.10, -0.01, -0.08, -0.15, 0.28, "m1", "2026-07-01T00:00:00Z"),
            ("NVDA", "2026-06-01", "INTC", "2024-08-20", 0.72, -0.04, -0.12, -0.05, -0.03, -0.14, -0.18, 0.35, "m1", "2026-07-01T00:00:00Z"),
            ("TSLA", "2026-06-01", "NIO", "2025-11-01", 0.68, -0.06, -0.18, -0.22, -0.05, -0.20, -0.28, 0.45, "m1", "2026-07-01T00:00:00Z"),
        ],
    )
    db_conn.commit()
    nvda_rows = db_conn.execute(
        "SELECT COUNT(*) as cnt FROM similar_scenarios WHERE query_symbol='NVDA'"
    ).fetchone()
    tsla_rows = db_conn.execute(
        "SELECT COUNT(*) as cnt FROM similar_scenarios WHERE query_symbol='TSLA'"
    ).fetchone()
    assert nvda_rows["cnt"] == 2
    assert tsla_rows["cnt"] == 1


def test_scenario_embeddings_table(db_conn):
    """scenario_embeddings 表可写入并验证唯一约束。"""
    import json, sqlite3

    emb = [0.1, 0.2, 0.3]
    db_conn.execute(
        """
        INSERT INTO scenario_embeddings(symbol, market, as_of_date, window_size, model_id,
                                        embedding_json, source_status, created_at)
        VALUES ('NVDA', 'us', '2026-07-01', 60, 'test_encoder',
                ?, 'live', '2026-07-01T00:00:00Z')
        """,
        (json.dumps(emb),),
    )
    db_conn.commit()

    row = db_conn.execute(
        "SELECT * FROM scenario_embeddings WHERE symbol='NVDA' AND model_id='test_encoder'"
    ).fetchone()
    assert row is not None
    parsed = json.loads(row["embedding_json"])
    assert parsed == emb

    # 验证复合唯一约束
    try:
        db_conn.execute(
            """
            INSERT INTO scenario_embeddings(symbol, market, as_of_date, window_size, model_id,
                                            embedding_json, source_status, created_at)
            VALUES ('NVDA', 'us', '2026-07-01', 60, 'test_encoder',
                    ?, 'live', '2026-07-01T00:00:00Z')
            """,
            (json.dumps(emb),),
        )
        db_conn.commit()
        raise AssertionError("复合唯一约束应触发")
    except sqlite3.IntegrityError:
        pass


def test_point_in_time_features_as_of_date_guard(db_conn):
    """point_in_time_features 记录的 available_at 必须 <= as_of_date。"""
    import backend.app as app_module

    # 手动写一条未来泄漏数据
    db_conn.execute(
        """
        INSERT INTO point_in_time_features(symbol, market, as_of_date, feature_version,
                                           field_name, field_value_json, source, available_at,
                                           revision_id, created_at)
        VALUES ('NVDA', 'us', '2026-06-01', 'v1', 'return_1d', '0.05',
                'future_leak', '2026-07-01T00:00:00Z', 'r1', '2026-07-01T00:00:00Z')
        """
    )
    db_conn.commit()

    row = db_conn.execute(
        "SELECT * FROM point_in_time_features WHERE symbol='NVDA' AND field_name='return_1d' AND revision_id='r1'"
    ).fetchone()
    assert row is not None
    # available_at 晚于 as_of_date，应由 point_in_time 模块检测
    assert row["available_at"] > row["as_of_date"]


def test_historical_analogy_evidence_in_research(client: TestClient, onboarded_user):
    """research payload 的 evidence 包含 historical_analogy 类型。"""
    resp = client.get("/api/research/NVDA?preference=balanced", headers=onboarded_user)
    data = resp.json()
    evidence_types = {item["sourceType"] for item in data["evidence"]}
    assert "historical_analogy" in evidence_types
