from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_long_term_candidate_suite.py"
    spec = importlib.util.spec_from_file_location("long_term_candidate_suite", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_suite_report_requires_all_four_canonical_tasks(tmp_path: Path) -> None:
    module = _module()
    assert module.DEFAULT_TARGETS == (
        "excess_return_120d",
        "excess_return_240d",
        "future_max_drawdown_120d",
        "future_max_drawdown_240d",
    )
    report = tmp_path / "reports" / "excess_return_120d.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"status": "research_only", "deployment_ready": False}), encoding="utf-8")
    status = {
        "stages": [{
            "task": "excess_return_120d",
            "status": "completed",
            "output": str(report),
            "predictions": str(tmp_path / "predictions" / "excess_return_120d.parquet"),
        }]
    }
    payload = module._write_suite_report(tmp_path, status, finished=True)
    assert payload["status"] == "blocked"
    assert payload["deployment_ready"] is False
    assert set(payload["task_contract"]["primary_tasks"]) == set(module.DEFAULT_TARGETS)


def test_metric_contract_does_not_fill_missing_fields_with_zero() -> None:
    module = _module()
    contract = module._metric_contract({
        "models": {
            "ridge": {"holdout_metrics": {"rank_ic": 0.04, "turnover": 0.2}},
        },
    })
    assert contract["status"] == "incomplete"
    assert contract["models"]["ridge"]["rank_ic"] == "recorded"
    assert contract["models"]["ridge"]["max_drawdown_after_cost"] == "not_recorded"
