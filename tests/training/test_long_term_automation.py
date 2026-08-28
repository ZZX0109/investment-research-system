from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_long_term_automation.py"
    spec = importlib.util.spec_from_file_location("long_term_automation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_is_fail_closed_and_never_creates_model_outputs(tmp_path: Path) -> None:
    module = _module()
    run_root = tmp_path / "runs"
    data_root = tmp_path / "data"
    code = module.main([
        "--mode", "dry-run",
        "--config", str(Path(__file__).resolve().parents[2] / "config/long_term_training.yaml"),
        "--data-root", str(data_root),
        "--object-store", str(tmp_path / "object-store"),
        "--run-root", str(run_root),
        "--lock-root", str(tmp_path / "locks"),
    ])
    assert code == module.EXIT_DRY_RUN_BLOCKED
    run_dirs = [item for item in run_root.iterdir() if item.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    status = json.loads((run_dir / "run-status.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "gate/dry-run-report.json").read_text(encoding="utf-8"))
    assert status["status"] == "dry_run_complete_blocked"
    assert report["safety"]["writes_model_weights"] is False
    assert report["safety"]["writes_predictions"] is False
    assert not list(run_dir.rglob("*.pt"))
    assert not list(run_dir.rglob("*.parquet"))
    assert not (data_root / "active.json").exists()


def test_formal_mode_requires_bound_sample_list_before_running(tmp_path: Path) -> None:
    module = _module()
    try:
        module.main([
            "--mode", "formal",
            "--config", str(Path(__file__).resolve().parents[2] / "config/long_term_training.yaml"),
            "--data-root", str(tmp_path / "data"),
            "--object-store", str(tmp_path / "object-store"),
            "--run-root", str(tmp_path / "runs"),
            "--lock-root", str(tmp_path / "locks"),
        ])
    except SystemExit as exc:
        assert "requires --samples" in str(exc)
    else:  # pragma: no cover - argparse contract must reject this input
        raise AssertionError("formal mode accepted an unbound sample list")


def test_run_identity_contains_contract_and_code_hashes() -> None:
    module = _module()
    run_id = module._make_run_id("dry-run", "a" * 64, "b" * 64, "c" * 64)
    assert run_id.startswith("lt-dry-run-")
    assert "-aaaaaaaaaaaa-bbbbbbbbbbbb-cccccccccccc" in run_id


def test_manifest_summary_preserves_snapshot_binding(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "manifest-list.json"
    path.write_text(json.dumps({
        "market_snapshot_id": "snap-1",
        "market_snapshot_hash": "d" * 64,
        "sample_manifests": ["one.json", "two.json"],
    }), encoding="utf-8")
    summary = module._manifest_summary(path)
    assert summary["exists"] is True
    assert summary["count"] == 2
    assert summary["snapshot_id"] == "snap-1"
    assert summary["snapshot_hash"] == "d" * 64


def test_rebuild_summary_is_explicitly_non_formal_binding(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "rebuild.json"
    path.write_text(json.dumps({
        "contexts": {"close_confirmed": {
            "snapshot_id": "research-snap",
            "snapshot_hash": "e" * 64,
            "sample_manifests": {"cn_equity_core": ["a.json"], "cn_etf_benchmark": ["b.json"]},
        }},
    }), encoding="utf-8")
    summary = module._manifest_summary(None, path)
    assert summary["count"] == 2
    assert summary["formal_binding"] is False
    assert summary["source"] == "rebuild_index"
