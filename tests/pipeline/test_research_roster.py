from hashlib import sha256
import json
from pathlib import Path

import pytest

from investment_research.pipeline.research_roster import (
    build_research_roster,
    load_verified_research_roster,
)


def _task_manifest(project: Path) -> dict:
    scope = project / "artifacts/models/cn/close_confirmed/cn_equity_core/drawdown_20d"
    reports = scope / "reports"
    reports.mkdir(parents=True)
    for name in ("dataset_manifest", "leakage_audit"):
        payload = {"name": name}
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        (reports / f"{name}.json").write_text(json.dumps({"report_hash": digest, "payload": payload}))
    for name, contents in {
        "evaluation.json": b"evaluation", "research_model.joblib": b"model",
        "feature_order.json": b"[]",
    }.items():
        (scope / name).write_bytes(contents)
    return {
        "data_tier": "research_pit", "status": "research_only", "deployment_ready": False,
        "market": "cn", "decision_context": "close_confirmed", "cohort": "cn_equity_core",
        "task": "drawdown_20d", "training_run_id": "run-1", "dataset_hash": "d" * 64,
        "market_snapshot_refs": [{"market_snapshot_id": "snapshot", "market_snapshot_hash": "s" * 64}],
        "code_hash": "c" * 64,
        "evaluation_ref": "artifacts/models/cn/close_confirmed/cn_equity_core/drawdown_20d/evaluation.json",
        "artifact_hashes": {
            name: sha256((scope / name).read_bytes()).hexdigest()
            for name in ("evaluation.json", "research_model.joblib", "feature_order.json")
        },
        "report_hashes": {
            name: json.loads((reports / f"{name}.json").read_text())["report_hash"]
            for name in ("dataset_manifest", "leakage_audit")
        },
    }


def test_research_roster_is_exact_scope_and_hash_bound(tmp_path: Path) -> None:
    manifest = _task_manifest(tmp_path)
    roster = build_research_roster(
        task_manifest=manifest, primary_candidate="historical-distribution",
        fallback_candidate="linear-baseline", challenger_candidates=[],
        cohort_version="cn-equity-core-2026Q3-abc", dependency_hash="p" * 64,
    )
    path = tmp_path / "roster.json"
    path.write_text(roster.model_dump_json())
    loaded = load_verified_research_roster(
        path, market="cn", decision_context="close_confirmed",
        cohort_version="cn-equity-core-2026Q3-abc", task="drawdown_20d",
        project_root=tmp_path,
    )
    assert loaded.primary.candidate_name == "historical-distribution"
    assert loaded.fallback.candidate_name == "linear-baseline"
    assert loaded.deployment_ready is False

    with pytest.raises(ValueError, match="exact scope mismatch"):
        load_verified_research_roster(
            path, market="cn", decision_context="close_confirmed",
            cohort_version="other", task="drawdown_20d", project_root=tmp_path,
        )


def test_research_roster_rejects_report_tampering(tmp_path: Path) -> None:
    manifest = _task_manifest(tmp_path)
    roster = build_research_roster(
        task_manifest=manifest, primary_candidate="historical-distribution",
        fallback_candidate="linear-baseline", challenger_candidates=[],
        cohort_version="v1", dependency_hash="p" * 64,
    )
    path = tmp_path / "roster.json"
    path.write_text(roster.model_dump_json())
    report = tmp_path / "artifacts/models/cn/close_confirmed/cn_equity_core/drawdown_20d/reports/leakage_audit.json"
    report.write_text(report.read_text().replace("leakage_audit", "tampered"))
    with pytest.raises(ValueError, match="report hash mismatch"):
        load_verified_research_roster(
            path, market="cn", decision_context="close_confirmed",
            cohort_version="v1", task="drawdown_20d", project_root=tmp_path,
        )
