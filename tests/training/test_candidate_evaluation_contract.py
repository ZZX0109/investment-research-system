from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_candidate_evaluation_contract.py"
    spec = importlib.util.spec_from_file_location("candidate_evaluation_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_contract_records_missing_capacity_and_hashes(tmp_path: Path) -> None:
    module = _module()
    reports = tmp_path / "reports"
    predictions = tmp_path / "predictions"
    reports.mkdir()
    predictions.mkdir()
    for task in module.TASKS:
        report = reports / f"{task}.json"
        report.write_text(json.dumps({
            "status": "research_only",
            "deployment_ready": False,
            "models": {
                "ridge": {"status": "research_only", "holdout_metrics": {
                    "rank_ic": 0.02,
                    "turnover": 0.1,
                    "capacity_estimate": None,
                }},
            },
        }), encoding="utf-8")
        (predictions / f"{task}.parquet").write_bytes(b"PAR1-test")

    contract = module.build(tmp_path, reports)

    assert contract["status"] == "incomplete"
    assert contract["research_only"] is True
    assert set(contract["tasks"]) == set(module.TASKS)
    item = contract["tasks"][module.TASKS[0]]
    assert item["report_sha256"]
    assert item["predictions_sha256"]
    assert "capacity_estimate" in item["models"]["ridge"]["missing_fields"]
    assert item["formal_promotion_eligible"] is False
