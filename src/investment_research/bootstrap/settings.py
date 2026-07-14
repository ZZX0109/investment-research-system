from __future__ import annotations

from investment_research.config import AppEnvironment, AppSettings, get_app_settings


def validate_runtime_storage(settings: AppSettings | None = None) -> AppSettings:
    resolved = settings or get_app_settings()
    if resolved.environment == AppEnvironment.PRODUCTION:
        if not resolved.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("Production requires INVESTMENT_RESEARCH_DATABASE_URL with PostgreSQL")
        if not resolved.object_store_endpoint:
            raise RuntimeError("Production requires INVESTMENT_RESEARCH_OBJECT_STORE_ENDPOINT")
        if not resolved.market_data_primary_provider or not resolved.market_data_backup_provider:
            raise RuntimeError("Production requires primary and backup licensed market data providers")
        if "akshare" in {resolved.market_data_primary_provider.lower(), resolved.market_data_backup_provider.lower()}:
            raise RuntimeError("AKShare cannot be configured as a production market data authority")
    return resolved
