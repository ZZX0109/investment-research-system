from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def test_cn_research_demo_dry_run_declares_fail_closed_evidence_stages() -> None:
    project = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(project / "scripts/run_cn_research_demo.py"), "--dry-run"],
        cwd=project,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["data_tier"] == "research_pit"
    assert payload["deployment_ready"] is False
    assert payload["stages"] == [
        "incremental_public_collection_and_raw_hash",
        "quality_audit_fixed_cohort_and_snapshot",
        "same_fold_four_task_model_comparison",
        "research_roster_and_report_hash_freeze",
        "roster_bound_hash_verified_inference",
        "immutable_research_shadow_freeze",
    ]
