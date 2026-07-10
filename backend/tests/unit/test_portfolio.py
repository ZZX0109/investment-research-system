"""
Portfolio 与 Watchlist 单元测试。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_get_portfolio_before_onboarding(client: TestClient, auth_headers):
    """未 onboarding 时，portfolio 返回结构化空组合载荷。"""
    resp = client.get("/api/portfolio", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "holdings" in data
    assert "metrics" in data
    assert isinstance(data["holdings"], list)
    assert data["metrics"]["marketValue"] == 0


def test_get_portfolio_after_onboarding(client: TestClient, onboarded_user):
    resp = client.get("/api/portfolio", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert isinstance(data["holdings"], list)
    assert len(data["holdings"]) >= 2
    symbols = {item["symbol"] for item in data["holdings"]}
    assert "NVDA" in symbols
    assert "TSLA" in symbols


def test_add_watchlist(client: TestClient, auth_headers):
    resp = client.post(
        "/api/watchlist",
        json={"symbol": "AMD", "market": "us", "name": "AMD"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AMD"
    assert data["market"] == "us"


def test_add_watchlist_duplicate(client: TestClient, auth_headers):
    client.post(
        "/api/watchlist",
        json={"symbol": "AMD", "market": "us", "name": "AMD"},
        headers=auth_headers,
    )
    resp = client.post(
        "/api/watchlist",
        json={"symbol": "AMD", "market": "us", "name": "AMD"},
        headers=auth_headers,
    )
    # 重复添加应返回 409 或 200（取决于实现）
    assert resp.status_code in (200, 409)


def test_report_settings_default(client: TestClient, auth_headers):
    resp = client.get("/api/settings/report", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "frequency" in data


def test_report_settings_update(client: TestClient, auth_headers):
    resp = client.post(
        "/api/settings/report",
        json={"frequency": "daily"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["frequency"] == "daily"
