from pathlib import Path

from investment_research.auth.security import AuthSettings
from investment_research.config import AppEnvironment
from investment_research.config import get_app_settings
from investment_research.config import redact_sensitive_value
from investment_research.config import resolve_app_environment
from investment_research.bootstrap.settings import validate_runtime_storage
from investment_research.service.credential_vault import credential_vault_settings_summary
from investment_research.service.credential_vault import get_credential_vault_settings


def test_app_settings_support_explicit_demo_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INVESTMENT_RESEARCH_ENV", "demo")
    monkeypatch.setenv("INVESTMENT_RESEARCH_DATABASE_PATH", str(tmp_path / "demo.db"))

    settings = get_app_settings()

    assert resolve_app_environment() == AppEnvironment.DEMO
    assert settings.environment == AppEnvironment.DEMO
    assert settings.allow_insecure_defaults is True
    assert settings.database_path == Path(tmp_path / "demo.db")


def test_auth_settings_require_secret_in_production(monkeypatch) -> None:
    monkeypatch.setenv("INVESTMENT_RESEARCH_ENV", "production")
    monkeypatch.delenv("INVESTMENT_RESEARCH_SECRET_KEY", raising=False)

    try:
        AuthSettings()
    except RuntimeError as exc:
        assert "SECRET_KEY" in str(exc)
    else:
        raise AssertionError("Expected AuthSettings to reject missing production secret")


def test_credential_vault_summary_redacts_master_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INVESTMENT_RESEARCH_ENV", "development")
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY", "top-secret-key")
    monkeypatch.setenv("AI_TEST_OFFICER_CREDENTIAL_STORE_PATH", str(tmp_path / "credentials.json"))

    settings = get_credential_vault_settings()
    summary = credential_vault_settings_summary(settings)

    assert summary["store_path"] == str(tmp_path / "credentials.json")
    assert str(summary["master_key_preview"]).startswith("***")
    assert "top-secret-key" not in str(summary["master_key_preview"])


def test_redact_sensitive_value_masks_full_secret() -> None:
    assert redact_sensitive_value("abcdefghijklmnop") == "***mnop"
    assert redact_sensitive_value(None) == "<unset>"


def test_production_requires_postgres_and_object_store(monkeypatch) -> None:
    monkeypatch.setenv("INVESTMENT_RESEARCH_ENV", "production")
    monkeypatch.setenv("INVESTMENT_RESEARCH_DATABASE_URL", "sqlite:///tmp/not-production.db")
    monkeypatch.delenv("INVESTMENT_RESEARCH_OBJECT_STORE_ENDPOINT", raising=False)

    try:
        validate_runtime_storage()
    except RuntimeError as exc:
        assert "PostgreSQL" in str(exc)
    else:
        raise AssertionError("Expected production storage validation to fail")

    monkeypatch.setenv("INVESTMENT_RESEARCH_DATABASE_URL", "postgresql://user:pass@localhost/research")
    monkeypatch.setenv("INVESTMENT_RESEARCH_OBJECT_STORE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("INVESTMENT_RESEARCH_MARKET_DATA_PRIMARY_PROVIDER", "licensed-primary")
    monkeypatch.setenv("INVESTMENT_RESEARCH_MARKET_DATA_BACKUP_PROVIDER", "licensed-backup")
    assert validate_runtime_storage().database_url.startswith("postgresql://")


def test_production_rejects_akshare_as_authority(monkeypatch) -> None:
    monkeypatch.setenv("INVESTMENT_RESEARCH_ENV", "production")
    monkeypatch.setenv("INVESTMENT_RESEARCH_DATABASE_URL", "postgresql://user:pass@localhost/research")
    monkeypatch.setenv("INVESTMENT_RESEARCH_OBJECT_STORE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("INVESTMENT_RESEARCH_MARKET_DATA_PRIMARY_PROVIDER", "akshare")
    monkeypatch.setenv("INVESTMENT_RESEARCH_MARKET_DATA_BACKUP_PROVIDER", "licensed-backup")
    try:
        validate_runtime_storage()
    except RuntimeError as exc:
        assert "AKShare" in str(exc)
    else:
        raise AssertionError("Expected AKShare production authority to be rejected")
