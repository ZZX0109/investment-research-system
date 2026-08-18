#!/usr/bin/env python3
"""Build a machine-readable backend acceptance report for one CN demo run."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any


PROJECT = Path(__file__).resolve().parent.parent
TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate CN research backend acceptance evidence")
    parser.add_argument("--run-report", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--shadow-root", type=Path, default=PROJECT / "artifacts/research_shadow")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--update-run-report", action="store_true",
        help="Embed the regenerated acceptance payload back into the referenced demo report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_path = _resolve(args.run_report)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    coverage = _read_json(args.coverage)
    records = coverage.get("records", [])
    cn_records = [item for item in records if item.get("market") == "cn"]
    provider_counts = Counter(str(item.get("provider", "unknown")) for item in cn_records)
    status_counts = Counter(str(item.get("status", "unknown")) for item in cn_records)
    quality_counts = Counter(_quality_status(item) for item in cn_records)
    fallback_records = [item for item in cn_records if len(item.get("provider_chain", [])) > 1]
    market_coverage = [item for item in coverage.get("market_coverage", []) if item.get("market") == "cn"]
    event_states = Counter(
        str(item.get("event_coverage_status", item.get("status", "unknown")))
        for item in cn_records if item.get("dataset") == "events"
    )
    task_statuses = {
        task: _task_status(run.get("tasks", {}), task)
        for task in TASKS
    }
    artifact_evidence = _artifact_evidence(run)
    _apply_task_contract(task_statuses, artifact_evidence)
    shadow = _shadow_summary(_resolve(args.shadow_root), run.get("shadow", {}))
    formal_blocking = [
        "licensed_provider_missing",
        "historical_available_at_unproven",
        "formal_pit_evidence_missing",
    ]
    reasons: list[str] = []
    if any(item.get("provider") == "yfinance" for item in cn_records):
        reasons.append("cn_yfinance_record_present_legacy_excluded")
    if not run.get("rebuild_index"):
        reasons.append("rebuild_index_missing")
    if run.get("status") != "research_complete":
        reasons.append(f"demo_status:{run.get('status', 'unknown')}")
    if any(item["status"] in {"blocked", "unavailable"} for item in task_statuses.values()):
        reasons.append("one_or_more_tasks_not_available")
    if artifact_evidence["missing_tasks"]:
        reasons.append("task_artifact_missing")
    artifact_available = not artifact_evidence["missing_tasks"] and all(
        entry.get("status") == "complete"
        for entry in artifact_evidence["entries"]
    ) and bool(artifact_evidence["entries"])
    inference_count = sum(
        int(value.get("count", 0))
        for value in (run.get("inference") or {}).values()
        if isinstance(value, dict)
    )
    quality_degraded = bool(quality_counts.get("degraded", 0))
    payload: dict[str, Any] = {
        "schema_version": "cn-research-backend-acceptance-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_report_ref": _portable_ref(run_path),
        "status": "blocked" if run.get("status") == "blocked" else "partial" if reasons else "complete",
        "data_tier": "research_pit",
        "research_only": True,
        "research_status": "research_only",
        "artifact_available": artifact_available,
        "prediction_status": "available" if inference_count else "unavailable",
        "model_status": "research_only" if artifact_available else "unavailable",
        "evidence_status": "partial" if quality_degraded or event_states else "valid",
        "deployment_ready": False,
        "environment": _environment(),
        "data": {
            "coverage_ref": _portable_ref(_resolve(args.coverage)) if _resolve(args.coverage).is_file() else None,
            "market_coverage": [{key: item.get(key) for key in (
                "market", "target_count", "successful_target_count", "coverage_ratio",
                "unavailable_symbols", "failed_providers", "security_state_status",
                "event_coverage_status", "reasons",
            )} for item in market_coverage],
            "provider_counts": dict(provider_counts),
            "akshare_success_count": sum(item.get("provider") == "akshare" and item.get("status") in {"backfilled", "complete"} for item in cn_records),
            "baostock_success_count": sum(item.get("provider") == "baostock" and item.get("status") in {"backfilled", "complete"} for item in cn_records),
            "status_counts": dict(status_counts),
            "failed_count": sum(item.get("status") in {"fetch_failed", "unsupported"} for item in cn_records),
            "conflict_count": sum(item.get("degraded_reason") == "provider_conflict" for item in cn_records),
            "quality_status_counts": dict(quality_counts),
            "fallback_count": len(fallback_records),
            "fallback_providers": sorted({str(item.get("provider")) for item in fallback_records}),
            "event_coverage_states": dict(event_states),
            "cninfo_event_records": sum(item.get("provider") == "akshare_cninfo_notices" and item.get("status") in {"backfilled", "partial"} for item in cn_records),
            "synthetic_count": int(coverage.get("synthetic_count", 0)),
            "cn_yfinance_records": sum(item.get("provider") == "yfinance" for item in cn_records),
            "legacy_yfinance_excluded_count": sum(item.get("provider") == "yfinance" for item in cn_records),
        },
        "cohorts": run.get("cohorts", {}),
        "tasks": task_statuses,
        "task_artifact_evidence": artifact_evidence,
        "inference": run.get("inference", {}),
        "shadow": {
            **run.get("shadow", {}),
            **shadow,
        },
        "formal_mode": {"status": "blocked", "gating_reasons": formal_blocking},
        "blocking_reasons": reasons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.update_run_report:
        run["backend_acceptance"] = payload
        run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 2 if payload["status"] == "blocked" else 0


def _task_status(tasks: dict[str, Any], task: str) -> dict[str, Any]:
    matches = [(key, value) for key, value in tasks.items() if key.endswith(f"/{task}")]
    if not matches:
        return {"status": "unavailable", "gating_reasons": ["task_artifact_missing"]}
    scopes: dict[str, Any] = {}
    for key, value in matches:
        record = dict(value)
        # Older run reports used an inaccurate name: these candidates had
        # already been evaluated on the common folds, but were not selected
        # for the primary/fallback roster.  Normalise the evidence without
        # rewriting the immutable historical run report.
        if "unevaluated_challengers" in record and "evaluated_challengers" not in record:
            record["evaluated_challengers"] = record.pop("unevaluated_challengers")
        research_ready = bool(record.get("research_ready", False))
        research_status = str(record.get("research_status", "research_ready" if research_ready else "exploratory"))
        record.setdefault("research_gate", {
            "passed": research_ready,
            "status": "passed" if research_ready else "failed",
            "reasons": [] if research_ready else ["task_metric_gate_not_met"],
        })
        # Populate the explicit contract even when this helper is used in
        # isolation (for example by contract tests).  The final artifact
        # verification pass may tighten these values further.
        record.setdefault("artifact_available", bool(record.get("manifest")))
        record.setdefault("prediction_status", "available" if record["artifact_available"] else "unavailable")
        record.setdefault("model_status", "research_only" if record["artifact_available"] else "unavailable")
        record.setdefault("evidence_status", "valid" if record["artifact_available"] else "blocked")
        scopes[key] = record
        scopes[key]["research_status"] = research_status
    return {
        # ``status=available`` is retained as a compatibility alias for older
        # consumers.  New consumers must use the explicit fields on each
        # scope: artifact_available, research_status and prediction_status.
        "status": "available" if any(value.get("status") == "research_only" for _, value in matches) else str(matches[0][1].get("status", "unavailable")),
        "research_status_counts": dict(Counter(str(value.get("research_status", "unavailable")) for value in scopes.values())),
        "scopes": scopes,
    }


def _apply_task_contract(task_statuses: dict[str, Any], artifact_evidence: dict[str, Any]) -> None:
    """Add explicit availability/status fields without breaking old readers."""
    evidence_by_scope = {
        str(entry.get("scope")): entry
        for entry in artifact_evidence.get("entries", [])
        if isinstance(entry, dict)
    }
    for task_payload in task_statuses.values():
        for scope, record in (task_payload.get("scopes") or {}).items():
            evidence = evidence_by_scope.get(scope)
            artifact_available = bool(evidence and evidence.get("status") == "complete")
            research_status = str(record.get("research_status", "exploratory"))
            record["artifact_available"] = artifact_available
            record["model_status"] = "research_only" if artifact_available else "unavailable"
            record["prediction_status"] = "available" if artifact_available else "unavailable"
            record["evidence_status"] = "valid" if artifact_available else "blocked"
            if evidence and evidence.get("reasons"):
                record["gating_reasons"] = list(dict.fromkeys([
                    *record.get("gating_reasons", []),
                    *evidence["reasons"],
                ]))
            record["research_status"] = research_status
        scope_records = list((task_payload.get("scopes") or {}).values())
        all_artifacts = bool(scope_records) and all(
            bool(record.get("artifact_available")) for record in scope_records
        )
        task_payload["artifact_available"] = all_artifacts
        task_payload["research_status"] = (
            "research_ready"
            if all(str(record.get("research_status")) == "research_ready" for record in scope_records)
            else "exploratory"
            if all_artifacts
            else "unavailable"
        )
        task_payload["prediction_status"] = "available" if all_artifacts else "unavailable"
        task_payload["model_status"] = "research_only" if all_artifacts else "unavailable"
        task_payload["evidence_status"] = "valid" if all_artifacts else "blocked"


def _artifact_evidence(run: dict[str, Any]) -> dict[str, Any]:
    """Validate task manifests when a task actually produced one.

    A partial/free-data run is allowed to have no artifacts, but the absence
    is explicit and cannot be mistaken for an empty prediction object.  When
    manifests exist, their task and governance fields are checked here and
    model hashes are compared across tasks to catch accidental reuse.
    """
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    sequence_entries: list[dict[str, Any]] = []
    model_hashes: dict[str, list[str]] = {}
    for scope, record in (run.get("tasks") or {}).items():
        task = scope.rsplit("/", 1)[-1]
        ref = record.get("manifest") if isinstance(record, dict) else None
        if not ref:
            missing.append(scope)
            continue
        path = _resolve(Path(str(ref)))
        if not path.is_file():
            entries.append({"scope": scope, "status": "blocked", "reason": "manifest_missing", "manifest_ref": _portable_ref(path)})
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries.append({"scope": scope, "status": "blocked", "reason": "manifest_invalid", "manifest_ref": _portable_ref(path)})
            continue
        hashes = payload.get("artifact_hashes") or {}
        model_hash = (
            hashes.get("model") or hashes.get("model_file")
            or hashes.get("research_model.joblib")
            or next((
                value for key, value in hashes.items()
                if str(key).endswith((".joblib", ".pkl", ".pt"))
            ), None)
        )
        if model_hash:
            model_hashes.setdefault(str(model_hash), []).append(scope)
        reasons = []
        if payload.get("task") != task:
            reasons.append("task_manifest_mismatch")
        if payload.get("data_tier") != "research_pit":
            reasons.append("data_tier_mismatch")
        if payload.get("status") != "research_only":
            reasons.append("research_status_mismatch")
        if payload.get("deployment_ready") is not False:
            reasons.append("deployment_ready_governance_violation")
        if not isinstance(payload.get("market_snapshot_hash"), str) or len(payload["market_snapshot_hash"]) != 64:
            reasons.append("market_snapshot_hash_missing")
        for name, digest in hashes.items():
            artifact_path = path.parent / str(name)
            if not artifact_path.is_file():
                reasons.append(f"artifact_missing:{name}")
            elif _sha256(artifact_path) != digest:
                reasons.append(f"artifact_hash_mismatch:{name}")
        for name, digest in (payload.get("report_hashes") or {}).items():
            report_path = path.parent / "reports" / f"{name}.json"
            if not report_path.is_file():
                reasons.append(f"report_missing:{name}")
                continue
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                actual = _sha256_json(report.get("payload"))
                if report.get("report_hash") != digest or actual != digest:
                    reasons.append(f"report_hash_mismatch:{name}")
            except (OSError, ValueError):
                reasons.append(f"report_invalid:{name}")
        entries.append({
            "scope": scope, "status": "complete" if not reasons else "blocked",
            "manifest_ref": _portable_ref(path), "task": payload.get("task"),
            "model_hash": model_hash, "reasons": reasons,
            "feature_contract_version": payload.get("feature_contract_version"),
            "label_version": payload.get("label_version"),
            "research_status": payload.get("research_status", "exploratory"),
            "research_gate": payload.get("research_gate", {}),
        })
        declared_architectures: set[str] = set()
        for architecture, challenger in (record.get("sequence_challengers") or {}).items() if isinstance(record, dict) else []:
            if not isinstance(challenger, dict):
                continue
            declared_architectures.add(str(architecture))
            sequence_entries.append(_sequence_evidence(scope, task, str(architecture), challenger))
        # A challenger may be trained after the tabular one-click run.  Its
        # immutable manifest is still valid run evidence and must not be
        # invisible merely because the older demo JSON was already frozen.
        for manifest_path in sorted((path.parent / "sequence").glob("*/sequence_manifest.json")):
            architecture = manifest_path.parent.name
            if architecture in declared_architectures:
                continue
            challenger = _read_json(manifest_path)
            sequence_entries.append(_sequence_evidence(scope, task, architecture, challenger))
    reused = {key: scopes for key, scopes in model_hashes.items() if len({item.rsplit("/", 1)[-1] for item in scopes}) > 1}
    return {"entries": entries, "sequence_entries": sequence_entries, "missing_tasks": missing, "reused_model_hashes": reused}


def _sequence_evidence(scope: str, task: str, architecture: str, challenger: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = challenger.get("artifact_ref")
    report_ref = challenger.get("report_ref")
    artifact_path = _resolve(Path(str(artifact_ref))) if artifact_ref else None
    report_path = _resolve(Path(str(report_ref))) if report_ref else None
    reasons: list[str] = []
    if not artifact_path or not artifact_path.is_file():
        reasons.append("sequence_artifact_missing")
    elif challenger.get("artifact_hash") and _sha256(artifact_path) != challenger.get("artifact_hash"):
        reasons.append("sequence_artifact_hash_mismatch")
    if not report_path or not report_path.is_file():
        reasons.append("sequence_report_missing")
    elif challenger.get("report_hash") and _sha256(report_path) != challenger.get("report_hash"):
        reasons.append("sequence_report_hash_mismatch")
    if challenger.get("task") != task:
        reasons.append("sequence_task_mismatch")
    if challenger.get("status") != "research_only" or challenger.get("deployment_ready") is not False:
        reasons.append("sequence_governance_violation")
    return {
        "scope": scope, "task": task, "architecture": architecture,
        "status": "complete" if not reasons else "blocked",
        "artifact_ref": _portable_ref(artifact_path) if artifact_path else None,
        "report_ref": _portable_ref(report_path) if report_path else None,
        "reasons": reasons,
    }


def _quality_status(item: dict[str, Any]) -> str:
    if item.get("status") in {"unsupported", "fetch_failed"}:
        return "unavailable" if item.get("status") == "fetch_failed" else "missing"
    if item.get("degraded_reason") or len(item.get("provider_chain", [])) > 1 or item.get("status") == "partial":
        return "degraded"
    return "complete" if item.get("status") in {"backfilled", "complete"} else "unavailable"


def _shadow_summary(root: Path, run_shadow: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarize only the immutable Shadow roots referenced by this run.

    Falling back to the shared root is retained for older reports.  New demo
    runs isolate each cohort below a run id, so scanning the global directory
    would mix stale sessions from unrelated experiments into acceptance.
    """
    referenced_roots = []
    for item in (run_shadow or {}).values():
        if isinstance(item, dict) and item.get("shadow_root_ref"):
            candidate = _resolve(Path(str(item["shadow_root_ref"])))
            if candidate not in referenced_roots:
                referenced_roots.append(candidate)
    roots = referenced_roots or [root]
    sessions: list[tuple[dict[str, Any], Path]] = []
    for session_root in roots:
        base = session_root / "sessions"
        for path in base.rglob("*.json") if base.is_dir() else []:
            try:
                sessions.append((json.loads(path.read_text(encoding="utf-8")), session_root))
            except (OSError, ValueError):
                continue
    outcomes = Counter()
    for session, session_root in sessions:
        base = session_root / "outcomes" / str(session.get("id"))
        for path in base.glob("*.json") if base.is_dir() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("data_complete"):
                    outcomes[str(item.get("horizon_sessions"))] += 1
            except (OSError, ValueError):
                continue
    session_count = len(sessions)
    valid_session_count = sum(bool(item.get("evidence_valid")) for item, _ in sessions)
    abstain_count = sum(bool(item.get("abstained")) for item, _ in sessions)
    completed = {str(horizon): int(outcomes.get(str(horizon), 0)) for horizon in (1, 5, 20, 60)}
    return {
        # Canonical UI contract plus backward-compatible names.
        "frozen_count": session_count,
        "session_count": session_count,
        "valid_session_count": valid_session_count,
        "valid_trade_date_count": len({
            item.get("trade_date") for item, _ in sessions if item.get("evidence_valid")
        }),
        "answered_count": session_count - abstain_count,
        "abstain_count": abstain_count,
        "completed_outcome_count": sum(completed.values()),
        "pending_count": sum(max(0, session_count - count) for count in completed.values()),
        "completed_outcomes": completed,
        "outcome_progress": {
            str(horizon): {
                "completed": completed[str(horizon)],
                "pending": max(0, session_count - completed[str(horizon)]),
            }
            for horizon in (1, 5, 20, 60)
        },
        "shadow_root_refs": [_portable_ref(item) for item in roots if item.exists()],
    }


def _environment() -> dict[str, Any]:
    packages = {}
    for name in ("akshare", "baostock", "pyarrow", "pandas", "scikit-learn", "lightgbm", "xgboost", "torch", "joblib"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True, capture_output=True, check=False).stdout.strip()
    except OSError:
        commit = None
    return {"python": platform.python_version(), "platform": platform.platform(), "git_commit": commit, "packages": packages}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT / path


def _portable_ref(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    import hashlib
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
