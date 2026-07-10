from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.auth_service import (
    authenticate_user,
    build_public_user,
    create_user_account,
    ensure_developer_account,
    get_user_profile,
    legacy_hash_password,
)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def make_connect(db_path: str):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return connect


def test_get_user_profile_returns_default_schema(app, test_db_path):
    profile = get_user_profile(999, connect=make_connect(test_db_path))

    assert profile == {
        "preference": "balanced",
        "riskAnswers": {},
        "onboardingCompleted": False,
        "updatedAt": None,
    }


def test_create_authenticate_and_public_user_schema(app, test_db_path):
    connect = make_connect(test_db_path)
    created_at = "2026-07-07T09:00:00Z"

    user = create_user_account(
        connect=connect,
        email="unit@example.com",
        password="Test!2345",
        created_at=created_at,
    )

    assert user["email"] == "unit@example.com"
    assert user["password_hash"].startswith("$2")
    assert user["salt"] == "bcrypt"
    assert authenticate_user(connect=connect, email="unit@example.com", password="wrong") is None
    authenticated = authenticate_user(connect=connect, email="unit@example.com", password="Test!2345")
    assert authenticated is not None

    public = build_public_user(authenticated, get_user_profile=lambda user_id: get_user_profile(user_id, connect=connect))
    assert public == {
        "id": authenticated["id"],
        "email": "unit@example.com",
        "role": "user",
        "createdAt": created_at,
        "onboardingCompleted": False,
        "preference": "balanced",
    }


def test_ensure_developer_account_creates_and_promotes(monkeypatch, app, test_db_path):
    connect = make_connect(test_db_path)
    fixed_now = datetime(2026, 7, 7, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("INVESTMENT_RESEARCH_DEV_EMAIL", "dev@example.com")
    monkeypatch.setenv("INVESTMENT_RESEARCH_DEV_PASSWORD", "Dev!23456")

    with connect() as conn:
        ensure_developer_account(conn=conn, now_utc=lambda: fixed_now, iso=iso)
        conn.commit()
        row = conn.execute("select email, role from users where email = 'dev@example.com'").fetchone()

    assert row["role"] == "developer"

    with connect() as conn:
        conn.execute("update users set role = 'user' where email = 'dev@example.com'")
        ensure_developer_account(conn=conn, now_utc=lambda: fixed_now, iso=iso)
        conn.commit()
        row = conn.execute("select role from users where email = 'dev@example.com'").fetchone()

    assert row["role"] == "developer"


def test_legacy_sha256_password_migrates_to_bcrypt_on_login(app, test_db_path):
    connect = make_connect(test_db_path)
    salt = "legacy-salt"
    with connect() as conn:
        conn.execute(
            """
            insert into users(email, password_hash, salt, created_at, role)
            values(?, ?, ?, ?, ?)
            """,
            ("legacy@example.com", legacy_hash_password("Legacy!2345", salt), salt, "2026-07-07T09:00:00Z", "user"),
        )
        conn.commit()
    user = authenticate_user(connect=connect, email="legacy@example.com", password="Legacy!2345")

    assert user is not None
    assert user["password_hash"].startswith("$2")
    assert user["salt"] == "bcrypt"
