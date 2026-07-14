from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from investment_research.api.artifact_security import validate_agent_api_settings, validate_artifact_access_settings
from investment_research.api.auth_routes import router as auth_router
from investment_research.api.credential_routes import router as credential_router
from investment_research.api.routes import router
from investment_research.api.run_bundle_routes import router as run_bundle_router
from investment_research.api.agent_routes import router as agent_router
from investment_research.api.security_middleware import BasicRateLimiter, allowed_origins, security_headers
from investment_research.auth.security import validate_auth_settings
from investment_research.bootstrap.settings import validate_runtime_storage
from investment_research.service.credential_vault import validate_credential_vault_settings
from investment_research.service.scheduling import LocalResearchScheduler


def create_app() -> FastAPI:
    scheduler = LocalResearchScheduler()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = validate_runtime_storage()
        app.state.environment = settings.environment.value
        app.state.redact_sensitive_logs = settings.redact_sensitive_logs
        validate_auth_settings()
        validate_agent_api_settings()
        validate_artifact_access_settings()
        validate_credential_vault_settings()
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown()

    app = FastAPI(title="Investment Research Console", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization", "content-type", "x-csrf-token", "x-test-officer-token",
            "x-test-officer-run-token", "x-test-officer-project-token",
        ],
    )
    app.middleware("http")(BasicRateLimiter())
    app.middleware("http")(security_headers)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(run_bundle_router)
    app.include_router(credential_router)
    app.include_router(agent_router)
    return app
