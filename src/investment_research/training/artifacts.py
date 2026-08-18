"""Content-addressed indexes for research artifacts.

The index is deliberately file-backed so it can be copied with a research
run.  A summary may reference a large prediction file, but never embeds its
rows.  Index updates are atomic and validation is fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


class TrainingArtifactStore:
    """Backward-compatible JSON store used by the legacy experiment CLI.

    New long-term jobs use :class:`ArtifactIndex`; this small adapter keeps
    the existing experiment command isolated and atomic while migrating.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_experiment_report(self, report: Any, *, name: str = "experiment") -> Path:
        return self._write_json(f"{name}.json", report)

    def write_model_card(self, card: Any, *, name: str) -> Path:
        return self._write_json(f"model_card_{name}.json", card)

    def _write_json(self, filename: str, value: Any) -> Path:
        path = self.root / filename
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        if hasattr(value, "__dict__") and not isinstance(value, (dict, list, str, int, float, bool, type(None))):
            payload = value.__dict__
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path


class ArtifactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    created_at: datetime
    retention_until: datetime | None = None
    references: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    lifecycle: Literal["active", "rebuild_required", "retired"] = "active"
    invalidation_plan_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None


class ArtifactIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "research-artifact-index-v1"
    generated_at: datetime
    artifacts: list[ArtifactRecord] = Field(default_factory=list)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_artifact(
    root: Path,
    path: Path,
    *,
    kind: str,
    artifact_id: str | None = None,
    references: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    retention_until: datetime | None = None,
) -> ArtifactRecord:
    """Create a record only for a regular file below ``root``."""
    root = root.resolve()
    path = path.resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError(f"artifact must be a file below root: {path}")
    relative = path.relative_to(root).as_posix()
    discovered = discover_local_references(root, path) if references is None else list(references)
    return ArtifactRecord(
        artifact_id=artifact_id or sha256_file(path),
        relative_path=relative,
        kind=kind,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        created_at=datetime.now(timezone.utc),
        retention_until=retention_until,
        references=discovered,
        metadata=dict(metadata or {}),
    )


def write_index(index: ArtifactIndex, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(index.model_dump_json(indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def read_index(path: Path) -> ArtifactIndex:
    return ArtifactIndex.model_validate_json(path.read_text(encoding="utf-8"))


def validate_index(root: Path, index: ArtifactIndex) -> list[str]:
    """Return missing/hash/duplicate/reference errors without mutating files."""
    errors: list[str] = []
    ids: set[str] = set()
    paths: set[str] = set()
    references: list[tuple[str, str]] = []
    for item in index.artifacts:
        if item.artifact_id in ids:
            errors.append(f"duplicate_artifact_id:{item.artifact_id}")
        ids.add(item.artifact_id)
        if item.relative_path in paths:
            errors.append(f"duplicate_artifact_path:{item.relative_path}")
        paths.add(item.relative_path)
        references.extend((item.artifact_id, reference) for reference in item.references)
        path = (root / item.relative_path).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            errors.append(f"missing_artifact:{item.relative_path}")
            continue
        if path.stat().st_size != item.size_bytes:
            errors.append(f"size_mismatch:{item.relative_path}")
        if sha256_file(path) != item.sha256:
            errors.append(f"hash_mismatch:{item.relative_path}")
    for owner, reference in references:
        if reference not in ids and reference not in paths:
            errors.append(f"dangling_reference:{owner}:{reference}")
    return sorted(set(errors))


def discover_local_references(root: Path, path: Path) -> list[str]:
    """Extract local artifact references from a JSON artifact.

    References are intentionally discovered from conventional ``*_ref`` and
    ``ref`` keys only.  External URLs/object-store URIs remain external
    evidence and are not incorrectly reported as missing local files.
    """
    if path.suffix.lower() != ".json":
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    values: list[str] = []

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and key is not None and (key == "ref" or key.endswith("_ref")):
            parsed = urlparse(value)
            if not parsed.scheme and value and value not in values:
                values.append(value)

    walk(payload)
    resolved: list[str] = []
    root = root.resolve()
    for value in values:
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
        else:
            # Accept both root-relative references and project-style
            # ``artifacts/...`` references when the index root is artifacts/.
            options = [candidate]
            parts = candidate.parts
            if parts and parts[0] == root.name:
                options.append(Path(*parts[1:]))
            relative = next(
                (item.as_posix() for item in options if (root / item).is_file()),
                value,
            )
        if relative not in resolved:
            resolved.append(relative)
    return resolved


def append_to_index(path: Path, record: ArtifactRecord) -> ArtifactIndex:
    """Atomically append or replace one artifact record."""
    if path.is_file():
        index = read_index(path)
        artifacts = [item for item in index.artifacts if item.artifact_id != record.artifact_id]
    else:
        artifacts = []
    index = ArtifactIndex(generated_at=datetime.now(timezone.utc), artifacts=[*artifacts, record])
    write_index(index, path)
    return index


def invalidate_artifacts_for_plan(
    index: ArtifactIndex,
    plan_payload: dict[str, Any],
    *,
    invalidated_at: datetime | None = None,
) -> tuple[ArtifactIndex, list[str]]:
    """Mark only artifacts affected by a verified incremental rebuild plan.

    This is deliberately non-destructive: old files and the active snapshot
    remain available for replay, while downstream consumers can refuse
    ``rebuild_required`` records until a replacement artifact is registered.
    Matching relies on explicit metadata (symbol/date/snapshot/model); an
    artifact without lineage metadata is not invalidated by guesswork.
    """
    plan_hash = str(plan_payload.get("plan_hash") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise ValueError("incremental rebuild plan hash is missing or invalid")
    plan = plan_payload.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("incremental rebuild plan payload is missing plan")
    affected_symbols = {str(value) for value in plan.get("affected_symbols", []) if value}
    invalidated_snapshots = {str(value) for value in plan.get("invalidated_snapshot_ids", []) if value}
    invalidated_models = {str(value) for value in plan.get("invalidated_model_versions", []) if value}
    feature_ranges = _plan_ranges(plan.get("feature_ranges"))
    label_ranges = _plan_ranges(plan.get("label_ranges"))
    changed_at = invalidated_at or datetime.now(timezone.utc)
    affected: list[str] = []
    updated: list[ArtifactRecord] = []
    for record in index.artifacts:
        metadata = record.metadata
        symbol_values = metadata.get("symbols", metadata.get("symbol"))
        symbols = {str(value) for value in symbol_values} if isinstance(symbol_values, (list, tuple, set)) else ({str(symbol_values)} if symbol_values else set())
        snapshot = str(metadata.get("snapshot_id") or metadata.get("data_snapshot_id") or "")
        model = str(metadata.get("model_version") or "")
        record_dates = _record_date_range(metadata)
        symbol_hit = bool(symbols & affected_symbols)
        snapshot_hit = bool(snapshot and snapshot in invalidated_snapshots)
        model_hit = bool(model and model in invalidated_models)
        range_hit = False
        if symbol_hit and record_dates is not None:
            intervals = [
                interval
                for symbol in symbols & affected_symbols
                for interval in (feature_ranges.get(symbol), label_ranges.get(symbol))
                if interval is not None
            ]
            range_hit = any(_ranges_overlap(record_dates, interval) for interval in intervals)
        elif symbol_hit:
            # A symbol-scoped artifact with no date metadata is still unsafe
            # after any revision for that symbol; do not leave it reusable.
            range_hit = True
        if not (symbol_hit and range_hit or snapshot_hit or model_hit):
            updated.append(record)
            continue
        affected.append(record.artifact_id)
        updated.append(record.model_copy(update={
            "lifecycle": "rebuild_required",
            "invalidation_plan_hash": plan_hash,
            "invalidated_at": changed_at,
            "invalidation_reason": "data_revision_requires_downstream_rebuild",
        }))
    return index.model_copy(update={"generated_at": changed_at, "artifacts": updated}), sorted(affected)


def _plan_ranges(value: Any) -> dict[str, tuple[date, date]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, tuple[date, date]] = {}
    for symbol, raw in value.items():
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            continue
        try:
            result[str(symbol)] = (date.fromisoformat(str(raw[0])[:10]), date.fromisoformat(str(raw[1])[:10]))
        except ValueError:
            continue
    return result


def _record_date_range(metadata: dict[str, Any]) -> tuple[date, date] | None:
    start = metadata.get("start_date") or metadata.get("as_of_start")
    end = metadata.get("end_date") or metadata.get("as_of_end")
    if not start or not end:
        return None
    try:
        return date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    except ValueError:
        return None


def _ranges_overlap(left, right) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]
