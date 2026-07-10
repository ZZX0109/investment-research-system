from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import re
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import bcrypt
from fastapi import Header, HTTPException
from pydantic import BaseModel

from .config import EMAIL_PATTERN, PASSWORD_POLICY_TEXT
from .schemas import PublicUserRecord, UserProfileRecord
from .user_repository import (
    fetch_user_by_email,
    fetch_user_by_access_token,
    fetch_user_by_id,
    fetch_user_profile_row,
    insert_user,
    update_user_password_hash,
    update_user_role,
)


class AuthRequest(BaseModel):
    email: str
    password: str


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    access_expires_at: str
    refresh_expires_at: str


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def legacy_hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def hash_password(password: str, salt: str | None = None) -> str:
    if salt is not None:
        return legacy_hash_password(password, salt)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str, salt: str | None = None) -> bool:
    if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    if not salt:
        return False
    return legacy_hash_password(password, salt) == password_hash


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def token_ttl_seconds() -> int:
    return int(os.getenv("INVESTMENT_RESEARCH_ACCESS_TOKEN_TTL_SECONDS", "900"))


def refresh_ttl_seconds() -> int:
    return int(os.getenv("INVESTMENT_RESEARCH_REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 60 * 60)))


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")
    if not re.search(r"[^a-zA-Z0-9]", password):
        errors.append("Password must contain at least one special character")
    return errors


def validate_auth_request(request: AuthRequest, *, check_password_policy: bool) -> str:
    email = request.email.strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise HTTPException(status_code=400, detail="Use a valid email address.")
    if check_password_policy and password_policy_errors(request.password):
        raise HTTPException(status_code=400, detail=PASSWORD_POLICY_TEXT)
    return email


def get_user_profile(
    user_id: int,
    *,
    connect: Callable[[], sqlite3.Connection],
) -> dict[str, Any]:
    with closing(connect()) as conn:
        row = fetch_user_profile_row(conn, user_id)
    if not row:
        return dump_model(UserProfileRecord())
    return dump_model(
        UserProfileRecord(
            preference=row["preference"],
            riskAnswers=json.loads(row["risk_answers"] or "{}"),
            onboardingCompleted=bool(row["onboarding_completed"]),
            updatedAt=row["updated_at"],
        )
    )


def build_public_user(
    row: sqlite3.Row,
    *,
    get_user_profile: Callable[[int], dict[str, Any]],
) -> dict[str, Any]:
    profile = get_user_profile(int(row["id"]))
    return dump_model(
        PublicUserRecord(
            id=int(row["id"]),
            email=row["email"],
            role=row["role"] if "role" in row.keys() else "user",
            createdAt=row["created_at"],
            onboardingCompleted=profile["onboardingCompleted"],
            preference=profile["preference"],
        )
    )


def create_user_account(
    *,
    connect: Callable[[], sqlite3.Connection],
    email: str,
    password: str,
    created_at: str,
    role: str = "user",
) -> sqlite3.Row:
    password_hash = hash_password(password)
    with closing(connect()) as conn:
        user_id = insert_user(
            conn,
            email=email,
            password_hash=password_hash,
            salt="bcrypt",
            created_at=created_at,
            role=role,
        )
        conn.commit()
        user = fetch_user_by_id(conn, user_id)
    if user is None:
        raise RuntimeError("User was created but could not be reloaded.")
    return user


def authenticate_user(
    *,
    connect: Callable[[], sqlite3.Connection],
    email: str,
    password: str,
) -> sqlite3.Row | None:
    with closing(connect()) as conn:
        user = fetch_user_by_email(conn, email)
        if not user or not verify_password(password, user["password_hash"], user["salt"]):
            return None
        if not str(user["password_hash"]).startswith(("$2a$", "$2b$", "$2y$")):
            update_user_password_hash(
                conn,
                user_id=int(user["id"]),
                password_hash=hash_password(password),
                salt="bcrypt",
            )
            conn.commit()
            user = fetch_user_by_id(conn, int(user["id"]))
    return user


def load_user_for_access_token(
    *,
    connect: Callable[[], sqlite3.Connection],
    token: str,
) -> sqlite3.Row | None:
    with closing(connect()) as conn:
        return fetch_user_by_access_token(conn, token)


def ensure_developer_account(
    *,
    conn: sqlite3.Connection,
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
) -> None:
    email = os.getenv("INVESTMENT_RESEARCH_DEV_EMAIL", "").strip().lower()
    password = os.getenv("INVESTMENT_RESEARCH_DEV_PASSWORD", "")
    if not email and not password:
        return
    if not EMAIL_PATTERN.match(email):
        raise RuntimeError("INVESTMENT_RESEARCH_DEV_EMAIL must be a valid email address.")
    errors = password_policy_errors(password)
    if errors:
        raise RuntimeError(f"INVESTMENT_RESEARCH_DEV_PASSWORD is invalid: {', '.join(errors)}.")

    existing = fetch_user_by_email(conn, email)
    if existing:
        update_user_role(conn, email=email, role="developer")
        return

    insert_user(
        conn,
        email=email,
        password_hash=hash_password(password),
        salt="bcrypt",
        created_at=iso(now_utc()),
        role="developer",
    )


def create_session(
    *,
    connect: Callable[[], sqlite3.Connection],
    user_id: int,
    created_at: str,
) -> SessionTokens:
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(48)
    created = parse_iso(created_at)
    access_expires_at = iso(created + timedelta(seconds=token_ttl_seconds()))
    refresh_expires_at = iso(created + timedelta(seconds=refresh_ttl_seconds()))
    with closing(connect()) as conn:
        conn.execute(
            """
            insert into sessions(token, user_id, created_at, expires_at, refresh_token_hash, refresh_expires_at, revoked_at)
            values(?, ?, ?, ?, ?, ?, null)
            """,
            (access_token, user_id, created_at, access_expires_at, hash_refresh_token(refresh_token), refresh_expires_at),
        )
        conn.commit()
    return SessionTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )


def refresh_session(
    *,
    connect: Callable[[], sqlite3.Connection],
    refresh_token: str,
    refreshed_at: str,
) -> SessionTokens | None:
    refresh_hash = hash_refresh_token(refresh_token)
    now = parse_iso(refreshed_at)
    with closing(connect()) as conn:
        row = conn.execute(
            """
            select * from sessions
            where refresh_token_hash = ?
              and revoked_at is null
            order by created_at desc
            limit 1
            """,
            (refresh_hash,),
        ).fetchone()
        if not row or not row["refresh_expires_at"] or parse_iso(row["refresh_expires_at"]) <= now:
            return None
        conn.execute("update sessions set revoked_at = ? where token = ?", (refreshed_at, row["token"]))
        conn.commit()
    return create_session(connect=connect, user_id=int(row["user_id"]), created_at=refreshed_at)


def revoke_session(
    *,
    connect: Callable[[], sqlite3.Connection],
    token: str | None,
    refresh_token: str | None,
    revoked_at: str,
) -> None:
    with closing(connect()) as conn:
        if token:
            conn.execute("update sessions set revoked_at = ? where token = ?", (revoked_at, token))
        if refresh_token:
            conn.execute(
                "update sessions set revoked_at = ? where refresh_token_hash = ?",
                (revoked_at, hash_refresh_token(refresh_token)),
            )
        conn.commit()


def build_current_user_dependency(
    *,
    connect: Callable[[], sqlite3.Connection],
) -> Callable[[str | None], sqlite3.Row]:
    def get_current_user(authorization: str | None = Header(default=None)) -> sqlite3.Row:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")
        token = authorization.removeprefix("Bearer ").strip()
        with closing(connect()) as conn:
            row = conn.execute(
                """
                select users.* from sessions
                join users on users.id = sessions.user_id
                where sessions.token = ?
                  and sessions.revoked_at is null
                """,
                (token,),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid token")
        with closing(connect()) as conn:
            session = conn.execute("select * from sessions where token = ?", (token,)).fetchone()
        if session and session["expires_at"] and parse_iso(session["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Token expired")
        return row

    return get_current_user


def build_auth_payload(
    *,
    user: sqlite3.Row,
    get_user_profile: Callable[[int], dict[str, Any]],
    public_user: Callable[[sqlite3.Row], dict[str, Any]],
    user_api_key_summary: Callable[[int], list[dict[str, Any]]],
) -> dict[str, Any]:
    user_id = int(user["id"])
    public = public_user(user)
    profile = get_user_profile(user_id)
    return {
        "id": public["id"],
        "email": public["email"],
        "role": public["role"],
        "createdAt": public["createdAt"],
        "onboardingCompleted": profile["onboardingCompleted"],
        "preference": profile["preference"],
        "user": public,
        "profile": profile,
        "apiKeys": user_api_key_summary(user_id),
    }
