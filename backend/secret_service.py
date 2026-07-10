from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Callable


SECRET_PREFIX = "enc-v1:"


def resolve_master_key() -> bytes:
    raw = os.getenv("INVESTMENT_RESEARCH_MASTER_KEY", "").strip() or os.getenv("INVESTMENT_RESEARCH_SECRET_KEY", "").strip()
    if not raw:
        raw = "investment_research-dev-only-change-me"
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _xor_keystream(data: bytes, master_key: bytes, nonce: bytes) -> bytes:
    result = bytearray()
    counter = 0
    while len(result) < len(data):
        block = hashlib.sha256(master_key + nonce + counter.to_bytes(4, "big")).digest()
        result.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(data, result[: len(data)]))


def encrypt_secret(value: str, *, master_key: bytes | None = None) -> str:
    key = master_key or resolve_master_key()
    nonce = secrets.token_bytes(16)
    ciphertext = _xor_keystream(value.encode("utf-8"), key, nonce)
    payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
    return f"{SECRET_PREFIX}{payload}"


def decrypt_secret(value: str, *, master_key: bytes | None = None) -> str:
    if not value.startswith(SECRET_PREFIX):
        return value
    key = master_key or resolve_master_key()
    raw = base64.urlsafe_b64decode(value.removeprefix(SECRET_PREFIX).encode("ascii"))
    nonce, ciphertext = raw[:16], raw[16:]
    plaintext = _xor_keystream(ciphertext, key, nonce)
    return plaintext.decode("utf-8")


def is_encrypted_secret(value: str) -> bool:
    return value.startswith(SECRET_PREFIX)


def migrate_plaintext_secrets(
    *,
    connect: Callable[[], object],
    encrypt_value: Callable[[str], str],
) -> int:
    migrated = 0
    with connect() as conn:  # type: ignore[misc]
        rows = conn.execute("select id, api_key from api_keys").fetchall()
        for row in rows:
            if is_encrypted_secret(row["api_key"]):
                continue
            conn.execute("update api_keys set api_key = ? where id = ?", (encrypt_value(row["api_key"]), row["id"]))
            migrated += 1
        conn.commit()
    return migrated
