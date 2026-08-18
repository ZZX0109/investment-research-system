from pathlib import Path
from datetime import datetime, timezone

from investment_research.training.artifacts import (
    ArtifactIndex,
    discover_local_references,
    append_to_index,
    invalidate_artifacts_for_plan,
    register_artifact,
    validate_index,
)


def test_artifact_index_discovers_local_refs_and_ignores_external_urls(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    target = root / "predictions.parquet"
    target.write_bytes(b"predictions")
    report = root / "evaluation.json"
    report.write_text(
        '{"prediction_artifact": {"ref": "predictions.parquet"}, "source_ref": "https://example.com/source"}',
        encoding="utf-8",
    )

    assert discover_local_references(root, report) == ["predictions.parquet"]
    record = register_artifact(root, report, kind="evaluation")
    assert record.references == ["predictions.parquet"]


def test_artifact_index_hashes_and_detects_tampering(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    payload = root / "predictions.parquet"
    payload.write_bytes(b"compressed-predictions")
    record = register_artifact(root, payload, kind="predictions")
    index = append_to_index(tmp_path / "index.json", record)
    assert isinstance(index, ArtifactIndex)
    assert validate_index(root, index) == []
    payload.write_bytes(b"tampered")
    assert any(item.startswith("size_mismatch") or item.startswith("hash_mismatch") for item in validate_index(root, index))


def test_artifact_index_rejects_dangling_references(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    payload = root / "report.json"
    payload.write_text("{}", encoding="utf-8")
    record = register_artifact(root, payload, kind="report", references=["missing-model.json"])
    index = ArtifactIndex(generated_at=datetime.now(timezone.utc), artifacts=[record])
    assert "dangling_reference:" in "\n".join(validate_index(root, index))


def test_incremental_plan_marks_only_lineage_matched_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    affected_path = root / "affected.json"
    unaffected_path = root / "unaffected.json"
    affected_path.write_text("affected", encoding="utf-8")
    unaffected_path.write_text("unaffected", encoding="utf-8")
    affected = register_artifact(
        root,
        affected_path,
        kind="feature",
        metadata={"symbol": "600519.SH", "start_date": "2024-01-01", "end_date": "2024-03-31"},
    )
    unaffected = register_artifact(
        root,
        unaffected_path,
        kind="feature",
        metadata={"symbol": "000001.SZ", "start_date": "2024-01-01", "end_date": "2024-03-31"},
    )
    index = ArtifactIndex(generated_at=datetime.now(timezone.utc), artifacts=[affected, unaffected])
    plan = {
        "plan_hash": "a" * 64,
        "plan": {
            "affected_symbols": ["600519.SH"],
            "feature_ranges": {"600519.SH": ["2024-01-15", "2024-02-15"]},
            "label_ranges": {"600519.SH": ["2023-01-01", "2024-01-31"]},
            "invalidated_snapshot_ids": [],
            "invalidated_model_versions": [],
        },
    }
    updated, ids = invalidate_artifacts_for_plan(index, plan)
    assert ids == [affected.artifact_id]
    assert updated.artifacts[0].lifecycle == "rebuild_required"
    assert updated.artifacts[1].lifecycle == "active"
