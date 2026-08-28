from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_sample_batch_merge_requires_one_snapshot_and_promotes_complete_set(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    root = tmp_path / "artifacts"
    root.mkdir()
    snapshot_id = "research-cn-close_confirmed-2025-01-01-abc123"
    snapshot_hash = "a" * 64
    equity_cohort = root / "equity.json"
    etf_cohort = root / "etf.json"
    equity_cohort.write_text(json.dumps({"members": [{"symbol": "600000"}]}), encoding="utf-8")
    etf_cohort.write_text(json.dumps({"members": [{"symbol": "510300"}]}), encoding="utf-8")
    base = root / "base.json"
    base.write_text(json.dumps({
        "status": "research_only", "data_tier": "research_pit", "as_of": "2025-01-01",
        "failures": [], "cohort_refs": {
            "cn_equity_core": str(equity_cohort), "cn_etf_benchmark": str(etf_cohort),
        }, "contexts": {"close_confirmed": {
            "snapshot_id": snapshot_id, "snapshot_hash": snapshot_hash,
            "sample_manifests": {}, "leakage_report_ref": "old.json",
        }},
    }), encoding="utf-8")

    batch_refs = {}
    for cohort, symbol in (("cn_equity_core", "600000"), ("cn_etf_benchmark", "510300")):
        manifest = root / f"{symbol}.json"
        manifest.write_text(json.dumps({
            "symbol": symbol, "trade_year": 2025,
            "market_snapshot_id": snapshot_id, "market_snapshot_hash": snapshot_hash,
        }), encoding="utf-8")
        batch_refs[cohort] = [str(manifest)]
    batch = root / "batch.json"
    batch.write_text(json.dumps({
        "status": "research_only", "data_tier": "research_pit", "contexts": {
            "close_confirmed": {
                "snapshot_id": snapshot_id, "snapshot_hash": snapshot_hash,
                "sample_manifests": batch_refs,
            }
        },
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(project / "scripts/merge_cn_research_sample_batches.py"),
         "--base-index", str(base), "--batch-indexes", str(batch)],
        cwd=project, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    merged = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
    assert merged["training_blocked"] is False
    assert len(merged["contexts"]["close_confirmed"]["sample_manifests"]["cn_equity_core"]) == 1
    assert (root / "latest.json").is_file()

    bad_manifest = root / "bad.json"
    bad_manifest.write_text(json.dumps({
        "symbol": "600000", "trade_year": 2026,
        "market_snapshot_id": snapshot_id, "market_snapshot_hash": "b" * 64,
    }), encoding="utf-8")
    bad_batch = root / "bad-batch.json"
    bad_batch.write_text(json.dumps({
        "status": "research_only", "data_tier": "research_pit", "contexts": {
            "close_confirmed": {
                "snapshot_id": snapshot_id, "snapshot_hash": snapshot_hash,
                "sample_manifests": {"cn_equity_core": [str(bad_manifest)]},
            }
        },
    }), encoding="utf-8")
    rejected = subprocess.run(
        [sys.executable, str(project / "scripts/merge_cn_research_sample_batches.py"),
         "--base-index", str(base), "--batch-indexes", str(bad_batch)],
        cwd=project, text=True, capture_output=True, check=False,
    )
    assert rejected.returncode != 0
    assert "snapshot mismatch" in rejected.stderr
