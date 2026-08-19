from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from investment_research.api.artifact_security import validate_agent_api_settings, validate_artifact_access_settings
from investment_research.api.auth_routes import router as auth_router
from investment_research.api.routes import router
from investment_research.api.agent_routes import router as agent_router
from investment_research.api.workbuddy_routes import router as workbuddy_router
from investment_research.api.security_middleware import BasicRateLimiter, allowed_origins, security_headers
from investment_research.public_demo import competition_mode_enabled
from investment_research.auth.security import validate_auth_settings
from investment_research.bootstrap.settings import validate_runtime_storage
from investment_research.service.scheduling import LocalResearchScheduler
from investment_research.config import env_flag


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
        # Keep long-running collection/training workers out of the API
        # process. Deploy ``scripts/run_research_worker.py`` separately; the
        # legacy in-process mode remains opt-in for local compatibility.
        scheduler_enabled = env_flag("INVESTMENT_RESEARCH_SCHEDULER_ENABLED", False)
        if scheduler_enabled:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler_enabled:
                scheduler.shutdown()

    app = FastAPI(title="Investment Research Console", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        # Permit any localhost frontend port so the workbench runs whether the
        # vite dev server lands on :5173, :5174 (after a conflict), a preview
        # server, or any local static origin. Explicit origins above still
        # apply for non-localhost production deployments.
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization", "content-type", "x-csrf-token",
        ],
    )
    app.middleware("http")(BasicRateLimiter())
    app.middleware("http")(security_headers)
    app.include_router(router)
    if not competition_mode_enabled():
        app.include_router(auth_router)
    app.include_router(agent_router)
    if not competition_mode_enabled():
        app.include_router(workbuddy_router)
    _attach_static_workbench(app)
    return app


def _attach_static_workbench(app: FastAPI) -> None:
    """Serve a built Workbench from the API process when explicitly configured.

    Vite remains the local development server. A single same-origin process is
    safer and simpler for a public Render demo because browser API calls keep
    their relative ``/api`` URLs and cookies do not cross origins.
    """
    import os

    configured_path = os.getenv("INVESTMENT_RESEARCH_STATIC_DIR")
    if not configured_path:
        return
    static_dir = Path(configured_path).expanduser().resolve()
    index_file = static_dir / "index.html"
    if not index_file.is_file():
        raise RuntimeError(
            f"INVESTMENT_RESEARCH_STATIC_DIR does not contain index.html: {static_dir}"
        )

    @app.get("/{workbench_path:path}", include_in_schema=False)
    async def serve_workbench(workbench_path: str):
        if workbench_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        requested = (static_dir / workbench_path).resolve()
        if workbench_path and requested.is_file() and static_dir in requested.parents:
            return FileResponse(requested)
        return FileResponse(index_file)
