from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from investment_research.main import app
from investment_research.service.credential_models import CredentialSummaryResponse
from investment_research.service.credential_models import CredentialUpsertRequest
from investment_research.service.credential_vault import CredentialVault


def test_test_officer_credentials_are_token_protected_and_encrypted(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "credentials.json"
    raw_key = bytes([11]) * 32
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_STORE_PATH", str(store_path))
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY", base64.b64encode(raw_key).decode("ascii"))

    client = TestClient(app)
    unauthorized = client.get("/api/v1/test-officer/credentials")
    create_response = client.post(
        "/api/v1/test-officer/credentials",
        headers={"x-test-officer-token": "dev-local-token"},
        json={
            "id": "openai-default",
            "label": "OpenAI default key",
            "kind": "api-key",
            "secret": "sk-test-secret-123456",
            "metadata": {"provider": "openai"},
        },
    )
    list_response = client.get(
        "/api/v1/test-officer/credentials",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    raw_file = store_path.read_text(encoding="utf-8")
    delete_response = client.delete(
        "/api/v1/test-officer/credentials/openai-default",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    empty_list_response = client.get(
        "/api/v1/test-officer/credentials",
        headers={"x-test-officer-token": "dev-local-token"},
    )

    assert unauthorized.status_code == 401
    assert create_response.status_code == 201
    assert create_response.json() == {
        "id": "openai-default",
        "label": "OpenAI default key",
        "kind": "api-key",
        "username": None,
        "metadata": {"provider": "openai"},
        "createdAt": create_response.json()["createdAt"],
        "updatedAt": create_response.json()["updatedAt"],
        "secretPreview": "****3456",
        "secretLength": 21,
    }
    assert "secret" not in create_response.json()
    assert list_response.status_code == 200
    assert list_response.json()[0]["secretPreview"] == "****3456"
    assert "sk-test-secret-123456" not in raw_file
    assert "\"ciphertext\"" in raw_file
    assert delete_response.status_code == 204
    assert empty_list_response.status_code == 200
    assert empty_list_response.json() == []


def test_test_officer_credentials_fail_closed_on_invalid_store(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "credentials.json"
    store_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_STORE_PATH", str(store_path))
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY", base64.b64encode(bytes([12]) * 32).decode("ascii"))

    client = TestClient(app)
    response = client.get(
        "/api/v1/test-officer/credentials",
        headers={"x-test-officer-token": "dev-local-token"},
    )

    assert response.status_code == 400
    assert "Credential vault read failed" in response.json()["detail"]


def test_test_officer_credentials_reject_unknown_fields(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "credentials.json"
    raw_key = bytes([13]) * 32
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_STORE_PATH", str(store_path))
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY", base64.b64encode(raw_key).decode("ascii"))

    client = TestClient(app)
    response = client.post(
        "/api/v1/test-officer/credentials",
        headers={"x-test-officer-token": "dev-local-token"},
        json={
            "id": "openai-default",
            "label": "OpenAI default key",
            "kind": "api-key",
            "secret": "sk-test-secret-123456",
            "metadata": {"provider": "openai"},
            "unexpected": "nope",
        },
    )

    assert response.status_code == 422


def test_credential_vault_returns_typed_summaries(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "credentials.json"
    raw_key = bytes([14]) * 32
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_STORE_PATH", str(store_path))
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY", base64.b64encode(raw_key).decode("ascii"))

    vault = CredentialVault()
    summary = vault.upsert_credential(
        CredentialUpsertRequest.model_validate(
            {
                "id": "openai-default",
                "label": "OpenAI default key",
                "kind": "api-key",
                "secret": "sk-test-secret-123456",
                "metadata": {"provider": "openai"},
            }
        )
    )
    listing = vault.list_credentials()

    assert isinstance(summary, CredentialSummaryResponse)
    assert summary.secretPreview == "****3456"
    assert isinstance(listing[0], CredentialSummaryResponse)
    assert listing[0].id == "openai-default"
