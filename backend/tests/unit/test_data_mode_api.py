from __future__ import annotations

from fastapi.testclient import TestClient


SOURCE_META_KEYS = {"mode", "provider", "as_of", "overrides", "synthetic_ratio"}


def assert_source_meta(meta: dict):
    assert SOURCE_META_KEYS <= set(meta)


def test_data_mode_endpoint_reports_demo_contract(client: TestClient, monkeypatch):
    monkeypatch.setenv("INVESTMENT_RESEARCH_DATA_MODE", "demo")
    resp = client.get("/api/data-mode")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "demo"
    assert data["providerPolicy"] == "fixed_synthetic_demo"
    assert_source_meta(data["sourceMeta"])
    assert data["sourceMeta"]["synthetic_ratio"] == 1.0


def test_portfolio_source_meta_uses_synthetic_status_in_demo(client: TestClient, onboarded_user, monkeypatch):
    monkeypatch.setenv("INVESTMENT_RESEARCH_DATA_MODE", "demo")
    resp = client.get("/api/portfolio?preference=balanced", headers=onboarded_user)
    assert resp.status_code == 200
    data = resp.json()
    assert "dataMode" in data
    assert_source_meta(data["sourceMeta"])
    assert data["sourceMeta"]["mode"] == "demo"
    assert {item["dataStatus"] for item in data["holdings"]} == {"synthetic"}
    for holding in data["holdings"]:
        assert_source_meta(holding["sourceMeta"])


def test_health_and_auth_include_source_meta(client: TestClient, auth_headers, monkeypatch):
    monkeypatch.setenv("INVESTMENT_RESEARCH_DATA_MODE", "sandbox")
    health = client.get("/api/health").json()
    assert health["dataMode"]["mode"] == "sandbox"
    assert_source_meta(health["sourceMeta"])

    me = client.get("/api/auth/me", headers=auth_headers).json()
    assert me["dataMode"]["mode"] == "sandbox"
    assert_source_meta(me["sourceMeta"])
