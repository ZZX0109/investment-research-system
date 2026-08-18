#!/usr/bin/env python3
"""Produce one machine-readable readiness audit for the long-term CN track.

This command is read-only with respect to raw data, landing directories and
the active pointer. It deliberately reports blocked checks instead of
guessing coverage from a nearby artifact or turning missing PIT timestamps
into usable values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.active_snapshot_guard import ActiveSnapshotInputError, require_active_snapshot
from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.snapshot_landing import SnapshotGateConfig, evaluate_snapshot_gate
from investment_research.service.deep_long_term import LONG_TERM_TASKS, load_deep_long_term_registry_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/long_term_readiness/latest.json")
    return parser.parse_args()


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _check(name: str, passed: bool, *, evidence: dict, reasons: list[str] | None = None) -> dict:
    return {
        "name": name,
        "status": "passed" if passed else "blocked",
        "evidence": evidence,
        "blocking_reasons": [] if passed else list(reasons or [f"{name}_not_proven"]),
    }


def _prediction_artifact_check(project_root: Path, training: dict) -> tuple[bool, dict, list[str]]:
    """Verify the compact prediction artifact named by the training report.

    The report is allowed to be blocked and therefore omit a prediction file;
    in that case the check remains blocked instead of treating the omission as
    an empty-but-valid result.  Paths are constrained to the project root so a
    report cannot make readiness depend on a mutable downloader directory.
    """
    reference = training.get("predictions_ref")
    expected_hash = training.get("predictions_sha256")
    evidence = {"reference": reference, "expected_sha256": expected_hash, "exists": False, "observed_sha256": None}
    if not isinstance(reference, str) or not reference:
        return False, evidence, ["training_predictions_reference_missing"]
    path = Path(reference)
    if not path.is_absolute():
        path = project_root / path
    try:
        resolved = path.resolve()
    except OSError:
        return False, evidence, ["training_predictions_reference_invalid"]
    if resolved != project_root and project_root not in resolved.parents:
        return False, evidence, ["training_predictions_reference_outside_project"]
    evidence["path"] = str(resolved)
    evidence["exists"] = resolved.is_file()
    if not resolved.is_file():
        return False, evidence, ["training_predictions_file_missing"]
    if resolved.suffix.lower() != ".parquet":
        return False, evidence, ["training_predictions_not_parquet"]
    try:
        digest_builder = hashlib.sha256()
        with resolved.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest_builder.update(block)
        digest = digest_builder.hexdigest()
    except OSError:
        return False, evidence, ["training_predictions_file_unreadable"]
    evidence["observed_sha256"] = digest
    if not isinstance(expected_hash, str) or digest != expected_hash:
        return False, evidence, ["training_predictions_hash_mismatch"]
    return True, evidence, []


def _evaluation_contract_check(deep_registry: dict) -> tuple[bool, dict, list[str]]:
    """Require each registered primary model to persist the evaluation fields."""
    models = deep_registry.get("models") if isinstance(deep_registry, dict) else None
    if not isinstance(models, list) or len(models) != len(LONG_TERM_TASKS):
        return False, {"task_count": 0 if not isinstance(models, list) else len(models)}, ["long_term_model_evaluation_tasks_incomplete"]
    missing_by_task: dict[str, list[str]] = {}
    coverage: dict[str, dict[str, int]] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        task = str(item.get("task") or "unknown")
        status = item.get("evaluation_metric_status")
        if not isinstance(status, dict):
            missing_by_task[task] = ["evaluation_metric_status_missing"]
            continue
        fields = status.get("fields") if isinstance(status.get("fields"), dict) else {}
        missing = sorted(str(key) for key, value in fields.items() if not isinstance(value, dict) or value.get("status") != "recorded")
        coverage[task] = {
            "recorded_count": int(status.get("recorded_count", 0) or 0),
            "required_count": int(status.get("required_count", len(fields)) or 0),
        }
        if missing:
            missing_by_task[task] = missing
    evidence = {"coverage": coverage, "missing_by_task": missing_by_task}
    reasons = [
        f"long_term_model_evaluation_metrics_incomplete:{task}:{','.join(fields)}"
        for task, fields in sorted(missing_by_task.items())
    ]
    return not reasons, evidence, reasons


def _event_semantics_check(download_manifest: dict) -> tuple[bool, dict, list[str]]:
    """Check that event absence is represented explicitly, never as a zero."""
    records = download_manifest.get("records") if isinstance(download_manifest, dict) else None
    event_records = [
        item for item in records or []
        if isinstance(item, dict) and (item.get("category") == "events" or item.get("dataset") == "events")
    ]
    allowed = {"no_events_confirmed", "provider_not_covered", "published_time_unverified", "field_missing_in_source", "fetch_failed", "pending_backfill"}
    invalid: list[str] = []
    statuses: dict[str, int] = {}
    for item in event_records:
        quality = str(item.get("quality_status") or "unavailable")
        statuses[quality] = statuses.get(quality, 0) + 1
        reason = item.get("missing_reason")
        code = item.get("missing_reason_code")
        if quality != "complete" and not reason:
            invalid.append("missing_reason")
        if code is not None and code not in allowed:
            invalid.append(f"unknown_missing_reason_code:{code}")
        if quality == "complete" and (reason or code):
            invalid.append("complete_event_record_has_missing_reason")
        if str(reason or "").strip().lower() in {"no events", "no_event", "none", "0"} and code != "no_events_confirmed":
            invalid.append("unqualified_no_event_statement")
    evidence = {"event_record_count": len(event_records), "quality_statuses": statuses, "invalid_semantics": sorted(set(invalid))}
    if not event_records:
        return False, evidence, ["event_dataset_missing"]
    if invalid:
        return False, evidence, [f"event_missing_semantics_invalid:{item}" for item in sorted(set(invalid))]
    return True, evidence, []


def build_audit(project_root: Path) -> dict:
    project_root = project_root.resolve()
    artifact_root = project_root / "artifacts"
    manifest = _read(artifact_root / "download_manifests/latest.json")
    financial = _read(artifact_root / "cn_financial_coverage/latest.json")
    security = _read(artifact_root / "cn_security_master/latest.json")
    trading = _read(artifact_root / "cn_trading_status/latest.json")
    macro = _read(artifact_root / "cn_research_auxiliary/macro_pit_latest.json")
    training = _read(artifact_root / "long_term_training/latest.json")
    deep_registry = load_deep_long_term_registry_summary(project_root=project_root)
    artifact_registration = _read(artifact_root / "long_term_model_registry/latest.json")
    active_path = project_root / "var/cn-research/active.json"
    active_error = None
    active_manifest = None
    active_context = None
    try:
        active_context = require_active_snapshot(project_root / "var/cn-research")
        active_manifest = active_context.manifest
    except (ValueError, ActiveSnapshotInputError) as exc:
        active_error = str(exc)

    active_gate = None
    if active_manifest is not None:
        try:
            config = load_long_term_training_config(project_root / "config/long_term_training.yaml")
            active_gate = evaluate_snapshot_gate(
                active_manifest,
                config=SnapshotGateConfig(
                    required_datasets=set(config.required_snapshot_datasets),
                    minimum_financial_coverage=config.minimum_financial_coverage,
                ),
                labels_mature=training.get("labels_mature") is True,
            )
        except (OSError, ValueError, TypeError) as exc:
            active_error = active_error or f"active_snapshot_gate_unavailable:{exc}"

    checks = [
        _check(
            "download_manifest",
            manifest.get("ready_for_landing") is True and manifest.get("status") == "ready_for_landing",
            evidence={"status": manifest.get("status"), "ready_for_landing": manifest.get("ready_for_landing"), "record_count": manifest.get("record_count")},
            reasons=[f"blocked_dataset:{item}" for item in manifest.get("blocked_datasets", [])] or ["download_manifest_not_ready"],
        ),
        _check(
            "active_snapshot",
            active_manifest is not None,
            evidence={
                "path": str(active_path),
                "exists": active_path.exists(),
                "snapshot_id": None if active_manifest is None else active_manifest.snapshot_id,
                "manifest_hash": None if active_context is None else active_context.manifest_hash,
                "file_integrity_verified": active_context is not None,
            },
            reasons=[active_error or "active_snapshot_invalid"],
        ),
        _check(
            "active_snapshot_gate",
            active_gate is not None and active_gate.passed,
            evidence={
                "passed": None if active_gate is None else active_gate.passed,
                "snapshot_id": None if active_gate is None else active_gate.snapshot_id,
                "dataset_names": [] if active_gate is None else active_gate.dataset_names,
                "pit_leakage_error_count": None if active_gate is None else active_gate.pit_leakage_error_count,
                "pit_leakage_audit_ref": None if active_gate is None else active_gate.pit_leakage_audit_ref,
            },
            reasons=(
                ["active_snapshot_gate_unavailable"]
                if active_gate is None
                else active_gate.reasons
            ),
        ),
        _check(
            "financial_pit",
            financial.get("quality_status") == "complete"
            and float(financial.get("coverage", 0.0) or 0.0) >= 0.95
            and financial.get("pit_verified") is True,
            evidence={"coverage": financial.get("coverage"), "minimum_coverage": financial.get("minimum_coverage"), "pit_verified": financial.get("pit_verified"), "low_coverage_fields": financial.get("low_coverage_fields", [])},
            reasons=["financial_pit_or_field_coverage_incomplete"],
        ),
        _check(
            "historical_security_master",
            security.get("quality_status") == "complete"
            and float(security.get("st_status_coverage", 0.0) or 0.0) >= 0.98
            and float(security.get("delisting_coverage", 0.0) or 0.0) >= 0.98
            and float(security.get("code_change_coverage", 0.0) or 0.0) >= 0.98,
            evidence={"symbol_count": security.get("symbol_count"), "industry_mapped_count": security.get("industry_mapped_count"), "st_status_coverage": security.get("st_status_coverage"), "delisting_coverage": security.get("delisting_coverage"), "code_change_coverage": security.get("code_change_coverage")},
            reasons=["historical_security_lifecycle_not_proven"],
        ),
        _check(
            "trading_status_pit",
            trading.get("quality_status") == "complete" and float(trading.get("published_at_coverage", 0.0) or 0.0) >= 0.98,
            evidence={"symbol_count": trading.get("symbol_count"), "row_count": trading.get("row_count"), "published_at_coverage": trading.get("published_at_coverage"), "available_at_coverage": trading.get("available_at_coverage")},
            reasons=["historical_trading_status_publication_time_not_proven"],
        ),
        _check(
            "macro_pit",
            macro.get("quality_status") == "complete" and float(macro.get("published_at_coverage", 0.0) or 0.0) >= 0.98,
            evidence={"record_count": macro.get("record_count"), "published_at_coverage": macro.get("published_at_coverage"), "revision_coverage": macro.get("revision_coverage")},
            reasons=["macro_publication_time_not_proven"],
        ),
        _check(
            "long_term_training",
            training.get("status") == "research_only" and training.get("deployment_ready") is False,
            evidence={"status": training.get("status"), "deployment_ready": training.get("deployment_ready"), "target": training.get("target"), "snapshot_id": training.get("snapshot_id")},
            reasons=list(training.get("blocking_reasons") or ["long_term_training_not_ready"]),
        ),
        _check(
            "deep_model_artifact_registration",
            deep_registry.get("status") == "available"
            and artifact_registration.get("schema_version") == "long-term-model-artifact-registration-v1"
            and artifact_registration.get("registration_status") == "registered_research_only"
            and artifact_registration.get("deployment_ready") is False
            and set(artifact_registration.get("tasks") or []) == set(LONG_TERM_TASKS),
            evidence={
                "registry_status": deep_registry.get("status"),
                "registration_status": artifact_registration.get("registration_status"),
                "task_count": artifact_registration.get("task_count"),
                "tasks": artifact_registration.get("tasks", []),
                "reference_only": artifact_registration.get("reference_only"),
            },
            reasons=(list(deep_registry.get("blocking_reasons") or [])
                     + ["deep_model_artifact_registration_missing"]),
        ),
    ]
    prediction_passed, prediction_evidence, prediction_reasons = _prediction_artifact_check(project_root, training)
    checks.append(_check(
        "training_prediction_parquet",
        prediction_passed,
        evidence=prediction_evidence,
        reasons=prediction_reasons,
    ))
    evaluation_passed, evaluation_evidence, evaluation_reasons = _evaluation_contract_check(deep_registry)
    checks.append(_check(
        "long_term_model_evaluation_contract",
        evaluation_passed,
        evidence=evaluation_evidence,
        reasons=evaluation_reasons,
    ))
    event_passed, event_evidence, event_reasons = _event_semantics_check(manifest)
    checks.append(_check(
        "event_missing_semantics",
        event_passed,
        evidence=event_evidence,
        reasons=event_reasons,
    ))
    blocked = [reason for check in checks if check["status"] == "blocked" for reason in check["blocking_reasons"]]
    return {
        "schema_version": "long-term-readiness-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_tier": "research_pit",
        "status": "ready_for_long_term_training" if not blocked else "blocked",
        "deployment_ready": False,
        "checks": checks,
        "blocking_reasons": sorted(set(blocked)),
        "source_refs": {
            "download_manifest": str((artifact_root / "download_manifests/latest.json").relative_to(project_root)),
            "financial_coverage": str((artifact_root / "cn_financial_coverage/latest.json").relative_to(project_root)),
            "security_master": str((artifact_root / "cn_security_master/latest.json").relative_to(project_root)),
            "trading_status": str((artifact_root / "cn_trading_status/latest.json").relative_to(project_root)),
            "macro_pit": str((artifact_root / "cn_research_auxiliary/macro_pit_latest.json").relative_to(project_root)),
            "long_term_training": str((artifact_root / "long_term_training/latest.json").relative_to(project_root)),
        },
    }


def main() -> int:
    args = parse_args()
    audit = build_audit(args.project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "blocking_reasons": audit["blocking_reasons"]}, ensure_ascii=False))
    return 0 if audit["status"] == "ready_for_long_term_training" else 2


if __name__ == "__main__":
    raise SystemExit(main())
