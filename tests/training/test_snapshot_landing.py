from pathlib import Path
import json

import pytest

from investment_research.training.snapshot_landing import (
    ResearchSnapshotManifest,
    activate_snapshot,
    build_file_record,
    create_landing_run,
    sha256_file,
    validate_landing_manifest,
    evaluate_snapshot_gate,
    load_active_manifest,
    SnapshotGateConfig,
    write_manifest,
)


def test_prepare_snapshot_requires_completed_source_handoff(tmp_path):
    from scripts.prepare_research_snapshot import _assert_source_ready

    source = tmp_path / "download-output"
    source.mkdir()
    with pytest.raises(SystemExit, match="source-ready-manifest"):
        _assert_source_ready(source, tmp_path / "var", None)


def test_prepare_snapshot_rejects_protected_source_even_with_marker(tmp_path):
    from scripts.prepare_research_snapshot import _assert_source_ready

    data_root = tmp_path / "var"
    source = data_root / "raw"
    source.mkdir(parents=True)
    marker = tmp_path / "ready.json"
    marker.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="protected"):
        _assert_source_ready(source, data_root, marker)


def _manifest(landing: Path) -> ResearchSnapshotManifest:
    data = landing / "prices" / "bars.json"
    data.parent.mkdir(parents=True)
    data.write_text('{"symbol":"000001","trade_date":"2026-08-01"}\n', encoding="utf-8")
    record = build_file_record(
        landing,
        "prices/bars.json",
        dataset="daily_bars_raw",
        provider="test-provider",
        metadata={
            "row_count": 1,
            "symbol": "000001",
            "start_date": "2026-08-01",
            "end_date": "2026-08-01",
            "published_at_coverage": 1.0,
            "available_at_coverage": 1.0,
            "revision_coverage": 1.0,
            "revision_id": "rev-1",
            "raw_hash": "a" * 64,
            "quality_status": "complete",
        },
    )
    return ResearchSnapshotManifest(
        run_id="download-1",
        snapshot_id="snapshot-1",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        source_root=str(landing),
        files=[record],
        target_symbol_count=1,
        observed_symbol_count=1,
        file_success_count=1,
    )


def test_manifest_hash_and_validation(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing)
    assert validate_landing_manifest(landing, manifest) == []
    assert sha256_file(landing / "prices/bars.json") == manifest.files[0].sha256
    assert manifest.files[0].revision_id == "rev-1"
    assert manifest.files[0].raw_hash == "a" * 64
    write_manifest(manifest, landing / "manifest.json")


def test_build_file_record_defaults_raw_lineage_to_landed_hash(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    path = landing / "events.json"
    path.write_text('{"symbol":"000001","trade_date":"2026-08-01"}\n', encoding="utf-8")
    record = build_file_record(
        landing, "events.json", dataset="events", provider="test-provider",
        metadata={"quality_status": "complete", "published_at_coverage": 1.0, "available_at_coverage": 1.0, "revision_coverage": 1.0, "revision_id": "rev-1"},
    )
    assert record.raw_hash == record.sha256


def test_validation_rejects_tampered_or_missing_file(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing)
    (landing / "prices/bars.json").write_text("tampered", encoding="utf-8")
    errors = validate_landing_manifest(landing, manifest)
    assert "size mismatch: prices/bars.json" in errors
    assert "sha256 mismatch: prices/bars.json" in errors


def test_validation_requires_file_quality_counts_to_match(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing)
    mismatched = manifest.model_copy(update={"file_success_count": 0})
    assert "file quality counts do not match manifest files" in validate_landing_manifest(landing, mismatched)


def test_activation_moves_run_and_swaps_pointer_atomically(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    landing = create_landing_run(data_root, "download-1")
    manifest = _manifest(landing).model_copy(update={"status": "validated"})
    pointer = activate_snapshot(data_root, landing, manifest)
    assert pointer == data_root / "active.json"
    assert not landing.exists()
    snapshot = data_root / "snapshots" / "snapshot-1"
    assert snapshot.is_dir()
    assert pointer.is_file()
    payload = pointer.read_text(encoding="utf-8")
    assert "snapshot-1" in payload
    assert ResearchSnapshotManifest.model_validate_json(
        (snapshot / "manifest.json").read_text(encoding="utf-8")
    ).status == "active"
    loaded = load_active_manifest(data_root)
    assert loaded.snapshot_id == "snapshot-1"


def test_activation_rejects_unvalidated_manifest(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    landing = create_landing_run(data_root, "download-1")
    with pytest.raises(ValueError, match="validated landing manifest"):
        activate_snapshot(data_root, landing, _manifest(landing))


def test_gate_blocks_unmature_labels_and_missing_dataset(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing)
    blocked = evaluate_snapshot_gate(manifest, labels_mature=False)
    assert not blocked.passed
    assert "snapshot_not_active" in blocked.reasons
    assert "required_datasets_missing:daily_bars_qfq" in blocked.reasons
    assert "labels_not_mature" in blocked.reasons


def test_gate_requires_declared_industry_coverage(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing).model_copy(update={"status": "active"})
    result = evaluate_snapshot_gate(manifest)
    assert not result.passed
    assert "industry_coverage_not_declared" in result.reasons


def test_gate_requires_verifiable_pit_leakage_evidence(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing).model_copy(update={"status": "active"})
    result = evaluate_snapshot_gate(manifest, config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}))
    assert "pit_leakage_evidence_not_declared" in result.reasons


def test_gate_accepts_content_addressed_zero_pit_leakage_report(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    audit = tmp_path / "pit-leakage.json"
    audit.write_text(json.dumps({"schema_version": "pit-audit-v1", "research_error_count": 0}), encoding="utf-8")
    digest = sha256_file(audit)
    manifest = _manifest(landing).model_copy(update={
        "status": "active",
        "pit_leakage_error_count": 0,
        "pit_leakage_audit_ref": str(audit),
        "pit_leakage_audit_sha256": digest,
    })
    result = evaluate_snapshot_gate(manifest, config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}))
    assert "pit_leakage_evidence_not_declared" not in result.reasons
    assert result.pit_leakage_error_count == 0


def test_gate_rejects_tampered_pit_leakage_report(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    audit = tmp_path / "pit-leakage.json"
    audit.write_text(json.dumps({"error_count": 0}), encoding="utf-8")
    digest = sha256_file(audit)
    audit.write_text(json.dumps({"error_count": 1}), encoding="utf-8")
    manifest = _manifest(landing).model_copy(update={
        "status": "active",
        "pit_leakage_error_count": 0,
        "pit_leakage_audit_ref": str(audit),
        "pit_leakage_audit_sha256": digest,
    })
    result = evaluate_snapshot_gate(manifest, config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}))
    assert "pit_leakage_audit_hash_mismatch" in result.reasons


def test_manifest_requires_complete_pit_leakage_evidence_fields() -> None:
    with pytest.raises(ValueError, match="PIT leakage evidence"):
        ResearchSnapshotManifest.model_validate({
            "run_id": "run-1",
            "snapshot_id": "snapshot-1",
            "created_at": "2026-08-17T00:00:00Z",
            "source_root": "/tmp/landing",
            "pit_leakage_error_count": 0,
        })


def test_gate_rejects_degraded_required_dataset(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing).model_copy(update={"status": "active"})
    degraded = manifest.model_copy(update={
        "files": [manifest.files[0].model_copy(update={"quality_status": "degraded", "missing_reason": "unverified"})],
    })
    result = evaluate_snapshot_gate(degraded, config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}))
    assert "required_datasets_not_complete:daily_bars_raw" in result.reasons


def test_gate_rejects_manifest_file_quality_counts(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing).model_copy(update={
        "status": "active",
        "file_success_count": 0,
        "file_failure_count": 0,
        "file_degraded_count": 1,
    })
    result = evaluate_snapshot_gate(manifest, config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}))
    assert "snapshot_file_quality_degraded" in result.reasons


def test_gate_requires_declared_financial_coverage(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing).model_copy(update={"status": "active"})
    result = evaluate_snapshot_gate(
        manifest,
        config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}, minimum_financial_coverage=0.95),
    )
    assert "financial_coverage_not_declared" in result.reasons


def test_gate_rejects_individual_low_coverage_financial_fields(tmp_path: Path) -> None:
    landing = create_landing_run(tmp_path / "data", "download-1")
    manifest = _manifest(landing).model_copy(update={
        "status": "active",
        "financial_target_field_count": 100,
        "financial_observed_field_count": 99,
        "financial_low_coverage_fields": ["profit.gpMargin"],
    })
    result = evaluate_snapshot_gate(
        manifest,
        config=SnapshotGateConfig(required_datasets={"daily_bars_raw"}, minimum_financial_coverage=0.95),
    )
    assert any(reason.startswith("financial_fields_below_95.00%:") for reason in result.reasons)


def test_degraded_file_requires_reason() -> None:
    with pytest.raises(ValueError, match="missing_reason"):
        ResearchSnapshotManifest.model_validate({
            "run_id": "run-1",
            "snapshot_id": "snapshot-1",
            "created_at": "2026-08-17T00:00:00Z",
            "source_root": "/tmp/landing",
            "files": [{
                "dataset": "events",
                "provider": "provider",
                "relative_path": "events.json",
                    "sha256": "0" * 64,
                    "raw_hash": "0" * 64,
                "size_bytes": 1,
                "quality_status": "degraded",
            }],
        })


def test_degraded_event_file_requires_semantic_reason_code() -> None:
    with pytest.raises(ValueError, match="event files require missing_reason_code"):
        ResearchSnapshotManifest.model_validate({
            "run_id": "run-1",
            "snapshot_id": "snapshot-1",
            "created_at": "2026-08-17T00:00:00Z",
            "source_root": "/tmp/landing",
            "files": [{
                "dataset": "events",
                "provider": "provider",
                "relative_path": "events.json",
                "sha256": "0" * 64,
                "raw_hash": "0" * 64,
                "size_bytes": 1,
                "quality_status": "degraded",
                "missing_reason": "provider has no historical coverage",
            }],
        })
