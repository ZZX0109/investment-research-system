from __future__ import annotations

import sqlite3
from typing import Any, Callable

from .credential_repository import delete_api_key_row, fetch_api_key_rows, upsert_api_key_row


def mask_key(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def user_api_key_summary(
    *,
    connect: Callable[[], sqlite3.Connection],
    decrypt_secret: Callable[[str], str],
    user_id: int,
) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = fetch_api_key_rows(conn, user_id)
    return [
        {
            "provider": row["provider"],
            "maskedKey": mask_key(decrypt_secret(row["api_key"])),
            "updatedAt": row["updated_at"],
            "enabled": True,
        }
        for row in rows
    ]


def upsert_user_api_key(
    *,
    connect: Callable[[], sqlite3.Connection],
    encrypt_secret: Callable[[str], str],
    user_id: int,
    provider: str,
    api_key: str,
    updated_at: str,
) -> None:
    with connect() as conn:
        upsert_api_key_row(
            conn,
            user_id=user_id,
            provider=provider,
            encrypted_api_key=encrypt_secret(api_key),
            updated_at=updated_at,
        )
        conn.commit()


def delete_user_api_key(
    *,
    connect: Callable[[], sqlite3.Connection],
    user_id: int,
    provider: str,
) -> None:
    with connect() as conn:
        delete_api_key_row(conn, user_id=user_id, provider=provider)
        conn.commit()
