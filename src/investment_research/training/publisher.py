from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

from investment_research.pipeline.artifact_integrity import verify_artifact_set


class PublicationBlocked(RuntimeError):
    pass


def attach_approval_evidence(
    staging_model_dir: Path,
    *,
    training_run_id: str,
    evidence_paths: list[Path],
) -> dict:
    manifest_path = staging_model_dir / "model_manifest.json"
    if not manifest_path.is_file():
        raise PublicationBlocked("cannot attach approval evidence without manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("training_run_id") != training_run_id:
        raise PublicationBlocked("approval evidence and manifest training_run_id differ")
    evidence = []
    for path in sorted((item for item in evidence_paths if item.is_file()), key=str):
        evidence.append(
            {
                "name": path.name,
                "evidence_type": _evidence_type(path.name),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest["approval_evidence"] = evidence
    manifest["approval_evidence_complete"] = bool(evidence)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def validate_publishable_manifest(
    staging_model_dir: Path,
    *,
    expected_training_run_id: str,
    expected_config_hash: str,
    expected_feature_contract: str,
    expected_market: str | None = None,
    expected_task: str | None = None,
    expected_decision_context: str | None = None,
    require_four_market_evidence: bool = False,
) -> dict:
    path = staging_model_dir / "model_manifest.json"
    if not path.is_file():
        raise PublicationBlocked("staged model manifest is missing")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    evidence_types = {item.get("evidence_type") for item in manifest.get("approval_evidence", [])}
    required_evidence = {
        "leakage_audit",
        "holdout_12m",
        "stress_6m",
        "ablation",
        "approval_report",
        "shadow_run",
    }
    checks = {
        "deployment_ready": manifest.get("deployment_ready") is True,
        "not_legacy": manifest.get("legacy_cutoff_semantics") is False,
        "real_data": manifest.get("data_source") == "real",
        "training_run_id": manifest.get("training_run_id") == expected_training_run_id,
        "config_hash": manifest.get("config_hash") == expected_config_hash,
        "feature_contract": manifest.get("feature_contract_version") == expected_feature_contract,
        "single_decision_context": manifest.get("decision_context") in {"close_confirmed", "pre_open"},
        "approval_evidence": manifest.get("approval_evidence_complete") is True,
        "approval_evidence_types": (not require_four_market_evidence) or required_evidence <= evidence_types,
        "leakage_errors_zero": (not require_four_market_evidence) or manifest.get("leakage_error_count") == 0,
        "critical_coverage": (not require_four_market_evidence) or float(manifest.get("critical_data_coverage", 0.0)) >= 0.98,
        "shadow_sessions": (not require_four_market_evidence) or int(manifest.get("shadow_run_sessions", 0)) >= 20,
        "synthetic_outputs_zero": (not require_four_market_evidence) or int(manifest.get("formal_synthetic_output_count", -1)) == 0,
        "market_scope": expected_market is None or manifest.get("market") == expected_market,
        "task_scope": expected_task is None or manifest.get("task") == expected_task,
        "context_scope": expected_decision_context is None or manifest.get("decision_context") == expected_decision_context,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise PublicationBlocked("manifest publication gates failed: " + ", ".join(failed))
    verify_artifact_set(staging_model_dir, manifest)
    return manifest


def _evidence_type(name: str) -> str:
    lowered = name.lower()
    for marker, evidence_type in (
        ("leakage", "leakage_audit"),
        ("holdout_12", "holdout_12m"),
        ("stress_6", "stress_6m"),
        ("ablation", "ablation"),
        ("shadow", "shadow_run"),
        ("approval", "approval_report"),
    ):
        if marker in lowered:
            return evidence_type
    return "other"


def atomic_publish(staging_model_dir: Path, deployment_dir: Path) -> None:
    temporary = deployment_dir.with_name(deployment_dir.name + ".next")
    backup = deployment_dir.with_name(deployment_dir.name + ".previous")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(staging_model_dir, temporary)
    if backup.exists():
        shutil.rmtree(backup)
    if deployment_dir.exists():
        deployment_dir.replace(backup)
    temporary.replace(deployment_dir)
