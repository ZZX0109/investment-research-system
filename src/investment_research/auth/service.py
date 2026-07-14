from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import jwt

from investment_research.auth.models import AuthenticatedUser, RefreshSession
from investment_research.auth.refresh_sessions import RefreshSessionService
from investment_research.auth.schemas import AuthResponse, LoginRequest, RegisterRequest, TokenBundle
from investment_research.auth.security import (
    AuthSettings,
    TokenClaims,
    TokenExtraClaims,
    create_token,
    decode_token,
    generate_csrf_token,
    hash_password,
    utc_now,
    verify_password,
)
from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork


class AuthenticationError(Exception):
    pass


class CsrfValidationError(AuthenticationError):
    pass


class AuthService:
    def __init__(self, uow: SQLiteUnitOfWork, settings: AuthSettings | None = None) -> None:
        self.uow = uow
        self.settings = settings or AuthSettings()
        self.refresh_sessions = RefreshSessionService(self.uow.refresh_sessions)

    def register(self, payload: RegisterRequest) -> tuple[AuthResponse, TokenBundle]:
        try:
            existing = self.uow.users.get_by_email(str(payload.email).lower())
            if existing is not None:
                raise AuthenticationError("User already exists")

            user = User(
                email=str(payload.email).lower(),
                display_name=payload.display_name,
                auth_subject=f"user:{uuid4()}",
                provenance=Provenance(
                    data_mode=DataMode.REAL,
                    source_type=DataSourceType.MANUAL_OVERRIDE,
                    source_name="auth-registration",
                    observed_at=utc_now(),
                    confidence=1.0,
                ),
            )
            self.uow.users.add(user, password_hash=hash_password(payload.password))
            tokens = self._issue_tokens(user)
            return self._build_response(user, tokens), tokens
        finally:
            self.uow.close()

    def login(self, payload: LoginRequest) -> tuple[AuthResponse, TokenBundle]:
        try:
            auth_user = self.uow.users.get_by_email(str(payload.email).lower())
            if auth_user is None or not verify_password(payload.password, auth_user.password_hash):
                raise AuthenticationError("Invalid email or password")
            tokens = self._issue_tokens(auth_user.user)
            return self._build_response(auth_user.user, tokens), tokens
        finally:
            self.uow.close()

    def refresh(self, refresh_token: str, *, expected_csrf: str | None = None) -> tuple[AuthResponse, TokenBundle]:
        try:
            try:
                payload = decode_token(refresh_token, self.settings)
            except jwt.PyJWTError as exc:
                raise AuthenticationError("Invalid refresh token") from exc
            if payload.type != "refresh":
                raise AuthenticationError("Invalid refresh token")
            self._require_bound_csrf(payload, expected_csrf)
            session = self.refresh_sessions.get_active(payload.jti)
            if session is None:
                raise AuthenticationError("Refresh session is missing or revoked")
            user = self.uow.users.get_by_id(payload.sub)
            if user is None:
                raise AuthenticationError("User not found")
            self.refresh_sessions.revoke(payload.jti)
            tokens = self._issue_tokens(user.user)
            return self._build_response(user.user, tokens), tokens
        finally:
            self.uow.close()

    def get_current_user(self, access_token: str, *, expected_csrf: str | None = None) -> User:
        try:
            try:
                payload = decode_token(access_token, self.settings)
            except jwt.PyJWTError as exc:
                raise AuthenticationError("Invalid access token") from exc
            if payload.type != "access":
                raise AuthenticationError("Invalid access token")
            self._require_bound_csrf(payload, expected_csrf)
            user = self.uow.users.get_by_id(payload.sub)
            if user is None:
                raise AuthenticationError("User not found")
            return user.user
        finally:
            self.uow.close()

    def logout(self, refresh_token: str | None, *, expected_csrf: str | None = None) -> None:
        try:
            if not refresh_token:
                return
            try:
                payload = decode_token(refresh_token, self.settings)
            except jwt.PyJWTError:
                return
            if payload.type == "refresh":
                self._require_bound_csrf(payload, expected_csrf)
                self.refresh_sessions.revoke(payload.jti)
        finally:
            self.uow.close()

    def _require_bound_csrf(self, payload: TokenClaims, expected_csrf: str | None) -> None:
        if expected_csrf is None:
            return
        if payload.csrf != expected_csrf:
            raise CsrfValidationError("Invalid CSRF token")

    def _issue_tokens(self, user: User) -> TokenBundle:
        csrf_token = generate_csrf_token()
        access_token, access_expires_at, _ = create_token(
            subject=str(user.id),
            token_type="access",
            expires_delta=timedelta(minutes=self.settings.access_ttl_minutes),
            settings=self.settings,
            extra_claims=TokenExtraClaims(csrf=csrf_token),
        )
        refresh_token, refresh_expires_at, refresh_jti = create_token(
            subject=str(user.id),
            token_type="refresh",
            expires_delta=timedelta(days=self.settings.refresh_ttl_days),
            settings=self.settings,
            extra_claims=TokenExtraClaims(csrf=csrf_token),
        )
        self.refresh_sessions.create(
            RefreshSession(
                id=uuid4(),
                user_id=user.id,
                token_id=refresh_jti,
                expires_at=refresh_expires_at,
                created_at=utc_now(),
            )
        )
        return TokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            csrf_token=csrf_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )

    def _build_response(self, user: User, tokens: TokenBundle) -> AuthResponse:
        return AuthResponse(
            user=user,
            access_expires_at=tokens.access_expires_at,
            refresh_expires_at=tokens.refresh_expires_at,
        )
