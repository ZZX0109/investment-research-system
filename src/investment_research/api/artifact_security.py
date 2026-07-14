from __future__ import annotations

import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

ProjectRole = str
_PROJECT_ROLE_ORDER: dict[ProjectRole, int] = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
}


@dataclass(frozen=True)
class ArtifactAccessSettings:
    token: str | None
    agent_api_token: str | None
    dev_mode: bool
    environment: str | None
    signed_url_ttl_seconds: int


def get_artifact_access_settings() -> ArtifactAccessSettings:
    environment = os.getenv("NODE_ENV") or os.getenv("ENVIRONMENT")
    agent_api_token = os.getenv("AGENT_API_TOKEN")
    token = os.getenv("AI_TEST_OFFICER_ARTIFACT_TOKEN") or agent_api_token
    return ArtifactAccessSettings(
        token=token,
        agent_api_token=agent_api_token,
        dev_mode=environment == "development",
        environment=environment,
        signed_url_ttl_seconds=int(os.getenv("AI_TEST_OFFICER_SIGNED_URL_TTL_SECONDS", "900")),
    )


def validate_agent_api_settings(settings: ArtifactAccessSettings | None = None) -> None:
    resolved = settings or get_artifact_access_settings()
    if resolved.agent_api_token is None and not resolved.dev_mode:
        raise RuntimeError(
            "AGENT_API_TOKEN is required unless NODE_ENV=development is explicit"
        )


def validate_artifact_access_settings(settings: ArtifactAccessSettings | None = None) -> None:
    resolved = settings or get_artifact_access_settings()
    if resolved.token is None and not resolved.dev_mode:
        raise RuntimeError(
            "AI_TEST_OFFICER_ARTIFACT_TOKEN or AGENT_API_TOKEN is required unless NODE_ENV=development is explicit"
        )


def require_agent_api_access(
    request: Request,
    settings: ArtifactAccessSettings | None = None,
) -> None:
    resolved = settings or get_artifact_access_settings()
    if _has_valid_agent_token(request, resolved):
        return
    if _resolve_agent_token_for_request(request, resolved) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AGENT_API_TOKEN is required outside local development",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Agent API token is missing or invalid",
    )


def require_run_access(
    request: Request,
    run_id: str,
    settings: ArtifactAccessSettings | None = None,
) -> None:
    resolved = settings or get_artifact_access_settings()
    if _has_valid_agent_token(request, resolved) or _has_valid_run_token(request, run_id, resolved):
        return

    if (
        _resolve_agent_token_for_request(request, resolved) is None
        and _resolve_signing_token_for_request(request, resolved) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Run access requires AGENT_API_TOKEN, artifact signing token, or loopback local development",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Run access token is missing, invalid, expired, or scoped to another run",
    )


def require_project_access(
    request: Request,
    project_id: str,
    *,
    min_role: ProjectRole = "viewer",
    settings: ArtifactAccessSettings | None = None,
) -> None:
    resolved = settings or get_artifact_access_settings()
    if _has_valid_agent_token(request, resolved) or _has_valid_project_token(
        request,
        project_id,
        min_role=min_role,
        settings=resolved,
    ):
        return

    if (
        _resolve_agent_token_for_request(request, resolved) is None
        and _resolve_signing_token_for_request(request, resolved) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project access requires AGENT_API_TOKEN, artifact signing token, or loopback local development",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Project access token is missing, invalid, expired, scoped to another project, or below the required role",
    )


def require_artifact_access(
    request: Request,
    run_id: str | None = None,
    settings: ArtifactAccessSettings | None = None,
) -> None:
    resolved = settings or get_artifact_access_settings()
    if _has_valid_signature(request, resolved):
        return
    if run_id and (_has_valid_agent_token(request, resolved) or _has_valid_run_token(request, run_id, resolved)):
        return

    expected_token = _resolve_artifact_token_for_request(request, resolved)

    if expected_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI_TEST_OFFICER_ARTIFACT_TOKEN, AGENT_API_TOKEN, or loopback local development is required",
        )

    provided = _extract_token(request)
    if provided is None or not secrets.compare_digest(provided, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Artifact access token is missing or invalid",
        )


def require_report_access(
    request: Request,
    report_name: str,
    run_id: str,
    settings: ArtifactAccessSettings | None = None,
) -> None:
    resolved = settings or get_artifact_access_settings()
    if _report_requires_agent_token(report_name):
        require_agent_api_access(request, resolved)
        return
    require_artifact_access(request, run_id=run_id, settings=resolved)


def build_signed_artifact_url(
    path: str,
    *,
    now: int | None = None,
    settings: ArtifactAccessSettings | None = None,
) -> str:
    resolved = settings or get_artifact_access_settings()
    signing_token = _resolve_signing_token(resolved)
    if signing_token is None:
        return path
    expires = (now if now is not None else int(time.time())) + resolved.signed_url_ttl_seconds
    signature = _sign_path(path, expires, signing_token)
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}expires={expires}&signature={signature}"


def build_run_access_token(
    run_id: str,
    *,
    now: int | None = None,
    settings: ArtifactAccessSettings | None = None,
) -> str | None:
    resolved = settings or get_artifact_access_settings()
    signing_token = _resolve_signing_token(resolved)
    if signing_token is None:
        return None
    expires = (now if now is not None else int(time.time())) + resolved.signed_url_ttl_seconds
    encoded_run_id = _base64_url_encode(run_id)
    signature = _sign_run_token(run_id, expires, signing_token)
    return f"run-v1.{encoded_run_id}.{expires}.{signature}"


def build_project_access_token(
    project_id: str,
    *,
    role: ProjectRole = "viewer",
    now: int | None = None,
    settings: ArtifactAccessSettings | None = None,
) -> str | None:
    resolved = settings or get_artifact_access_settings()
    signing_token = _resolve_signing_token(resolved)
    if signing_token is None:
        return None
    if role not in _PROJECT_ROLE_ORDER:
        raise ValueError(f"Unsupported project role: {role}")
    expires = (now if now is not None else int(time.time())) + resolved.signed_url_ttl_seconds
    encoded_project_id = _base64_url_encode(project_id)
    signature = _sign_project_token(project_id, role, expires, signing_token)
    return f"project-v1.{encoded_project_id}.{role}.{expires}.{signature}"


def _extract_token(request: Request) -> str | None:
    header_token = request.headers.get("x-test-officer-token")
    if header_token:
        return header_token

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    query_token = request.query_params.get("token")
    return query_token or None


def _extract_run_token(request: Request) -> str | None:
    header_token = request.headers.get("x-test-officer-run-token")
    if header_token:
        return header_token
    return request.query_params.get("run_token") or None


def _extract_project_token(request: Request) -> str | None:
    header_token = request.headers.get("x-test-officer-project-token")
    if header_token:
        return header_token
    return request.query_params.get("project_token") or None


def _has_valid_agent_token(request: Request, settings: ArtifactAccessSettings) -> bool:
    expected_token = _resolve_agent_token_for_request(request, settings)
    if expected_token is None:
        return False
    provided = _extract_token(request)
    return provided is not None and secrets.compare_digest(provided, expected_token)


def _has_valid_signature(request: Request, settings: ArtifactAccessSettings) -> bool:
    expires_raw = request.query_params.get("expires")
    signature = request.query_params.get("signature")
    signing_token = _resolve_signing_token_for_request(request, settings)
    if not expires_raw or not signature or signing_token is None:
        return False
    try:
        expires = int(expires_raw)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    expected = _sign_path(request.url.path, expires, signing_token)
    return compare_digest(signature, expected)


def _has_valid_run_token(request: Request, run_id: str, settings: ArtifactAccessSettings) -> bool:
    token = _extract_run_token(request)
    signing_token = _resolve_signing_token_for_request(request, settings)
    if not token or signing_token is None:
        return False
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "run-v1":
        return False
    try:
        token_run_id = _base64_url_decode(parts[1])
        expires = int(parts[2])
    except (ValueError, UnicodeDecodeError):
        return False
    if token_run_id != run_id or expires < int(time.time()):
        return False
    expected = _sign_run_token(token_run_id, expires, signing_token)
    return compare_digest(parts[3], expected)


def _has_valid_project_token(
    request: Request,
    project_id: str,
    *,
    min_role: ProjectRole,
    settings: ArtifactAccessSettings,
) -> bool:
    token = _extract_project_token(request)
    signing_token = _resolve_signing_token_for_request(request, settings)
    if not token or signing_token is None:
        return False
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != "project-v1":
        return False
    try:
        token_project_id = _base64_url_decode(parts[1])
        role = parts[2]
        expires = int(parts[3])
    except (ValueError, UnicodeDecodeError):
        return False
    if token_project_id != project_id or expires < int(time.time()):
        return False
    if _PROJECT_ROLE_ORDER.get(role, 0) < _PROJECT_ROLE_ORDER.get(min_role, 999):
        return False
    expected = _sign_project_token(token_project_id, role, expires, signing_token)
    return compare_digest(parts[4], expected)


def _sign_path(path: str, expires: int, token: str) -> str:
    message = f"{path}\n{expires}".encode("utf-8")
    return hmac_new(token.encode("utf-8"), message, sha256).hexdigest()


def _sign_run_token(run_id: str, expires: int, token: str) -> str:
    message = f"run-access\n{run_id}\n{expires}".encode("utf-8")
    return hmac_new(token.encode("utf-8"), message, sha256).hexdigest()


def _sign_project_token(project_id: str, role: ProjectRole, expires: int, token: str) -> str:
    message = f"project-access\n{project_id}\n{role}\n{expires}".encode("utf-8")
    return hmac_new(token.encode("utf-8"), message, sha256).hexdigest()


def _base64_url_encode(value: str) -> str:
    return urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _base64_url_decode(value: str) -> str:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    return urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def _resolve_agent_token_for_request(request: Request, settings: ArtifactAccessSettings) -> str | None:
    if settings.agent_api_token:
        return settings.agent_api_token
    if settings.dev_mode and _is_loopback_request(request):
        return "dev-local-token"
    return None


def _resolve_artifact_token_for_request(request: Request, settings: ArtifactAccessSettings) -> str | None:
    if settings.token:
        return settings.token
    if settings.dev_mode and _is_loopback_request(request):
        return "dev-local-token"
    return None


def _resolve_signing_token(settings: ArtifactAccessSettings) -> str | None:
    if settings.token:
        return settings.token
    if settings.dev_mode:
        return "dev-local-token"
    return None


def _resolve_signing_token_for_request(request: Request, settings: ArtifactAccessSettings) -> str | None:
    if settings.token:
        return settings.token
    if settings.dev_mode and _is_loopback_request(request):
        return "dev-local-token"
    return None


def should_sign_report_url(report_name: str) -> bool:
    return not _report_requires_agent_token(report_name)


def _report_requires_agent_token(report_name: str) -> bool:
    normalized = report_name.rsplit("/", maxsplit=1)[-1].lower()
    return normalized in {
        "run-report.json",
        "junit.xml",
        "comparison.json",
        "gate.json",
        "pr-annotation.md",
        "pr-annotations.json",
        "artifact-upload-manifest.json",
        "retention-job.json",
        "integrity-report.json",
        "download-manifest.json",
    }


def _is_loopback_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}
