from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys

from investment_research.training.artifacts import ArtifactIndex, register_artifact, write_index


def test_prune_dry_run_protects_incoming_references_and_rebuild_required(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    prediction = root / "predictions.parquet"
    prediction.write_bytes(b"predictions")
    report = root / "evaluation.json"
    report.write_text(json.dumps({"prediction_ref": "predictions.parquet"}), encoding="utf-8")
    stale = root / "stale.json"
    stale.write_text("stale", encoding="utf-8")
    invalidated = root / "invalidated.json"
    invalidated.write_text("invalidated", encoding="utf-8")
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    records = [
        register_artifact(root, prediction, kind="predictions", retention_until=expired),
        register_artifact(root, report, kind="evaluation", retention_until=expired),
        register_artifact(root, stale, kind="scratch", retention_until=expired),
        register_artifact(root, invalidated, kind="feature", retention_until=expired),
    ]
    records[-1] = records[-1].model_copy(update={"lifecycle": "rebuild_required"})
    index_path = tmp_path / "index.json"
    write_index(ArtifactIndex(generated_at=datetime.now(timezone.utc), artifacts=records), index_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/prune_training_artifacts.py",
            "--root", str(root),
            "--index", str(index_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "stale.json" in result.stdout
    assert "predictions.parquet" not in result.stdout
    assert "invalidated.json" not in result.stdout
    assert prediction.exists()
    assert invalidated.exists()
