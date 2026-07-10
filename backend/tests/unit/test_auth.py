"""
认证模块单元测试：注册、登录、Token 校验、密码规则、会话管理。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_register_success(client: TestClient):
    resp = client.post(
        "/api/auth/register",
        json={"email": "newuser@example.com", "password": "Abc!2345"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["accessToken"] == data["token"]
    assert data["accessExpiresAt"]
    assert "investment_research_refresh" in resp.headers.get("set-cookie", "")
    assert data["user"]["email"] == "newuser@example.com"
    assert data["user"]["role"] == "user"


def test_register_weak_password(client: TestClient):
    resp = client.post(
        "/api/auth/register",
        json={"email": "weak@example.com", "password": "123"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "Password" in data["detail"]


def test_register_duplicate_email(client: TestClient, auth_headers):
    resp = client.post(
        "/api/auth/register",
        json={"email": "tester@example.com", "password": "Abc!2345"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "already" in data["detail"].lower()


def test_login_success(client: TestClient):
    # 先注册
    client.post(
        "/api/auth/register",
        json={"email": "login_test@example.com", "password": "Xyz@5678"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "login_test@example.com", "password": "Xyz@5678"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["email"] == "login_test@example.com"


def test_login_wrong_password(client: TestClient, auth_headers):
    resp = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "Wrong!000"},
    )
    assert resp.status_code == 401


def test_me_without_token(client: TestClient):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_with_valid_token(client: TestClient, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "tester@example.com"


def test_me_with_invalid_token(client: TestClient):
    resp = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer fake-token-deadbeef"},
    )
    assert resp.status_code == 401


def test_refresh_rotates_access_token_and_revokes_old_token(client: TestClient):
    register = client.post(
        "/api/auth/register",
        json={"email": "refresh@example.com", "password": "Refresh!2345"},
    )
    assert register.status_code == 200
    old_token = register.json()["token"]

    refreshed = client.post("/api/auth/refresh")

    assert refreshed.status_code == 200, refreshed.text
    new_token = refreshed.json()["token"]
    assert new_token != old_token
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_logout_revokes_current_session(client: TestClient):
    register = client.post(
        "/api/auth/register",
        json={"email": "logout@example.com", "password": "Logout!2345"},
    )
    token = register.json()["token"]

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})

    assert logout.status_code == 200
    assert logout.json()["ok"] is True
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_onboarding_sets_profile(client: TestClient, auth_headers):
    resp = client.post(
        "/api/onboarding",
        json={
            "preference": "growth",
            "riskAnswers": {"maxDrawdown": "30%"},
            "holdings": [
                {"symbol": "QQQ", "name": "Nasdaq ETF", "market": "us", "sector": "科技指数",
                 "shares": 100, "costPrice": 400.0},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preference"] == "growth"
    assert data["onboardingCompleted"] is True


def test_onboarding_requires_auth(client: TestClient):
    resp = client.post(
        "/api/onboarding",
        json={"preference": "balanced", "riskAnswers": {}, "holdings": []},
    )
    assert resp.status_code == 401


def test_api_key_not_stored_as_plaintext(client: TestClient, auth_headers, db_conn):
    resp = client.post(
        "/api/api-keys",
        json={"provider": "openai", "apiKey": "sk-test-1234567890"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    row = db_conn.execute("SELECT api_key FROM api_keys WHERE provider = 'openai'").fetchone()
    assert row is not None
    assert row["api_key"] != "sk-test-1234567890"
    assert row["api_key"].startswith("enc-v1:")


def test_plaintext_api_keys_are_migrated(db_conn):
    import backend.app as app_module

    db_conn.execute(
        "INSERT INTO api_keys(user_id, provider, api_key, updated_at) VALUES (1, 'legacy', 'plaintext-value', '2026-07-01T00:00:00Z')"
    )
    db_conn.commit()
    migrated = app_module.migrate_plaintext_secrets(connect=app_module.connect, encrypt_value=app_module.encrypt_secret)
    assert migrated >= 1
    row = db_conn.execute("SELECT api_key FROM api_keys WHERE provider = 'legacy'").fetchone()
    assert row is not None
    assert row["api_key"].startswith("enc-v1:")
