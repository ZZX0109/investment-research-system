from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from investment_research.config import get_app_settings
from investment_research.config import redact_sensitive_value
from investment_research.service.credential_models import CredentialKind
from investment_research.service.credential_models import CredentialSummaryResponse
from investment_research.service.credential_models import CredentialUpsertRequest

_VALID_KINDS = {"api-key", "test-account", "connector-token", "custom"}
_VALID_ID = re.compile(r"^[A-Za-z0-9._:-]+$")


class CredentialVaultError(ValueError):
    pass


@dataclass(frozen=True)
class CredentialVaultSettings:
    store_path: Path
    master_key: bytes | None
    key_id: str | None
    dev_mode: bool
    environment: str | None


@dataclass(frozen=True)
class CredentialRecord:
    id: str
    label: str
    kind: CredentialKind
    secret: str
    username: str | None
    metadata: dict[str, str]
    created_at: str
    updated_at: str


def get_credential_vault_settings() -> CredentialVaultSettings:
    app_settings = get_app_settings()
    environment = app_settings.environment.value
    dev_mode = app_settings.allow_insecure_defaults
    raw_key = os.getenv("AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY")
    key = _normalize_key(raw_key) if raw_key else None
    if key is None and dev_mode:
        key = sha256(b"dev-ai-test-officer-credential-master-key").digest()
    store_path = Path(os.getenv("AI_TEST_OFFICER_CREDENTIAL_STORE_PATH", "runs/secrets/credentials.json"))
    return CredentialVaultSettings(
        store_path=store_path,
        master_key=key,
        key_id=f"local:{sha256(key).hexdigest()[:16]}" if key else None,
        dev_mode=dev_mode,
        environment=environment,
    )


def validate_credential_vault_settings(settings: CredentialVaultSettings | None = None) -> None:
    resolved = settings or get_credential_vault_settings()
    if resolved.master_key is None:
        raise RuntimeError(
            "AI_TEST_OFFICER_CREDENTIAL_MASTER_KEY is required unless INVESTMENT_RESEARCH_ENV is development, demo, or test"
        )


def credential_vault_settings_summary(settings: CredentialVaultSettings | None = None) -> dict[str, object]:
    resolved = settings or get_credential_vault_settings()
    return {
        "store_path": str(resolved.store_path),
        "key_id": resolved.key_id,
        "master_key_preview": redact_sensitive_value(
            None if resolved.master_key is None else resolved.master_key.hex()
        ),
        "environment": resolved.environment,
        "dev_mode": resolved.dev_mode,
    }


class CredentialVault:
    def __init__(self, settings: CredentialVaultSettings | None = None) -> None:
        self.settings = settings or get_credential_vault_settings()
        validate_credential_vault_settings(self.settings)

    def list_credentials(self) -> list[CredentialSummaryResponse]:
        return [self._summarize(record) for record in self._read_records()]

    def upsert_credential(self, payload: CredentialUpsertRequest) -> CredentialSummaryResponse:
        record = self._validate_record_payload(payload)
        records = self._read_records()
        previous = next((existing for existing in records if existing.id == record.id), None)
        now = _utc_now()
        next_record = CredentialRecord(
            id=record.id,
            label=record.label,
            kind=record.kind,
            secret=record.secret,
            username=record.username,
            metadata=record.metadata,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        next_records = sorted(
            [existing for existing in records if existing.id != next_record.id] + [next_record],
            key=lambda item: item.id,
        )
        self._write_records(next_records)
        return self._summarize(next_record)

    def delete_credential(self, credential_id: str) -> bool:
        self._validate_id(credential_id)
        records = self._read_records()
        next_records = [record for record in records if record.id != credential_id]
        if len(next_records) == len(records):
            return False
        self._write_records(next_records)
        return True

    def get_secret(self, credential_id: str) -> str:
        """Resolve a secret for an internal provider without exposing it via API."""
        self._validate_id(credential_id)
        record = next(
            (item for item in self._read_records() if item.id == credential_id),
            None,
        )
        if record is None:
            raise CredentialVaultError("Credential not found")
        return record.secret

    def _read_records(self) -> list[CredentialRecord]:
        if self.settings.master_key is None or self.settings.key_id is None:
            raise CredentialVaultError("Credential vault master key is unavailable")
        if not self.settings.store_path.exists():
            return []
        try:
            raw = json.loads(self.settings.store_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise CredentialVaultError(f"Credential vault read failed: {exc}") from exc
        if raw.get("schemaVersion") != "1.0" or raw.get("keyId") != self.settings.key_id:
            raise CredentialVaultError("Credential vault schema or key id is invalid")
        encrypted_records = raw.get("credentials")
        if not isinstance(encrypted_records, list):
            raise CredentialVaultError("Credential vault credentials must be a list")
        return [self._decrypt_record(record) for record in encrypted_records]

    def _write_records(self, records: list[CredentialRecord]) -> None:
        if self.settings.master_key is None or self.settings.key_id is None:
            raise CredentialVaultError("Credential vault master key is unavailable")
        payload = {
            "schemaVersion": "1.0",
            "keyId": self.settings.key_id,
            "credentials": [self._encrypt_record(record) for record in records],
        }
        self.settings.store_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings.store_path.with_name(
            f"{self.settings.store_path.name}.{os.getpid()}.{datetime.now(timezone.utc).timestamp()}.tmp"
        )
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.settings.store_path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _encrypt_record(self, record: CredentialRecord) -> dict[str, object]:
        if self.settings.master_key is None or self.settings.key_id is None:
            raise CredentialVaultError("Credential vault master key is unavailable")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.settings.master_key).encrypt(
            nonce,
            record.secret.encode("utf-8"),
            record.id.encode("utf-8"),
        )
        return {
            "id": record.id,
            "label": record.label,
            "kind": record.kind,
            "username": record.username,
            "metadata": record.metadata,
            "createdAt": record.created_at,
            "updatedAt": record.updated_at,
            "algorithm": "aes-256-gcm",
            "keyId": self.settings.key_id,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def _decrypt_record(self, value: object) -> CredentialRecord:
        if self.settings.master_key is None or self.settings.key_id is None:
            raise CredentialVaultError("Credential vault master key is unavailable")
        if not isinstance(value, dict):
            raise CredentialVaultError("Credential record is invalid")
        if value.get("algorithm") != "aes-256-gcm" or value.get("keyId") != self.settings.key_id:
            raise CredentialVaultError("Credential record algorithm or key id is invalid")
        credential_id = str(value.get("id", ""))
        try:
            secret = AESGCM(self.settings.master_key).decrypt(
                base64.b64decode(str(value["nonce"])),
                base64.b64decode(str(value["ciphertext"])),
                credential_id.encode("utf-8"),
            ).decode("utf-8")
        except Exception as exc:
            raise CredentialVaultError(f"Credential decrypt failed for {credential_id}") from exc
        return CredentialRecord(
            id=credential_id,
            label=str(value.get("label", "")),
            kind=_coerce_kind(value.get("kind")),
            secret=secret,
            username=str(value["username"]) if value.get("username") is not None else None,
            metadata=_coerce_metadata(value.get("metadata")),
            created_at=str(value.get("createdAt", "")),
            updated_at=str(value.get("updatedAt", "")),
        )

    def _validate_record_payload(self, payload: CredentialUpsertRequest) -> CredentialRecord:
        credential_id = payload.id.strip()
        self._validate_id(credential_id)
        label = payload.label.strip()
        secret = payload.secret
        if not label:
            raise CredentialVaultError("Credential label is required")
        if not secret:
            raise CredentialVaultError("Credential secret is required")
        return CredentialRecord(
            id=credential_id,
            label=label,
            kind=_coerce_kind(payload.kind),
            secret=secret,
            username=payload.username.strip() if payload.username else None,
            metadata=_coerce_metadata(payload.metadata),
            created_at="",
            updated_at="",
        )

    def _validate_id(self, credential_id: str) -> None:
        if not credential_id or not _VALID_ID.match(credential_id):
            raise CredentialVaultError("Credential id must contain only letters, numbers, dots, dashes, underscores, or colons")

    def _summarize(self, record: CredentialRecord) -> CredentialSummaryResponse:
        return CredentialSummaryResponse(
            id=record.id,
            label=record.label,
            kind=record.kind,
            username=record.username,
            metadata=record.metadata,
            createdAt=record.created_at,
            updatedAt=record.updated_at,
            secretPreview=_preview_secret(record.secret),
            secretLength=len(record.secret),
        )


def _normalize_key(value: str | None) -> bytes | None:
    if value is None:
        return None
    stripped = value.strip()
    if re.fullmatch(r"[A-Fa-f0-9]{64}", stripped):
        return bytes.fromhex(stripped)
    try:
        decoded = base64.b64decode(stripped, validate=True)
        if len(decoded) == 32:
            return decoded
    except (binascii.Error, ValueError):
        pass
    return sha256(stripped.encode("utf-8")).digest()


def _coerce_kind(value: object) -> CredentialKind:
    if value not in _VALID_KINDS:
        raise CredentialVaultError("Credential kind is invalid")
    return value  # type: ignore[return-value]


def _coerce_metadata(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CredentialVaultError("Credential metadata must be an object")
    return {str(key): str(item) for key, item in value.items()}


def _preview_secret(secret: str) -> str:
    suffix = secret[-4:] if len(secret) >= 4 else secret
    return f"****{suffix}" if suffix else "****"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
