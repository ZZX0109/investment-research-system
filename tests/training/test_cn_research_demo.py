from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from scripts.run_free_research_cycle import _shadow_coverage
from scripts.generate_cn_research_acceptance import _shadow_summary, _task_status


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


def test_shadow_freeze_uses_core_coverage_without_hiding_optional_gaps() -> None:
    assert _shadow_coverage({"coverage_ratio": 0.45, "core_feature_coverage": 1.0}) == 1.0
    assert _shadow_coverage({"coverage_ratio": 0.45}) == 0.45


def test_acceptance_shadow_summary_is_scoped_to_the_current_run(tmp_path: Path) -> None:
    current = tmp_path / "runs" / "current" / "equity"
    stale = tmp_path / "sessions" / "legacy"
    (current / "sessions" / "cn").mkdir(parents=True)
    stale.mkdir(parents=True)
    (current / "sessions" / "cn" / "one.json").write_text(
        json.dumps({"id": "one", "trade_date": "2026-07-21", "evidence_valid": True, "abstained": False})
    )
    (stale / "old.json").write_text(
        json.dumps({"id": "old", "trade_date": "2020-01-01", "evidence_valid": True, "abstained": True})
    )

    summary = _shadow_summary(
        tmp_path,
        {"cn_equity_core": {"shadow_root_ref": str(current)}},
    )

    assert summary["session_count"] == 1
    assert summary["frozen_count"] == 1
    assert summary["answered_count"] == 1
    assert summary["valid_trade_date_count"] == 1
    assert summary["completed_outcomes"] == {"1": 0, "5": 0, "20": 0, "60": 0}
    assert summary["outcome_progress"]["20"] == {"completed": 0, "pending": 1}


def test_acceptance_normalizes_evaluated_challenger_and_gate_semantics() -> None:
    status = _task_status(
        {
            "cn_equity_core/direction_1d": {
                "status": "research_only",
                "research_ready": False,
                "unevaluated_challengers": ["lightgbm", "xgboost"],
            }
        },
        "direction_1d",
    )

    scope = status["scopes"]["cn_equity_core/direction_1d"]
    assert status["status"] == "available"
    assert scope["evaluated_challengers"] == ["lightgbm", "xgboost"]
    assert "unevaluated_challengers" not in scope
    assert scope["research_gate"] == {
        "passed": False,
        "status": "failed",
        "reasons": ["task_metric_gate_not_met"],
    }
