from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Callable

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response

from .auth_service import (
    AuthRequest,
    authenticate_user,
    build_auth_payload,
    create_session,
    create_user_account,
    load_user_for_access_token,
    refresh_session,
    refresh_ttl_seconds,
    revoke_session,
    validate_auth_request,
)


def build_auth_router(
    *,
    connect: Callable[[], sqlite3.Connection],
    get_current_user: Callable[..., sqlite3.Row],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    public_user: Callable[[sqlite3.Row], dict[str, Any]],
    get_user_profile: Callable[[int], dict[str, Any]],
    user_api_key_summary: Callable[[int], list[dict[str, Any]]],
    data_mode_status: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["auth"])

    def with_source_meta(payload: dict[str, Any]) -> dict[str, Any]:
        mode = data_mode_status()
        return {**payload, "dataMode": mode, "sourceMeta": mode["sourceMeta"]}

    def set_refresh_cookie(response: Response, refresh_token: str) -> None:
        response.set_cookie(
            "investment_research_refresh",
            refresh_token,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=refresh_ttl_seconds(),
            path="/api/auth",
        )

    def clear_refresh_cookie(response: Response) -> None:
        response.delete_cookie("investment_research_refresh", path="/api/auth")

    def auth_response(user: sqlite3.Row, tokens: Any) -> dict[str, Any]:
        return with_source_meta({
            "token": tokens.access_token,
            "accessToken": tokens.access_token,
            "accessExpiresAt": tokens.access_expires_at,
            "refreshExpiresAt": tokens.refresh_expires_at,
            **build_auth_payload(
                user=user,
                get_user_profile=get_user_profile,
                public_user=public_user,
                user_api_key_summary=user_api_key_summary,
            )
        })

    def bearer_token(authorization: str | None) -> str | None:
        if authorization and authorization.startswith("Bearer "):
            return authorization.removeprefix("Bearer ").strip()
        return None

    @router.post("/api/auth/register")
    def register(request: AuthRequest, response: Response) -> dict[str, Any]:
        email = validate_auth_request(request, check_password_policy=True)
        created_at = iso(now_utc())
        try:
            user = create_user_account(connect=connect, email=email, password=request.password, created_at=created_at)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=400, detail="Email already registered.") from exc
        tokens = create_session(connect=connect, user_id=int(user["id"]), created_at=created_at)
        set_refresh_cookie(response, tokens.refresh_token)
        return auth_response(user, tokens)

    @router.post("/api/auth/login")
    def login(request: AuthRequest, response: Response) -> dict[str, Any]:
        email = validate_auth_request(request, check_password_policy=False)
        user = authenticate_user(connect=connect, email=email, password=request.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        tokens = create_session(connect=connect, user_id=int(user["id"]), created_at=iso(now_utc()))
        set_refresh_cookie(response, tokens.refresh_token)
        return auth_response(user, tokens)

    @router.post("/api/auth/refresh")
    def refresh(
        response: Response,
        refresh_token: str | None = Cookie(default=None, alias="investment_research_refresh"),
    ) -> dict[str, Any]:
        if not refresh_token:
            raise HTTPException(status_code=401, detail="Missing refresh token.")
        tokens = refresh_session(connect=connect, refresh_token=refresh_token, refreshed_at=iso(now_utc()))
        if not tokens:
            clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Refresh token expired or revoked.")
        user = load_user_for_access_token(connect=connect, token=tokens.access_token)
        if not user:
            clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Invalid refreshed session.")
        set_refresh_cookie(response, tokens.refresh_token)
        return auth_response(user, tokens)

    @router.post("/api/auth/logout")
    def logout(
        response: Response,
        authorization: str | None = Header(default=None),
        refresh_token: str | None = Cookie(default=None, alias="investment_research_refresh"),
    ) -> dict[str, Any]:
        revoke_session(
            connect=connect,
            token=bearer_token(authorization),
            refresh_token=refresh_token,
            revoked_at=iso(now_utc()),
        )
        clear_refresh_cookie(response)
        return with_source_meta({"ok": True})

    @router.get("/api/auth/me")
    def me(user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        return with_source_meta(build_auth_payload(
            user=user,
            get_user_profile=get_user_profile,
            public_user=public_user,
            user_api_key_summary=user_api_key_summary,
        ))

    return router
