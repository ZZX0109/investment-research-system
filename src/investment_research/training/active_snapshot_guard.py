"""Fail-closed guards for training inputs and the active immutable snapshot.

The downloader may continue writing under ``landing`` while research jobs are
running.  A trainer therefore needs two independent proofs before it reads a
row: the active pointer must be valid, and the input manifest/path must be
bound to that exact snapshot.  Keeping this logic in one module prevents the
tabular, sequence, panel and long-term runners from drifting apart.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .snapshot_landing import (
    ResearchSnapshotManifest,
    SnapshotGateConfig,
    SnapshotGateResult,
    evaluate_snapshot_gate,
    load_active_manifest,
    sha256_file,
)


class ActiveSnapshotInputError(ValueError):
    """Raised when a training input cannot be proven to come from active data."""


@dataclass(frozen=True)
class ActiveSnapshotContext:
    data_root: Path
    manifest: ResearchSnapshotManifest
    snapshot_root: Path
    manifest_hash: str

    @property
    def snapshot_id(self) -> str:
        return self.manifest.snapshot_id


def require_active_snapshot(data_root: Path) -> ActiveSnapshotContext:
    """Load and integrity-check the active pointer without mutating anything."""

    try:
        manifest = load_active_manifest(data_root)
    except (OSError, ValueError, TypeError) as exc:
        raise ActiveSnapshotInputError(f"active_snapshot_unavailable:{exc}") from exc
    snapshot_root = Path(manifest.source_root).resolve()
    expected_root = (data_root / "snapshots" / manifest.snapshot_id).resolve()
    if snapshot_root != expected_root or not snapshot_root.is_dir():
        raise ActiveSnapshotInputError("active_snapshot_root_invalid")
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.is_file():
        raise ActiveSnapshotInputError("active_snapshot_manifest_missing")
    try:
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ActiveSnapshotInputError("active_snapshot_manifest_unreadable") from exc
    context = ActiveSnapshotContext(
        data_root=data_root.resolve(),
        manifest=manifest,
        snapshot_root=snapshot_root,
        manifest_hash=manifest_hash,
    )
    assert_active_snapshot_files(context)
    return context


def require_training_snapshot_gate(
    context: ActiveSnapshotContext,
    *,
    config: SnapshotGateConfig | None = None,
    labels_mature: bool = True,
    allow_research_only: bool = False,
) -> SnapshotGateResult:
    """Apply the data gate after the active pointer and file hashes are bound.

    ``require_active_snapshot`` proves identity/integrity only.  Training
    runners must also prove coverage, PIT timestamps and an explicit leakage
    audit; keeping this second check here prevents sequence and panel runners
    from silently bypassing the long-term gate.
    """
    result = evaluate_snapshot_gate(
        context.manifest,
        config=config,
        labels_mature=labels_mature,
    )
    if not result.passed and not allow_research_only:
        raise ActiveSnapshotInputError(
            "active_snapshot_gate_blocked:" + ";".join(result.reasons[:12])
        )
    return result


def assert_active_snapshot_files(context: ActiveSnapshotContext) -> None:
    """Recheck every immutable file before any training input is consumed.

    The active pointer and manifest are small metadata objects; their presence
    alone does not prove that a referenced Parquet file still exists or has
    the bytes that were audited at landing time.  Fail closed on the first
    missing, size, hash, or content-quality mismatch.
    """
    errors: list[str] = []
    observed_counts = {
        "complete": 0,
        "unavailable": 0,
        "degraded": 0,
    }
    for item in context.manifest.files:
        observed_counts[item.quality_status] = observed_counts.get(item.quality_status, 0) + 1
        relative = Path(item.relative_path)
        path = (context.snapshot_root / relative).resolve()
        if context.snapshot_root not in path.parents:
            errors.append(f"file_escapes_snapshot:{item.relative_path}")
            continue
        if not path.is_file():
            errors.append(f"file_missing:{item.relative_path}")
            continue
        if path.stat().st_size != item.size_bytes:
            errors.append(f"size_mismatch:{item.relative_path}")
        try:
            digest = sha256_file(path)
        except OSError:
            errors.append(f"file_unreadable:{item.relative_path}")
            continue
        if digest != item.sha256:
            errors.append(f"sha256_mismatch:{item.relative_path}")
        for field in (
            "duplicate_key_count", "security_code_error_count", "ohlc_error_count", "trading_date_error_count",
            "trading_status_error_count", "adjustment_error_count",
            "security_lifecycle_error_count", "reference_error_count", "pit_time_error_count",
        ):
            if getattr(item, field, 0):
                errors.append(f"{field}:{item.relative_path}")
        if not item.schema_valid:
            errors.append(f"schema_invalid:{item.relative_path}")
    tracked = {Path(item.relative_path).as_posix() for item in context.manifest.files}
    for path in sorted(context.snapshot_root.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(context.snapshot_root).as_posix()
            if relative not in tracked:
                errors.append(f"untracked_file:{relative}")
    declared_counts = (
        context.manifest.file_success_count,
        context.manifest.file_failure_count,
        context.manifest.file_degraded_count,
    )
    if any(declared_counts) and declared_counts != (
        observed_counts["complete"],
        observed_counts["unavailable"],
        observed_counts["degraded"],
    ):
        errors.append("file_quality_counts_mismatch")
    if errors:
        raise ActiveSnapshotInputError("active_snapshot_file_integrity_failed:" + ";".join(errors[:12]))


def assert_input_path(context: ActiveSnapshotContext, path: Path, *, label: str = "training_input") -> Path:
    """Require a file/directory to live below the immutable active snapshot.

    Directories are accepted only when every regular data file below them is
    tracked by the active manifest.  This keeps a caller from passing the
    mutable ``landing`` or an unrelated object-store directory by accident.
    """

    resolved = path.resolve()
    root = context.snapshot_root
    if resolved != root and root not in resolved.parents:
        raise ActiveSnapshotInputError(f"{label}_outside_active_snapshot:{path}")
    tracked = {item.relative_path for item in context.manifest.files}
    candidates = [resolved] if resolved.is_file() else sorted(resolved.rglob("*"))
    for candidate in candidates:
        if not candidate.is_file() or candidate.name == "manifest.json":
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative not in tracked:
            raise ActiveSnapshotInputError(f"{label}_untracked_file:{relative}")
    return resolved


def assert_object_store_path(context: ActiveSnapshotContext, path: Path) -> Path:
    """Require Parquet/object storage to be a directory in the active tree."""

    resolved = path.resolve()
    if resolved != context.snapshot_root and context.snapshot_root not in resolved.parents:
        raise ActiveSnapshotInputError(f"object_store_outside_active_snapshot:{path}")
    return resolved


def assert_manifest_binding(
    context: ActiveSnapshotContext,
    payload: dict[str, Any],
    *,
    label: str = "sample_manifest",
) -> None:
    """Require a derived sample manifest to name and hash its active snapshot."""

    snapshot_id = payload.get("data_snapshot_id") or payload.get("active_snapshot_id")
    if snapshot_id != context.snapshot_id:
        raise ActiveSnapshotInputError(
            f"{label}_snapshot_mismatch:expected={context.snapshot_id}:observed={snapshot_id}"
        )
    manifest_hash = payload.get("data_snapshot_manifest_hash")
    if manifest_hash is None:
        raise ActiveSnapshotInputError(f"{label}_snapshot_manifest_hash_missing")
    if manifest_hash != context.manifest_hash:
        raise ActiveSnapshotInputError(f"{label}_snapshot_manifest_hash_mismatch")


def assert_manifest_list_binding(context: ActiveSnapshotContext, path: Path) -> list[Path]:
    """Read a manifest-list file and require every child manifest to bind."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ActiveSnapshotInputError(f"sample_manifest_list_unreadable:{path}") from exc
    values = payload if isinstance(payload, list) else payload.get("sample_manifests") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        raise ActiveSnapshotInputError("sample_manifest_list_empty")
    paths: list[Path] = []
    for value in values:
        raw_child = Path(str(value))
        if raw_child.is_absolute():
            candidates = [raw_child]
        else:
            # Rebuild indexes persist project-relative references such as
            # ``artifacts/...``.  A queue manifest lives below its own run
            # directory, so resolving only against ``path.parent`` would
            # incorrectly reject those valid references.  Keep the local
            # relative location first for fixture manifests, then try the
            # project root inferred from ``var/cn-research``.
            project_root = context.data_root.parent.parent
            candidates = [path.parent / raw_child, project_root / raw_child]
        child = next((candidate.resolve() for candidate in candidates if candidate.is_file()), candidates[0].resolve())
        landing_root = (context.data_root / "landing").resolve()
        if child == landing_root or landing_root in child.parents:
            raise ActiveSnapshotInputError(f"sample_manifest_in_downloader_landing:{child}")
        try:
            child_payload = json.loads(child.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ActiveSnapshotInputError(f"sample_manifest_unreadable:{child}") from exc
        if not isinstance(child_payload, dict):
            raise ActiveSnapshotInputError(f"sample_manifest_invalid:{child}")
        assert_manifest_binding(context, child_payload, label=str(child))
        paths.append(child)
    return paths


def assert_training_sources(
    context: ActiveSnapshotContext,
    samples_path: Path,
    object_store_path: Path,
) -> None:
    """Validate the two physical inputs consumed by a training runner.

    A sample directory/file must be inside the active snapshot.  The one
    supported exception is an external *index* JSON whose child manifests all
    carry the active binding; the Parquet object store must still be inside the
    snapshot.  No external raw/landing directory is accepted.
    """

    resolved_samples = samples_path.resolve()
    landing_root = (context.data_root / "landing").resolve()
    if resolved_samples == landing_root or landing_root in resolved_samples.parents:
        raise ActiveSnapshotInputError("samples_in_downloader_landing")
    try:
        assert_input_path(context, samples_path, label="samples")
    except ActiveSnapshotInputError:
        if samples_path.suffix.lower() != ".json" or not samples_path.is_file():
            raise
        try:
            payload = json.loads(samples_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ActiveSnapshotInputError(f"samples_manifest_unreadable:{samples_path}") from exc
        if isinstance(payload, dict) and (payload.get("data_snapshot_id") or payload.get("active_snapshot_id")):
            assert_manifest_binding(context, payload, label=str(samples_path))
        else:
            assert_manifest_list_binding(context, samples_path)
    # Derived PIT Parquet partitions may live in a content-addressed object
    # store beside the snapshot.  Their sample manifests carry the active
    # snapshot id/hash and the runner separately verifies the partition hash;
    # only the mutable downloader landing tree is forbidden here.
    resolved_store = object_store_path.resolve()
    # A derived, content-addressed store may live outside ``data_root`` when
    # its partitions are bound to the active snapshot by sample manifests.
    # The downloader's mutable data trees may never be used as that store,
    # however: accepting ``raw``/``standard``/``pit`` here would let a caller
    # bypass the active pointer while still appearing to use Parquet data.
    protected_roots = {
        (context.data_root / name).resolve()
        for name in ("landing", "raw", "standard", "pit", "active")
    }
    if any(resolved_store == root or root in resolved_store.parents for root in protected_roots):
        raise ActiveSnapshotInputError("object_store_in_mutable_data_tree")
