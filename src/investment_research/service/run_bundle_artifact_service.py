from __future__ import annotations

import binascii
import hashlib
import os
import zipfile
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from investment_research.service.run_bundle_manifest_service import RunBundleManifestService
from investment_research.service.run_bundle_models import RunBundleArtifactIntegrityRecord
from investment_research.service.run_bundle_models import RunBundleArtifactIntegrityReport
from investment_research.service.run_bundle_models import RunBundleDownloadManifest
from investment_research.service.run_bundle_models import RunBundleDownloadManifestEntry
from investment_research.service.run_bundle_models import JsonValue
from investment_research.service.run_bundle_models import RunBundleManifestArtifact
from investment_research.service.run_bundle_store import RunBundleFileStore


class ArtifactDecryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunBundleArtifactDelivery:
    path: Path
    media_type: str | None = None
    temporary: bool = False


class RunBundleArtifactService:
    """Handles artifact file delivery, integrity reports, and download bundles."""

    def __init__(self, store: RunBundleFileStore, manifests: RunBundleManifestService) -> None:
        self.store = store
        self.manifests = manifests

    def get_artifact_path(self, run_id: str, artifact_name: str) -> Path:
        artifact_root = (self.store.safe_run_root(run_id) / "artifacts").resolve()
        artifact_path = (artifact_root / artifact_name).resolve()
        if not artifact_path.is_file() or artifact_root not in artifact_path.parents:
            raise FileNotFoundError(f"Artifact not found for {run_id}: {artifact_name}")
        return artifact_path

    def get_artifact_delivery(self, run_id: str, artifact_name: str) -> RunBundleArtifactDelivery:
        artifact_path = self.get_artifact_path(run_id, artifact_name)
        artifact = self._find_manifest_artifact(run_id, artifact_name)
        if artifact is None or not _metadata_flag(artifact.metadata, "encryptedAtRest"):
            return RunBundleArtifactDelivery(
                path=artifact_path,
                media_type=artifact.mediaType if artifact else None,
            )

        plain_bytes = self._decrypt_artifact_bytes(artifact_path, artifact)
        suffix = artifact_path.suffix or ".artifact"
        with NamedTemporaryFile(prefix=f"{run_id}-{artifact_path.stem}-", suffix=suffix, delete=False) as temp_file:
            temp_file.write(plain_bytes)
            temp_path = Path(temp_file.name)
        return RunBundleArtifactDelivery(path=temp_path, media_type=artifact.mediaType, temporary=True)

    def verify_artifact_integrity(self, run_id: str) -> RunBundleArtifactIntegrityReport:
        manifest = self.manifests.get_manifest(run_id)
        records: list[RunBundleArtifactIntegrityRecord] = []
        for artifact in manifest.artifacts:
            expected_sha = getattr(artifact, "sha256", None)
            expected_size = artifact.sizeBytes
            try:
                artifact_path = self.store.resolve_run_path(run_id, artifact.path)
            except FileNotFoundError as exc:
                records.append(
                    RunBundleArtifactIntegrityRecord(
                        artifactId=artifact.id,
                        path=artifact.path,
                        status="path-escaped",
                        expectedSha256=expected_sha,
                        expectedSizeBytes=expected_size,
                        reason=str(exc),
                    )
                )
                continue

            if not artifact_path.exists():
                records.append(
                    RunBundleArtifactIntegrityRecord(
                        artifactId=artifact.id,
                        path=str(artifact_path),
                        status="missing",
                        expectedSha256=expected_sha,
                        expectedSizeBytes=expected_size,
                        reason="Artifact file is missing.",
                    )
                )
                continue

            actual = artifact_path.read_bytes()
            actual_sha = hashlib.sha256(actual).hexdigest()
            actual_size = len(actual)
            sha_matches = expected_sha is None or actual_sha == expected_sha
            size_matches = expected_size is None or actual_size == expected_size
            records.append(
                RunBundleArtifactIntegrityRecord(
                    artifactId=artifact.id,
                    path=str(artifact_path),
                    status="passed" if sha_matches and size_matches else "failed",
                    expectedSha256=expected_sha,
                    actualSha256=actual_sha,
                    expectedSizeBytes=expected_size,
                    actualSizeBytes=actual_size,
                    reason=None if sha_matches and size_matches else "Artifact hash or size does not match manifest.",
                )
            )

        summary: dict[str, int] = {}
        for record in records:
            summary[record.status] = summary.get(record.status, 0) + 1
        report_path = self.store.safe_run_root(run_id) / "reports" / "integrity-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = RunBundleArtifactIntegrityReport.model_validate(
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "reportPath": str(report_path),
                "passed": all(record.status == "passed" for record in records),
                "summary": summary,
                "artifacts": records,
            }
        )
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report

    def create_download_bundle(self, run_id: str) -> RunBundleDownloadManifest:
        manifest = self.manifests.get_manifest(run_id)
        run_root = self.store.safe_run_root(run_id)
        reports_dir = run_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = reports_dir / "run-bundle.zip"
        entries: list[RunBundleDownloadManifestEntry] = []
        large_strategy = _download_large_artifact_strategy()
        large_threshold = _download_large_artifact_threshold()
        artifact_index = self._artifact_index_by_relative_path(run_id, manifest.artifacts)
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(run_root.rglob("*")):
                if not file_path.is_file() or file_path == bundle_path:
                    continue
                relative = file_path.relative_to(run_root)
                relative_label = relative.as_posix()
                artifact = artifact_index.get(relative_label)
                is_large_runtime_artifact = (
                    artifact is not None
                    and artifact.kind in {"playwright-trace", "video"}
                    and file_path.stat().st_size > large_threshold
                )
                include_file = not (is_large_runtime_artifact and large_strategy == "reference-only")
                if include_file:
                    archive.write(file_path, relative_label)
                entries.append(
                    RunBundleDownloadManifestEntry(
                        label=relative_label,
                        path=str(file_path),
                        relativePath=relative_label,
                        sizeBytes=file_path.stat().st_size,
                        included=include_file,
                        largeArtifact=is_large_runtime_artifact,
                        largeArtifactStrategy=large_strategy if is_large_runtime_artifact else None,
                        reason=(
                            f"Large {artifact.kind} omitted from zip; referenced by path only."
                            if is_large_runtime_artifact and not include_file
                            else None
                        ),
                        artifactId=artifact.id if artifact else None,
                        artifactKind=artifact.kind if artifact else None,
                    )
                )
        manifest_path = reports_dir / "download-manifest.json"
        result = RunBundleDownloadManifest.model_validate(
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "bundlePath": str(bundle_path),
                "entryCount": len(entries),
                "includedCount": sum(1 for entry in entries if entry.included),
                "referencedOnlyCount": sum(1 for entry in entries if not entry.included),
                "largeArtifactStrategy": large_strategy,
                "largeArtifactThresholdBytes": large_threshold,
                "sizeBytes": bundle_path.stat().st_size,
                "entries": entries,
            }
        )
        manifest_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def _find_manifest_artifact(self, run_id: str, artifact_name: str) -> RunBundleManifestArtifact | None:
        try:
            manifest = self.manifests.get_manifest(run_id)
        except FileNotFoundError:
            return None
        normalized_name = artifact_name.replace("\\", "/").lstrip("/")
        expected_relative = f"artifacts/{normalized_name}"
        for artifact in manifest.artifacts:
            metadata = _metadata_dict(artifact.metadata)
            relative_path = metadata.get("relativePath")
            if relative_path == expected_relative or relative_path == normalized_name:
                return artifact
            if artifact.path.replace("\\", "/").endswith(f"/{normalized_name}"):
                return artifact
            if Path(artifact.path).name == Path(normalized_name).name:
                return artifact
        return None

    def _decrypt_artifact_bytes(
        self,
        artifact_path: Path,
        artifact: RunBundleManifestArtifact,
    ) -> bytes:
        metadata = artifact.metadata or {}
        key = _load_artifact_encryption_key(_metadata_text(metadata, "encryptionKeyRef"))
        iv = _metadata_b64(metadata, "encryptionIv")
        auth_tag = _metadata_b64(metadata, "encryptionAuthTag")
        ciphertext = artifact_path.read_bytes()
        try:
            plain_bytes = AESGCM(key).decrypt(iv, ciphertext + auth_tag, None)
        except Exception as exc:
            raise ArtifactDecryptionError("Encrypted artifact could not be decrypted with the configured key") from exc

        expected_sha = _metadata_text(metadata, "plaintextSha256")
        if expected_sha and hashlib.sha256(plain_bytes).hexdigest() != expected_sha:
            raise ArtifactDecryptionError("Encrypted artifact plaintext hash does not match manifest metadata")

        expected_size = _metadata_int(metadata, "plaintextSizeBytes")
        if expected_size is not None and len(plain_bytes) != expected_size:
            raise ArtifactDecryptionError("Encrypted artifact plaintext size does not match manifest metadata")

        return plain_bytes

    def _artifact_index_by_relative_path(
        self,
        run_id: str,
        artifacts: list[RunBundleManifestArtifact],
    ) -> dict[str, RunBundleManifestArtifact]:
        index: dict[str, RunBundleManifestArtifact] = {}
        for artifact in artifacts:
            relative_path = self.manifests.artifact_relative_path(artifact)
            if relative_path:
                index[relative_path.replace("\\", "/")] = artifact
                continue
            try:
                artifact_path = Path(artifact.path).resolve()
                run_root = self.store.safe_run_root(run_id)
                index[artifact_path.relative_to(run_root).as_posix()] = artifact
            except (OSError, ValueError, FileNotFoundError):
                continue
        return index


def _metadata_dict(metadata: object | None) -> dict[str, JsonValue]:
    if metadata is None:
        return {}
    if hasattr(metadata, "model_dump"):
        value = metadata.model_dump()
        return value if isinstance(value, dict) else {}
    return metadata if isinstance(metadata, dict) else {}


def _metadata_flag(metadata: object | None, key: str) -> bool:
    value = _metadata_dict(metadata).get(key)
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _metadata_text(metadata: object | None, key: str) -> str | None:
    value = _metadata_dict(metadata).get(key)
    return value if isinstance(value, str) and value else None


def _metadata_int(metadata: object | None, key: str) -> int | None:
    value = _metadata_dict(metadata).get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _metadata_b64(metadata: object | None, key: str) -> bytes:
    value = _metadata_text(metadata, key)
    if value is None:
        raise ArtifactDecryptionError(f"Encrypted artifact metadata is missing {key}")
    try:
        return b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise ArtifactDecryptionError(f"Encrypted artifact metadata has invalid {key}") from exc


def _load_artifact_encryption_key(expected_key_ref: str | None) -> bytes:
    configured_key_ref = os.getenv("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY_REF")
    if configured_key_ref and expected_key_ref and configured_key_ref != expected_key_ref:
        raise ArtifactDecryptionError("Configured artifact encryption key ref does not match manifest metadata")
    key_material = os.getenv("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY")
    if not key_material:
        raise ArtifactDecryptionError("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY is required to read encrypted artifacts")
    return _parse_artifact_encryption_key(key_material)


def _parse_artifact_encryption_key(key_material: str) -> bytes:
    stripped = key_material.strip()
    encoded = stripped.removeprefix("base64:")
    try:
        decoded = b64decode(encoded.encode("ascii"), validate=True)
        if len(decoded) == 32:
            return decoded
    except (binascii.Error, UnicodeEncodeError):
        pass
    if len(stripped) == 64 and all(character in "0123456789abcdefABCDEF" for character in stripped):
        return bytes.fromhex(stripped)
    raw = stripped.encode("utf-8")
    if len(raw) == 32:
        return raw
    raise ArtifactDecryptionError("Artifact encryption key must decode to 32 bytes for AES-256-GCM")


def _download_large_artifact_strategy() -> str:
    strategy = os.getenv("AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_STRATEGY", "include").strip().lower()
    return strategy if strategy in {"include", "reference-only"} else "include"


def _download_large_artifact_threshold() -> int:
    raw_value = os.getenv("AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_BYTES", str(100 * 1024 * 1024))
    try:
        parsed = int(raw_value)
    except ValueError:
        return 100 * 1024 * 1024
    return max(0, parsed)
