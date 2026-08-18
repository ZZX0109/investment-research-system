from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from investment_research.training.active_snapshot_guard import (
    ActiveSnapshotInputError,
    assert_training_sources,
    require_active_snapshot,
    require_training_snapshot_gate,
)
from investment_research.training.snapshot_landing import (
    ResearchSnapshotManifest,
    activate_snapshot,
    build_file_record,
    create_landing_run,
)


def _activate(tmp_path: Path):
    data_root = tmp_path / "data"
    landing = create_landing_run(data_root, "download-1")
    payload = landing / "pit" / "bars.parquet"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"immutable-pit")
    record = build_file_record(
        landing,
        "pit/bars.parquet",
        dataset="daily_bars_raw",
        provider="fixture",
        metadata={
            "published_at_coverage": 1.0,
            "available_at_coverage": 1.0,
            "collected_at_coverage": 1.0,
            "revision_coverage": 1.0,
            "revision_id": "rev-1",
            "quality_status": "complete",
        },
    )
    manifest = ResearchSnapshotManifest(
        run_id="download-1",
        snapshot_id="snapshot-1",
        created_at=datetime.now(timezone.utc),
        source_root=str(landing),
        files=[record],
        file_success_count=1,
    ).model_copy(update={"status": "validated"})
    activate_snapshot(data_root, landing, manifest)
    return data_root


def test_external_sample_index_must_bind_to_active_snapshot(tmp_path: Path) -> None:
    data_root = _activate(tmp_path)
    active = require_active_snapshot(data_root)
    child = tmp_path / "sample.json"
    child.write_text(
        json.dumps({
            "data_snapshot_id": active.snapshot_id,
            "data_snapshot_manifest_hash": active.manifest_hash,
        }),
        encoding="utf-8",
    )
    index = tmp_path / "samples.json"
    index.write_text(json.dumps({"sample_manifests": [str(child)]}), encoding="utf-8")
    assert_training_sources(active, index, tmp_path / "derived-parquet")


def test_sample_index_rejects_stale_snapshot(tmp_path: Path) -> None:
    data_root = _activate(tmp_path)
    active = require_active_snapshot(data_root)
    child = tmp_path / "sample.json"
    child.write_text(
        json.dumps({
            "data_snapshot_id": "old-snapshot",
            "data_snapshot_manifest_hash": active.manifest_hash,
        }),
        encoding="utf-8",
    )
    index = tmp_path / "samples.json"
    index.write_text(json.dumps({"sample_manifests": [str(child)]}), encoding="utf-8")
    with pytest.raises(ActiveSnapshotInputError, match="snapshot_mismatch"):
        assert_training_sources(active, index, tmp_path / "derived-parquet")


def test_direct_external_samples_are_rejected(tmp_path: Path) -> None:
    data_root = _activate(tmp_path)
    active = require_active_snapshot(data_root)
    external = tmp_path / "outside.parquet"
    external.write_bytes(b"not-active")
    with pytest.raises(ActiveSnapshotInputError, match="outside_active_snapshot"):
        assert_training_sources(active, external, tmp_path / "derived-parquet")


def test_active_snapshot_rechecks_file_hash_before_training(tmp_path: Path) -> None:
    data_root = _activate(tmp_path)
    payload = data_root / "snapshots" / "snapshot-1" / "pit" / "bars.parquet"
    payload.write_bytes(b"tampered")
    with pytest.raises(ActiveSnapshotInputError, match="sha256_mismatch"):
        require_active_snapshot(data_root)


def test_training_snapshot_gate_requires_explicit_pit_audit(tmp_path: Path) -> None:
    active = require_active_snapshot(_activate(tmp_path))
    with pytest.raises(ActiveSnapshotInputError, match="pit_leakage_evidence_not_declared"):
        require_training_snapshot_gate(active)


def test_research_only_training_can_report_gate_reasons_without_passing(tmp_path: Path) -> None:
    active = require_active_snapshot(_activate(tmp_path))
    result = require_training_snapshot_gate(active, allow_research_only=True)
    assert result.passed is False
    assert "pit_leakage_evidence_not_declared" in result.reasons


def test_sample_manifest_in_landing_is_rejected_even_when_bound(tmp_path: Path) -> None:
    data_root = _activate(tmp_path)
    active = require_active_snapshot(data_root)
    landing = data_root / "landing" / "download-2"
    landing.mkdir(parents=True)
    sample = landing / "samples.json"
    sample.write_text(json.dumps({
        "data_snapshot_id": active.snapshot_id,
        "data_snapshot_manifest_hash": active.manifest_hash,
    }), encoding="utf-8")
    with pytest.raises(ActiveSnapshotInputError, match="samples_in_downloader_landing"):
        assert_training_sources(active, sample, tmp_path / "derived-parquet")


def test_child_manifest_list_cannot_point_into_landing(tmp_path: Path) -> None:
    data_root = _activate(tmp_path)
    active = require_active_snapshot(data_root)
    landing = data_root / "landing" / "download-2"
    landing.mkdir(parents=True)
    child = landing / "child.json"
    child.write_text(json.dumps({
        "data_snapshot_id": active.snapshot_id,
        "data_snapshot_manifest_hash": active.manifest_hash,
    }), encoding="utf-8")
    index = tmp_path / "samples.json"
    index.write_text(json.dumps({"sample_manifests": [str(child)]}), encoding="utf-8")
    with pytest.raises(ActiveSnapshotInputError, match="sample_manifest_in_downloader_landing"):
        assert_training_sources(active, index, tmp_path / "derived-parquet")


@pytest.mark.parametrize("tree_name", ["raw", "standard", "pit", "active"])
def test_object_store_cannot_use_mutable_data_tree(tmp_path: Path, tree_name: str) -> None:
    data_root = _activate(tmp_path)
    active = require_active_snapshot(data_root)
    sample_manifest = tmp_path / "sample.json"
    sample_manifest.write_text(json.dumps({
        "data_snapshot_id": active.snapshot_id,
        "data_snapshot_manifest_hash": active.manifest_hash,
    }), encoding="utf-8")
    mutable_store = data_root / tree_name
    mutable_store.mkdir(parents=True)
    with pytest.raises(ActiveSnapshotInputError, match="object_store_in_mutable_data_tree"):
        assert_training_sources(active, sample_manifest, mutable_store)
