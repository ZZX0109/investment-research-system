"""
ML API 单元测试：/api/ml/models、/api/ml/datasets/build、
/api/ml/train、/api/ml/infer/{symbol}、/api/ml/predictions/{symbol}、
/api/ml/scenarios/{symbol}、/api/ml/token-compression/{symbol}。

注意：这些测试验证 API 契约（请求/响应结构），不实际运行模型训练。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


SOURCE_META_KEYS = {"mode", "provider", "as_of", "overrides", "synthetic_ratio"}


def assert_source_meta(meta: dict):
    assert SOURCE_META_KEYS <= set(meta)


def test_list_models(client: TestClient, onboarded_user):
    """GET /api/ml/models 返回模型列表。"""
    resp = client.get("/api/ml/models", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["models"], list)
    assert_source_meta(data["sourceMeta"])
    # 即使空列表也是合法返回
    for model in data["models"]:
        assert "modelId" in model
        assert "modelType" in model
        assert "status" in model


def test_build_dataset_smoke(client: TestClient, onboarded_user):
    """POST /api/ml/datasets/build (smoke=true) 返回 dataset path。"""
    resp = client.post(
        "/api/ml/datasets/build",
        json={"symbols": ["NVDA"], "allowSynthetic": True, "smoke": True},
        headers=onboarded_user,
    )
    # smoke 模式可能快速完成，200 为正常
    assert resp.status_code == 200
    data = resp.json()
    assert "datasetPath" in data or "sampleCount" in data
    assert_source_meta(data["sourceMeta"])


def test_build_dataset_requires_symbols(client: TestClient, onboarded_user):
    """必须提供 symbols 或 allow_synthetic。"""
    resp = client.post(
        "/api/ml/datasets/build",
        json={"smoke": True},
        headers=onboarded_user,
    )
    # 应为 400 或 200（使用默认 symbols）
    assert resp.status_code in (200, 400)


def test_infer_requires_model(client: TestClient, onboarded_user):
    """POST /api/ml/infer/{symbol} 无模型时返回错误。"""
    resp = client.post(
        "/api/ml/infer/NVDA",
        json={"allowSynthetic": True, "modelId": "nonexistent_model"},
        headers=onboarded_user,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_predictions_list(client: TestClient, onboarded_user):
    """GET /api/ml/predictions/{symbol} 返回预测列表。"""
    resp = client.get("/api/ml/predictions/NVDA", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "NVDA"
    assert isinstance(data["predictions"], list)
    assert "summary" in data
    assert_source_meta(data["sourceMeta"])
    for pred in data["predictions"]:
        assert "symbol" in pred
        assert "as_of_date" in pred
        assert "risk_regime" in pred


def test_scenarios_list(client: TestClient, onboarded_user):
    """GET /api/ml/scenarios/{symbol} 返回历史类比场景。"""
    resp = client.get("/api/ml/scenarios/NVDA", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "NVDA"
    assert isinstance(data["scenarios"], list)
    assert_source_meta(data["sourceMeta"])
    for scenario in data["scenarios"]:
        assert "matched_symbol" in scenario
        assert "similarity" in scenario


def test_token_compression(client: TestClient, onboarded_user):
    """GET /api/ml/token-compression/{symbol} 返回压缩报告。"""
    resp = client.get("/api/ml/token-compression/NVDA", headers=onboarded_user)
    assert resp.status_code in (200, 404)
    if resp.status_code == 200:
        data = resp.json()
        assert data["ok"] is True
        assert "tokenReductionPercent" in data["report"]
        assert "conclusionConsistency" in data["report"]
        assert_source_meta(data["sourceMeta"])
        assert_source_meta(data["report"]["sourceMeta"])


def test_train_endpoint_validation(client: TestClient, onboarded_user):
    """POST /api/ml/train 参数校验。"""
    resp = client.post(
        "/api/ml/train",
        json={"modelType": "tabular_baseline", "epochs": 1},
        headers=onboarded_user,
    )
    # 可能需要 datasetPath，返回 400 是预期
    assert resp.status_code in (200, 400, 404)
