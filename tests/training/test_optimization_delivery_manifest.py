from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_optimization_delivery_manifest.py"
    spec = importlib.util.spec_from_file_location("optimization_delivery", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_delivery_manifest_never_calls_partial_artifacts_complete(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "artifacts/cn_data_completion_plan").mkdir(parents=True)
    (tmp_path / "artifacts/project_completion").mkdir(parents=True)
    (tmp_path / "artifacts/long_term_readiness").mkdir(parents=True)
    (tmp_path / "artifacts/long_term_training/candidate-suite").mkdir(parents=True)
    (tmp_path / "artifacts/agent_acceptance").mkdir(parents=True)
    for relative, payload in {
        "artifacts/cn_data_completion_plan/latest.json": {"status": "blocked", "steps": [{"id": "prices", "status": "partial"}]},
        "artifacts/project_completion/latest.json": {"status": "blocked", "summary": {"missing": 1}},
        "artifacts/long_term_readiness/latest.json": {"status": "blocked", "checks": []},
        "artifacts/long_term_training/candidate-suite/evaluation-contract.json": {"status": "incomplete"},
        "artifacts/agent_acceptance/latest.json": {"status": "blocked", "metrics": {}},
    }.items():
        (tmp_path / relative).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "dist-workbench").mkdir()
    (tmp_path / "dist-workbench/index.html").write_text("ok", encoding="utf-8")

    manifest = module.build_manifest(tmp_path)

    assert manifest["status"] == "blocked"
    assert manifest["release_channel"] == "research_only"
    assert "active_snapshot" in manifest["missing_gates"]
    assert manifest["gates"]["frontend_build"] is True
