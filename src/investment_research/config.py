from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    DEMO = "demo"
    TEST = "test"
    PRODUCTION = "production"


def _normalized_env_name() -> str:
    return (
        os.getenv("INVESTMENT_RESEARCH_ENV")
        or os.getenv("APP_ENV")
        or os.getenv("NODE_ENV")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip().lower()


def resolve_app_environment() -> AppEnvironment:
    value = _normalized_env_name()
    aliases = {
        "dev": AppEnvironment.DEVELOPMENT,
        "development": AppEnvironment.DEVELOPMENT,
        "demo": AppEnvironment.DEMO,
        "test": AppEnvironment.TEST,
        "testing": AppEnvironment.TEST,
        "prod": AppEnvironment.PRODUCTION,
        "production": AppEnvironment.PRODUCTION,
    }
    return aliases.get(value, AppEnvironment.DEVELOPMENT)


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return max(minimum, default)
    try:
        parsed = int(raw)
    except ValueError:
        return max(minimum, default)
    return parsed if parsed >= minimum else max(minimum, default)


def env_csv(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    parts = [part.strip() for part in value.split(",")]
    return [part for part in parts if part]


def redact_sensitive_value(value: str | None, *, visible: int = 4) -> str:
    if not value:
        return "<unset>"
    suffix = value[-visible:] if len(value) > visible else value
    return f"***{suffix}"


@dataclass(frozen=True)
class AppSettings:
    environment: AppEnvironment
    allow_insecure_defaults: bool
    database_path: Path
    database_url: str
    object_store_endpoint: str | None
    object_store_bucket: str
    log_level: str
    redact_sensitive_logs: bool
    market_data_primary_provider: str | None = None
    market_data_backup_provider: str | None = None
    minute_collection_enabled: bool = False


def get_app_settings() -> AppSettings:
    environment = resolve_app_environment()
    default_database = Path.cwd() / "var" / "investment_research.db"
    database_url = os.getenv("INVESTMENT_RESEARCH_DATABASE_URL", f"sqlite:///{default_database}")
    return AppSettings(
        environment=environment,
        allow_insecure_defaults=environment in {
            AppEnvironment.DEVELOPMENT,
            AppEnvironment.DEMO,
            AppEnvironment.TEST,
        },
        database_path=Path(os.getenv("INVESTMENT_RESEARCH_DATABASE_PATH", str(default_database))),
        database_url=database_url,
        object_store_endpoint=os.getenv("INVESTMENT_RESEARCH_OBJECT_STORE_ENDPOINT") or None,
        object_store_bucket=os.getenv("INVESTMENT_RESEARCH_OBJECT_STORE_BUCKET", "investment-research"),
        log_level=os.getenv("INVESTMENT_RESEARCH_LOG_LEVEL", "INFO").upper(),
        redact_sensitive_logs=env_flag("INVESTMENT_RESEARCH_REDACT_SENSITIVE_LOGS", True),
        market_data_primary_provider=os.getenv("INVESTMENT_RESEARCH_MARKET_DATA_PRIMARY_PROVIDER") or None,
        market_data_backup_provider=os.getenv("INVESTMENT_RESEARCH_MARKET_DATA_BACKUP_PROVIDER") or None,
        minute_collection_enabled=env_flag("INVESTMENT_RESEARCH_MINUTE_COLLECTION_ENABLED", False),
    )
