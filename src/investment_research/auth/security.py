from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from pydantic import BaseModel, ConfigDict, Field

from investment_research.config import get_app_settings
from investment_research.config import env_flag


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthSettings:
    def __init__(self) -> None:
        app_settings = get_app_settings()
        self.environment = app_settings.environment.value
        self.dev_mode = app_settings.allow_insecure_defaults
        configured_secret = os.getenv("INVESTMENT_RESEARCH_SECRET_KEY")
        if configured_secret is None and not self.dev_mode:
            raise RuntimeError(
                "INVESTMENT_RESEARCH_SECRET_KEY is required unless INVESTMENT_RESEARCH_ENV is development, demo, or test"
            )
        self.secret_key = configured_secret or "workbuddy-development-secret-key-change-me"
        self.previous_secret_keys = _parse_previous_secret_keys()
        self.access_ttl_minutes = int(os.getenv("INVESTMENT_RESEARCH_ACCESS_TTL_MINUTES", "15"))
        self.refresh_ttl_days = int(os.getenv("INVESTMENT_RESEARCH_REFRESH_TTL_DAYS", "14"))
        self.algorithm = "HS256"
        self.access_cookie_name = "airc_access_token"
        self.refresh_cookie_name = "airc_refresh_token"
        self.csrf_cookie_name = "airc_csrf_token"
        self.csrf_header_name = "x-csrf-token"
        self.cookie_secure = env_flag("INVESTMENT_RESEARCH_COOKIE_SECURE", not self.dev_mode)
        self.cookie_samesite = os.getenv("INVESTMENT_RESEARCH_COOKIE_SAMESITE", "lax").lower()
        self.cookie_domain = os.getenv("INVESTMENT_RESEARCH_COOKIE_DOMAIN") or None
        self.cookie_path = os.getenv("INVESTMENT_RESEARCH_COOKIE_PATH", "/")


class TokenExtraClaims(BaseModel):
    model_config = ConfigDict(extra="allow")

    csrf: str | None = None


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub: str = Field(min_length=1)
    type: str = Field(min_length=1)
    jti: str = Field(min_length=1)
    iat: int
    exp: int
    csrf: str | None = None

    def __getitem__(self, key: str):
        value = self.model_dump().get(key)
        if key not in self.model_dump():
            raise KeyError(key)
        return value

    def get(self, key: str, default=None):
        return self.model_dump().get(key, default)


def validate_auth_settings(settings: AuthSettings | None = None) -> None:
    resolved = settings or AuthSettings()
    if not resolved.secret_key:
        raise RuntimeError("Auth secret key is empty")
    if len(resolved.secret_key.encode("utf-8")) < 32:
        raise RuntimeError("INVESTMENT_RESEARCH_SECRET_KEY must be at least 32 bytes")
    if any(key == resolved.secret_key for key in resolved.previous_secret_keys):
        raise RuntimeError("Previous auth secret keys must not include the active secret key")
    if resolved.cookie_samesite not in {"lax", "strict", "none"}:
        raise RuntimeError("INVESTMENT_RESEARCH_COOKIE_SAMESITE must be lax, strict, or none")
    if resolved.cookie_samesite == "none" and not resolved.cookie_secure:
        raise RuntimeError("SameSite=None requires secure auth cookies")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def create_token(
    *,
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    settings: AuthSettings,
    extra_claims: TokenExtraClaims | None = None,
) -> tuple[str, datetime, str]:
    issued_at = utc_now()
    expires_at = issued_at + expires_delta
    token_id = secrets.token_urlsafe(18)
    payload = TokenClaims(
        sub=subject,
        type=token_type,
        jti=token_id,
        iat=int(issued_at.timestamp()),
        exp=int(expires_at.timestamp()),
        **(extra_claims.model_dump(exclude_none=True) if extra_claims else {}),
    ).model_dump(exclude_none=True)
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, expires_at, token_id


def decode_token(token: str, settings: AuthSettings) -> TokenClaims:
    last_error: jwt.PyJWTError | None = None
    for secret_key in [settings.secret_key, *settings.previous_secret_keys]:
        try:
            return TokenClaims.model_validate(jwt.decode(token, secret_key, algorithms=[settings.algorithm]))
        except jwt.PyJWTError as exc:
            last_error = exc
    raise last_error or jwt.InvalidTokenError("Invalid token")


def _parse_previous_secret_keys() -> list[str]:
    raw_value = os.getenv("INVESTMENT_RESEARCH_PREVIOUS_SECRET_KEYS", "")
    keys: list[str] = []
    for value in raw_value.replace("\n", ",").split(","):
        key = value.strip()
        if key and key not in keys:
            keys.append(key)
    return keys
