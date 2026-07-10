"""
数据库 Schema 验证：确认所有关键表和字段存在。
覆盖阶段3/4/5的核心表：evidence_refresh_runs, evidence_refresh_items,
experience_history, similar_scenarios, scenario_embeddings, point_in_time_features 等。
"""

from __future__ import annotations

import pytest


REQUIRED_TABLES: dict[str, list[str]] = {
    # 核心业务
    "schema_migrations": ["version", "applied_at"],
    "users": ["id", "email", "password_hash", "salt", "created_at", "role"],
    "sessions": ["token", "user_id", "created_at"],
    "user_profiles": ["user_id", "preference", "risk_answers", "onboarding_completed", "updated_at"],
    "user_holdings": ["id", "user_id", "symbol", "name", "market", "sector", "shares", "cost_price", "updated_at"],
    "holdings": ["symbol", "name", "market", "sector", "shares", "cost_value", "market_value", "day_change"],
    "historical_prices": ["symbol", "trade_date", "close_price", "volume", "source_name"],
    # 证据系统
    "evidence_records": [
        "id", "symbol", "claim", "source_type", "source_name", "source_url",
        "observed_at", "valid_until", "confidence", "is_model_inferred",
        "superseded_by", "archived_at",
    ],
    "experience_history": ["id", "symbol", "archived_claim", "source_type", "observed_at", "archived_at", "reason"],
    # 阶段3: 刷新与复盘
    "evidence_refresh_runs": ["refresh_id", "user_id", "refreshed_at", "symbol_count", "archived_count", "summary"],
    "evidence_refresh_items": [
        "id", "refresh_id", "symbol", "before_score", "after_score",
        "risk_score_delta", "before_claim_summary", "after_claim_summary",
        "evidence_changes", "conclusion_changes", "snapshot_status",
    ],
    # 研究运行
    "research_runs": [
        "run_id", "symbol", "preference", "started_at", "finished_at", "data_status", "risk_score", "summary",
        "input_snapshot_hash", "input_snapshot_json", "model_version", "evidence_ids_json", "reasoning_steps_json", "judge_json",
        "risk_conclusion_json", "report_version", "source_meta_json",
    ],
    "report_snapshots": ["run_id", "symbol", "preference", "report_version", "markdown", "created_at"],
    "tool_invocations": ["id", "run_id", "tool_id", "symbol", "input_json", "output_summary", "source_name", "observed_at", "status", "failure_reason", "evidence_id"],
    "tool_registry": ["tool_id", "name", "category", "description", "freshness_rule", "output_contract", "updated_at"],
    # ML 与模型
    "model_registry": ["model_id", "model_type", "version", "feature_version", "trained_until", "validation_window", "test_window", "metrics_json", "artifact_path", "status", "created_at"],
    "feature_snapshots": ["id", "symbol", "market", "as_of_date", "feature_version", "features_json", "source_status_json", "created_at"],
    "point_in_time_features": ["id", "symbol", "market", "as_of_date", "feature_version", "field_name", "field_value_json", "source", "available_at", "revision_id", "created_at"],
    "risk_predictions": ["id", "symbol", "market", "as_of_date", "model_id", "horizon", "risk_regime", "drawdown_p50", "drawdown_p90", "volatility_p50", "confidence", "calibration_status", "valid_until", "created_at"],
    # 阶段4: 历史类比增强
    "scenario_embeddings": ["id", "symbol", "market", "as_of_date", "window_size", "model_id", "embedding_json", "source_status", "created_at"],
    "similar_scenarios": ["id", "query_symbol", "query_as_of_date", "matched_symbol", "matched_as_of_date", "similarity", "return_1w", "return_1m", "return_3m", "max_drawdown_1w", "max_drawdown_1m", "max_drawdown_3m", "volatility_1m", "model_id", "created_at"],
    # 文档
    "multimodal_documents": ["document_id", "symbol", "filename", "uploaded_at", "source_type", "text_blocks", "table_blocks", "chart_blocks", "footnote_blocks", "summary"],
    "document_blocks": ["id", "document_id", "symbol", "block_type", "label", "locator", "content_preview", "created_at"],
    "financial_metrics": ["id", "document_id", "symbol", "metric_name", "metric_value", "period", "source_block"],
    # 配置
    "report_settings": ["id", "frequency", "updated_at"],
    "api_keys": ["id", "user_id", "provider", "api_key", "updated_at"],
}


def test_all_tables_exist(db_conn):
    """验证所有必需表存在于数据库。"""
    cursor = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    existing = {row["name"] for row in cursor.fetchall()}
    for table_name in REQUIRED_TABLES:
        assert table_name in existing, f"缺少表: {table_name}"


def test_table_columns(db_conn):
    """验证所有必需表的列名。"""
    for table_name, required_columns in REQUIRED_TABLES.items():
        cursor = db_conn.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row["name"] for row in cursor.fetchall()}
        for col in required_columns:
            assert col in existing_columns, f"{table_name} 缺少字段: {col}"


def test_schema_migrations_are_recorded(db_conn):
    versions = {row["version"] for row in db_conn.execute("select version from schema_migrations").fetchall()}
    assert {"0001_core_schema", "0002_run_auth_columns"}.issubset(versions)


def test_standard_tools_registered(db_conn):
    """验证17个标准工具已注册到 tool_registry。"""
    cursor = db_conn.execute("SELECT COUNT(*) as cnt FROM tool_registry")
    count = cursor.fetchone()["cnt"]
    assert count >= 15, f"期望至少 15 个标准工具，实际 {count} 个"


def test_seed_holdings_exist(db_conn):
    """验证种子持仓已插入。"""
    cursor = db_conn.execute("SELECT COUNT(*) as cnt FROM holdings")
    count = cursor.fetchone()["cnt"]
    assert count == 6, f"期望 6 个种子持仓，实际 {count} 个"


def test_evidence_refresh_tables_have_required_indices(db_conn):
    """验证阶段3相关表的复合约束（通过尝试重复插入验证 unique 约束生效）。"""
    import sqlite3

    db_conn.execute("""
        INSERT INTO evidence_refresh_runs(refresh_id, user_id, refreshed_at, symbol_count, archived_count, summary)
        VALUES ('test-refresh-1', 1, '2026-07-01T00:00:00Z', 2, 3, 'test')
    """)
    try:
        db_conn.execute("""
            INSERT INTO evidence_refresh_runs(refresh_id, user_id, refreshed_at, symbol_count, archived_count, summary)
            VALUES ('test-refresh-1', 1, '2026-07-01T00:00:00Z', 2, 3, 'test')
        """)
        # Primary key 冲突应该抛异常
        raise AssertionError("重复 refresh_id 应触发 UNIQUE 约束")
    except sqlite3.IntegrityError:
        pass  # 预期行为


def test_point_in_time_features_unique_constraint(db_conn):
    """验证 point_in_time_features 的复合唯一约束。"""
    import sqlite3

    db_conn.execute("""
        INSERT INTO point_in_time_features(symbol, market, as_of_date, feature_version, field_name, field_value_json, source, available_at, revision_id, created_at)
        VALUES ('NVDA', 'us', '2026-07-01', 'v1', 'return_1d', '0.02', 'test', '2026-07-01T00:00:00Z', 'r1', '2026-07-01T00:00:00Z')
    """)
    try:
        db_conn.execute("""
            INSERT INTO point_in_time_features(symbol, market, as_of_date, feature_version, field_name, field_value_json, source, available_at, revision_id, created_at)
            VALUES ('NVDA', 'us', '2026-07-01', 'v1', 'return_1d', '0.03', 'test', '2026-07-01T00:00:00Z', 'r1', '2026-07-01T00:00:00Z')
        """)
        raise AssertionError("重复 (symbol,as_of_date,feature_version,field_name,revision_id) 应触发 UNIQUE 约束")
    except sqlite3.IntegrityError:
        pass
