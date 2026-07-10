"""
测试数据管理：用于集成测试和 E2E 测试的数据工厂。
"""

from __future__ import annotations

import json
import random
import string
from datetime import datetime, timedelta


def random_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def make_user(email: str | None = None, password: str = "Test!1234") -> dict:
    """生成标准用户注册 payload。"""
    return {
        "email": email or f"test_user_{random_string(8)}@example.com",
        "password": password,
    }


def make_onboarding_payload(
    preference: str = "balanced",
    holdings: list[dict] | None = None,
) -> dict:
    """生成标准 onboarding payload。"""
    if holdings is None:
        holdings = [
            {"symbol": "NVDA", "name": "NVIDIA", "market": "us", "sector": "AI 算力",
             "shares": 100, "costPrice": 850.0},
        ]
    return {
        "preference": preference,
        "riskAnswers": {"maxDrawdown": "20%", "horizon": "1y"},
        "holdings": holdings,
    }


def make_us_holdings() -> list[dict]:
    """生成美股持仓列表。"""
    return [
        {"symbol": "NVDA", "name": "NVIDIA", "market": "us", "sector": "AI 算力",
         "shares": 100, "costPrice": 850.0},
        {"symbol": "TSLA", "name": "Tesla", "market": "us", "sector": "新能源",
         "shares": 50, "costPrice": 250.0},
        {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "market": "us", "sector": "科技指数",
         "shares": 200, "costPrice": 400.0},
    ]


def make_cn_holdings() -> list[dict]:
    """生成A股持仓列表。"""
    return [
        {"symbol": "600519", "name": "贵州茅台", "market": "cn", "sector": "消费龙头",
         "shares": 20, "costPrice": 1600.0},
        {"symbol": "000858", "name": "五粮液", "market": "cn", "sector": "消费龙头",
         "shares": 30, "costPrice": 120.0},
        {"symbol": "300750", "name": "宁德时代", "market": "cn", "sector": "新能源",
         "shares": 10, "costPrice": 280.0},
    ]


def make_evidence_record(
    symbol: str,
    source_type: str = "market_data",
    days_ago: int = 0,
    valid_days: int = 30,
) -> dict:
    """生成 evidence_records 插入记录。"""
    now = datetime.utcnow()
    observed_at = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    valid_until = (now + timedelta(days=valid_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "symbol": symbol,
        "claim": f"{source_type} data for {symbol} on {observed_at}",
        "source_type": source_type,
        "source_name": "test_factory",
        "observed_at": observed_at,
        "valid_until": valid_until,
        "confidence": 0.5 + random.random() * 0.5,
        "is_model_inferred": 0,
    }


def seed_evidence(db_conn, records: list[dict]):
    """向数据库批量插入 evidence。"""
    for rec in records:
        db_conn.execute(
            """
            INSERT INTO evidence_records(symbol, claim, source_type, source_name, source_url,
                                         observed_at, valid_until, confidence, is_model_inferred)
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                rec["symbol"], rec["claim"], rec["source_type"], rec["source_name"],
                rec["observed_at"], rec["valid_until"], rec["confidence"],
                rec["is_model_inferred"],
            ),
        )
    db_conn.commit()


def make_similar_scenario(
    query_symbol: str,
    matched_symbol: str,
    similarity: float = 0.8,
) -> dict:
    """生成 similar_scenarios 插入记录。"""
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "query_symbol": query_symbol,
        "query_as_of_date": "2026-06-01",
        "matched_symbol": matched_symbol,
        "matched_as_of_date": "2025-03-15",
        "similarity": similarity,
        "return_1w": -0.01 * random.random(),
        "return_1m": -0.03 * random.random(),
        "return_3m": 0.05 * random.random(),
        "max_drawdown_1w": -0.01 * random.random(),
        "max_drawdown_1m": -0.05 * random.random(),
        "max_drawdown_3m": -0.1 * random.random(),
        "volatility_1m": 0.15 + random.random() * 0.2,
        "model_id": "test_factory_model",
        "created_at": now,
    }
