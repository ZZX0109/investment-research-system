from __future__ import annotations

import sqlite3


def fetch_user_profile_row(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("select * from user_profiles where user_id = ?", (user_id,)).fetchone()


def fetch_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("select * from users where email = ?", (email,)).fetchone()


def fetch_user_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("select * from users where id = ?", (user_id,)).fetchone()


def fetch_user_by_access_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select users.* from sessions
        join users on users.id = sessions.user_id
        where sessions.token = ?
        """,
        (token,),
    ).fetchone()


def insert_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    password_hash: str,
    salt: str,
    created_at: str,
    role: str = "user",
) -> int:
    cursor = conn.execute(
        "insert into users(email, password_hash, salt, created_at, role) values(?, ?, ?, ?, ?)",
        (email, password_hash, salt, created_at, role),
    )
    return int(cursor.lastrowid)


def update_user_role(conn: sqlite3.Connection, *, email: str, role: str) -> None:
    conn.execute("update users set role = ? where email = ?", (role, email))


def update_user_password_hash(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    password_hash: str,
    salt: str,
) -> None:
    conn.execute(
        "update users set password_hash = ?, salt = ? where id = ?",
        (password_hash, salt, user_id),
    )
