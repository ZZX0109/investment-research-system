"""
E2E 测试：从注册到报告生成的完整用户流程。

运行方式：
    cd /path/to/investment-research-system
    python -m pytest e2e/test_full_flow.py -v
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# 复用 backend tests 的 fixtures
from backend.tests.conftest import client  # noqa: F401


def test_register_to_report_full_flow(client: TestClient):
    """
    完整端到端流程：
    1. 注册
    2. Onboarding（设置偏好 + 持仓）
    3. 查看 portfolio
    4. 刷新数据
    5. 研究某个标的
    6. 生成 Markdown 报告
    7. 查看 ML 预测
    """

    # ---- Step 1: Register ----
    resp = client.post(
        "/api/auth/register",
        json={"email": "e2e_user@example.com", "password": "E2E!Test99"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # ---- Step 2: Onboarding ----
    resp = client.post(
        "/api/onboarding",
        json={
            "preference": "growth",
            "riskAnswers": {"maxDrawdown": "25%", "horizon": "2y"},
            "holdings": [
                {"symbol": "NVDA", "name": "NVIDIA", "market": "us", "sector": "AI 算力",
                 "shares": 100, "costPrice": 850.0},
                {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "market": "us", "sector": "科技指数",
                 "shares": 200, "costPrice": 400.0},
                {"symbol": "600519", "name": "贵州茅台", "market": "cn", "sector": "消费龙头",
                 "shares": 20, "costPrice": 1600.0},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    onboarding_data = resp.json()
    assert onboarding_data["preference"] == "growth"
    assert onboarding_data["onboardingCompleted"] is True

    # ---- Step 3: Portfolio ----
    resp = client.get("/api/portfolio", headers=headers)
    assert resp.status_code == 200
    portfolio = resp.json()
    assert len(portfolio["holdings"]) >= 3
    symbols = {item["symbol"] for item in portfolio["holdings"]}
    assert "NVDA" in symbols
    assert "QQQ" in symbols
    assert "600519" in symbols

    # ---- Step 4: Refresh ----
    resp = client.post("/api/refresh/daily", headers=headers)
    assert resp.status_code == 200
    refresh_data = resp.json()
    assert "refreshedAt" in refresh_data
    assert refresh_data["count"] > 0

    # ---- Step 5: Research ----
    resp = client.get("/api/research/NVDA?preference=growth", headers=headers)
    assert resp.status_code == 200
    research_data = resp.json()

    # 验证核心结构
    assert "riskLevel" in research_data
    assert research_data["riskLevel"] in ("low", "medium", "high")
    assert "riskScore" in research_data
    assert "summary" in research_data
    assert "evidence" in research_data
    assert len(research_data["evidence"]) >= 3  # 至少3条证据
    assert "run" in research_data
    assert "qualityGate" in research_data

    # 验证 audit
    audit = research_data["audit"]
    assert audit["score"] >= 0
    assert isinstance(audit["dimensions"], list)
    assert any(dim["key"] == "freshness" for dim in audit["dimensions"])
    assert any(dim["key"] == "bear_case" for dim in audit["dimensions"])
    assert any(dim["key"] == "pit_feature_store" for dim in audit["dimensions"])
    assert any(dim["key"] == "risk_distribution_engine" for dim in audit["dimensions"])

    # 验证 evidence graph
    graph = research_data["evidenceGraph"]
    assert isinstance(graph["claims"], list)
    assert isinstance(graph["edges"], list)
    for claim in graph["claims"]:
        assert claim["id"]
        assert claim["title"]
        assert claim["status"] in ("supported", "contested", "unsupported", "pending")

    # 验证 revision loop
    revision = research_data["revision"]
    assert revision["draftStatus"]
    assert revision["judgeVerdict"]
    assert revision["finalStatus"] in ("approved_research_note", "data_insufficient", "quality_gate_hold", "quality_gate_blocked")

    # 验证 mlSummary
    ml = research_data["mlSummary"]
    assert "modelStatus" in ml
    assert "calibrationStatus" in ml
    assert "featureStoreAudit" in ml
    assert "validationMetrics" in ml
    assert "riskDistribution" in ml

    # ---- Step 6: Markdown Report ----
    run_id = research_data["run"]["runId"]
    resp = client.get("/api/reports/NVDA.md?preference=growth", headers=headers)
    assert resp.status_code == 400
    resp = client.get(f"/api/reports/NVDA.md?preference=growth&run_id={run_id}", headers=headers)
    assert resp.status_code == 200
    md_text = resp.text
    assert "# " in md_text or "## " in md_text
    assert "NVDA" in md_text
    assert run_id in md_text

    # ---- Step 7: ML Predictions / Scenarios ----
    resp = client.get("/api/ml/predictions/NVDA", headers=headers)
    assert resp.status_code == 200

    resp = client.get("/api/ml/scenarios/NVDA", headers=headers)
    assert resp.status_code == 200

    # ---- Step 8: Report Settings ----
    resp = client.post(
        "/api/settings/report",
        json={"frequency": "daily"},
        headers=headers,
    )
    assert resp.status_code == 200
    settings = resp.json()
    assert settings["frequency"] == "daily"


def test_full_flow_conservative_user(client: TestClient):
    """保守型用户的完整流程。"""
    # Register
    resp = client.post(
        "/api/auth/register",
        json={"email": "conservative@example.com", "password": "Safe!Pass1"},
    )
    assert resp.status_code == 200
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Onboarding with conservative preference
    resp = client.post(
        "/api/onboarding",
        json={
            "preference": "conservative",
            "riskAnswers": {"maxDrawdown": "10%", "horizon": "3m"},
            "holdings": [
                {"symbol": "510300", "name": "沪深300 ETF", "market": "cn", "sector": "宽基指数",
                 "shares": 5000, "costPrice": 3.8},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200

    # Refresh
    client.post("/api/refresh/daily", headers=headers)

    # Research
    resp = client.get("/api/research/510300?preference=conservative", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "riskLevel" in data


def test_api_key_management_flow(client: TestClient):
    """API Key 管理流程。"""
    resp = client.post(
        "/api/auth/register",
        json={"email": "apikey_test@example.com", "password": "Key!Test123"},
    )
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 设置 API key
    resp = client.post(
        "/api/api-keys",
        json={"provider": "openai", "apiKey": "sk-test-1234567890abcdef"},
        headers=headers,
    )
    assert resp.status_code == 200

    # 查看 API keys
    resp = client.get("/api/api-keys", headers=headers)
    assert resp.status_code == 200
    keys_payload = resp.json()
    assert "apiKeys" in keys_payload
    keys = keys_payload["apiKeys"]
    assert isinstance(keys, list)
    assert len(keys) >= 1
    assert keys[0]["provider"] == "openai"
    assert "..." in keys[0]["maskedKey"]

    # 删除 API key
    resp = client.delete("/api/api-keys/openai", headers=headers)
    assert resp.status_code == 200

    resp = client.get("/api/api-keys", headers=headers)
    assert resp.json()["apiKeys"] == []
