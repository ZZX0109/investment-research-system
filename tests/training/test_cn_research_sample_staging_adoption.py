from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_legacy_sample_adoption_requires_explicit_ack_and_writes_marker(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    root = tmp_path / "artifacts"
    base = root / "base.json"
    base.parent.mkdir(parents=True)
    snapshot_hash = "a" * 64
    base.write_text(json.dumps({
        "status": "research_only", "data_tier": "research_pit",
        "contexts": {"close_confirmed": {
            "snapshot_id": "snapshot-1", "snapshot_hash": snapshot_hash,
        }},
    }), encoding="utf-8")
    sample_root = root / "staging"
    symbol_root = sample_root / "samples" / "close_confirmed" / "cn_equity_core" / "600000"
    symbol_root.mkdir(parents=True)
    (symbol_root / "2025.json").write_text(json.dumps({
        "symbol": "600000", "data_tier": "research_pit", "row_count": 10,
        "sample_parquet_ref": "file-object://sample",
        "market_snapshot_id": "snapshot-1", "market_snapshot_hash": snapshot_hash,
    }), encoding="utf-8")

    rejected = subprocess.run(
        [sys.executable, str(project / "scripts/adopt_cn_research_sample_staging.py"),
         "--base-index", str(base), "--sample-root", str(sample_root)],
        cwd=project, text=True, capture_output=True, check=False,
    )
    assert rejected.returncode != 0
    assert "--allow-unmarked" in rejected.stderr

    completed = subprocess.run(
        [sys.executable, str(project / "scripts/adopt_cn_research_sample_staging.py"),
         "--base-index", str(base), "--sample-root", str(sample_root), "--allow-unmarked"],
        cwd=project, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    marker = json.loads((symbol_root / ".complete.json").read_text(encoding="utf-8"))
    assert marker["completion_evidence"] == "legacy_manifest_scan"
    assert marker["manifest_count"] == 1
    report = json.loads(Path(completed.stdout.strip()).read_text(encoding="utf-8"))
    assert report["training_blocked"] is True
