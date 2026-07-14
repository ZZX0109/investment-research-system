import jwt
from fastapi.testclient import TestClient

from investment_research.api.auth_routes import get_auth_service, get_auth_settings
from investment_research.auth.security import AuthSettings, TokenClaims, decode_token, validate_auth_settings
from investment_research.main import app
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.auth.service import AuthService


def _csrf_headers(client: TestClient, settings: AuthSettings) -> dict[str, str]:
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert csrf_token is not None
    return {settings.csrf_header_name: csrf_token}


def test_register_login_refresh_and_me_flow(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / "auth.db"), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "display_name": "Alice",
            "password": "supersecret123",
        },
    )
    me_response = client.get("/api/v1/auth/me")
    refresh_response = client.post("/api/v1/auth/refresh", headers=_csrf_headers(client, settings))

    app.dependency_overrides.clear()

    assert register_response.status_code == 201
    assert register_response.json()["user"]["email"] == "alice@example.com"
    assert settings.access_cookie_name in register_response.cookies
    assert settings.refresh_cookie_name in register_response.cookies
    assert settings.csrf_cookie_name in register_response.cookies
    assert me_response.status_code == 200
    assert me_response.json()["display_name"] == "Alice"
    assert refresh_response.status_code == 200
    assert refresh_response.json()["user"]["email"] == "alice@example.com"


def test_login_rejects_invalid_password(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / "invalid.db"), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "bob@example.com",
            "display_name": "Bob",
            "password": "correcthorse1",
        },
    )
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "bob@example.com",
            "password": "wrongpass999",
        },
    )

    app.dependency_overrides.clear()

    assert login_response.status_code == 401


def test_refresh_requires_matching_csrf_token(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / "csrf.db"), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf@example.com",
            "display_name": "CSRF User",
            "password": "supersecret123",
        },
    )
    refresh_response = client.post("/api/v1/auth/refresh")
    invalid_response = client.post("/api/v1/auth/refresh", headers={settings.csrf_header_name: "wrong-token"})

    app.dependency_overrides.clear()

    assert refresh_response.status_code == 403
    assert invalid_response.status_code == 403


def test_refresh_rejects_csrf_pair_not_bound_to_refresh_token(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    database_path = tmp_path / "csrf-bound-refresh.db"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(database_path), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf-bound@example.com",
            "display_name": "CSRF Bound User",
            "password": "supersecret123",
        },
    )
    refresh_token = client.cookies.get(settings.refresh_cookie_name)
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert refresh_token is not None
    assert csrf_token is not None

    forged_client = TestClient(app)
    forged_client.cookies.set(settings.refresh_cookie_name, refresh_token)
    forged_client.cookies.set(settings.csrf_cookie_name, "forged-csrf-token")
    forged_response = forged_client.post(
        "/api/v1/auth/refresh",
        headers={settings.csrf_header_name: "forged-csrf-token"},
    )
    valid_response = client.post(
        "/api/v1/auth/refresh",
        headers={settings.csrf_header_name: csrf_token},
    )

    app.dependency_overrides.clear()

    assert forged_response.status_code == 403
    assert forged_response.json()["detail"] == "Invalid CSRF token"
    assert valid_response.status_code == 200


def test_logout_rejects_csrf_pair_not_bound_to_refresh_token(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    database_path = tmp_path / "csrf-bound-logout.db"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(database_path), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    client.post(
        "/api/v1/auth/register",
        json={
            "email": "csrf-logout@example.com",
            "display_name": "CSRF Logout User",
            "password": "supersecret123",
        },
    )
    refresh_token = client.cookies.get(settings.refresh_cookie_name)
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert refresh_token is not None
    assert csrf_token is not None

    forged_client = TestClient(app)
    forged_client.cookies.set(settings.refresh_cookie_name, refresh_token)
    forged_client.cookies.set(settings.csrf_cookie_name, "forged-csrf-token")
    forged_response = forged_client.post(
        "/api/v1/auth/logout",
        headers={settings.csrf_header_name: "forged-csrf-token"},
    )
    valid_response = client.post(
        "/api/v1/auth/logout",
        headers={settings.csrf_header_name: csrf_token},
    )

    app.dependency_overrides.clear()

    assert forged_response.status_code == 403
    assert forged_response.json()["detail"] == "Invalid CSRF token"
    assert valid_response.status_code == 204


def test_auth_cookies_respect_security_settings(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "test-secret-key-with-32-bytes-minimum"
    settings.cookie_secure = True
    settings.cookie_samesite = "strict"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(tmp_path / "secure-cookies.db"), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "cookie@example.com",
            "display_name": "Cookie User",
            "password": "supersecret123",
        },
    )

    app.dependency_overrides.clear()

    set_cookie_headers = register_response.headers.get_list("set-cookie")
    assert any(f"{settings.access_cookie_name}=" in header and "HttpOnly" in header and "Secure" in header for header in set_cookie_headers)
    assert any(f"{settings.refresh_cookie_name}=" in header and "SameSite=strict" in header for header in set_cookie_headers)
    assert any(f"{settings.csrf_cookie_name}=" in header and "HttpOnly" not in header and "Secure" in header for header in set_cookie_headers)


def test_auth_secret_rotation_accepts_previous_tokens_but_signs_new_tokens_with_current_secret(tmp_path) -> None:
    settings = AuthSettings()
    settings.secret_key = "old-secret-key-with-32-bytes-minimum"
    settings.previous_secret_keys = []
    database_path = tmp_path / "rotated-secrets.db"

    def override_settings() -> AuthSettings:
        return settings

    def override_service() -> AuthService:
        return AuthService(SQLiteUnitOfWork(database_path), settings=settings)

    app.dependency_overrides[get_auth_settings] = override_settings
    app.dependency_overrides[get_auth_service] = override_service
    client = TestClient(app)

    register_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "rotate@example.com",
            "display_name": "Rotate User",
            "password": "supersecret123",
        },
    )
    old_access_token = client.cookies.get(settings.access_cookie_name)

    settings.secret_key = "new-secret-key-with-32-bytes-minimum"
    settings.previous_secret_keys = ["old-secret-key-with-32-bytes-minimum"]
    me_with_old_token = client.get("/api/v1/auth/me")
    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "rotate@example.com",
            "password": "supersecret123",
        },
    )
    new_access_token = client.cookies.get(settings.access_cookie_name)

    old_only_settings = AuthSettings()
    old_only_settings.secret_key = "old-secret-key-with-32-bytes-minimum"
    old_only_settings.previous_secret_keys = []

    app.dependency_overrides.clear()

    assert register_response.status_code == 201
    assert old_access_token is not None
    assert me_with_old_token.status_code == 200
    assert me_with_old_token.json()["email"] == "rotate@example.com"
    assert login_response.status_code == 200
    assert new_access_token is not None
    assert new_access_token != old_access_token
    decoded = decode_token(new_access_token, settings)
    assert isinstance(decoded, TokenClaims)
    assert decoded.type == "access"
    assert decoded["type"] == "access"
    try:
        decode_token(new_access_token, old_only_settings)
    except jwt.PyJWTError:
        pass
    else:
        raise AssertionError("Expected newly issued token to reject the old signing secret")


def test_auth_settings_fail_closed_outside_development_without_secret(monkeypatch) -> None:
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.delenv("INVESTMENT_RESEARCH_SECRET_KEY", raising=False)

    try:
        AuthSettings()
    except RuntimeError as exc:
        assert "INVESTMENT_RESEARCH_SECRET_KEY is required" in str(exc)
    else:
        raise AssertionError("Expected production auth settings without secret to fail")


def test_auth_settings_reject_insecure_none_samesite(monkeypatch) -> None:
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("INVESTMENT_RESEARCH_COOKIE_SAMESITE", "none")
    monkeypatch.setenv("INVESTMENT_RESEARCH_COOKIE_SECURE", "false")

    try:
        validate_auth_settings(AuthSettings())
        raise AssertionError("Expected invalid SameSite=None settings to be rejected")
    except RuntimeError:
        pass


def test_auth_settings_reject_previous_secret_matching_active_secret() -> None:
    settings = AuthSettings()
    settings.secret_key = "active-secret-key-with-32-bytes-minimum"
    settings.previous_secret_keys = ["previous-secret-key-with-32-bytes-minimum", settings.secret_key]

    try:
        validate_auth_settings(settings)
        raise AssertionError("Expected duplicate active/previous auth secret to be rejected")
    except RuntimeError as exc:
        assert "must not include the active secret" in str(exc)


def test_auth_settings_reject_short_hmac_secret() -> None:
    settings = AuthSettings()
    settings.secret_key = "too-short"

    try:
        validate_auth_settings(settings)
        raise AssertionError("Expected a short HS256 secret to be rejected")
    except RuntimeError as exc:
        assert "at least 32 bytes" in str(exc)
