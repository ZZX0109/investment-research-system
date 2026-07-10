from __future__ import annotations

import sqlite3


def fetch_api_key_rows(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "select provider, api_key, updated_at from api_keys where user_id = ? order by provider",
        (user_id,),
    ).fetchall()


def upsert_api_key_row(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    provider: str,
    encrypted_api_key: str,
    updated_at: str,
) -> None:
    conn.execute(
        """
        insert into api_keys(user_id, provider, api_key, updated_at)
        values(?, ?, ?, ?)
        on conflict(user_id, provider) do update set api_key = excluded.api_key, updated_at = excluded.updated_at
        """,
        (user_id, provider, encrypted_api_key, updated_at),
    )


def delete_api_key_row(conn: sqlite3.Connection, *, user_id: int, provider: str) -> None:
    conn.execute("delete from api_keys where user_id = ? and provider = ?", (user_id, provider))
