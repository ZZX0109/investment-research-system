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
    shadow = _shadow_summary(_resolve(args.shadow_root))
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
    payload: dict[str, Any] = {
        "schema_version": "cn-research-backend-acceptance-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_report_ref": _portable_ref(run_path),
        "status": "blocked" if run.get("status") == "blocked" else "partial" if reasons else "complete",
        "data_tier": "research_pit",
        "research_only": True,
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
    print(args.output)
    return 2 if payload["status"] == "blocked" else 0


def _task_status(tasks: dict[str, Any], task: str) -> dict[str, Any]:
    matches = [(key, value) for key, value in tasks.items() if key.endswith(f"/{task}")]
    if not matches:
        return {"status": "unavailable", "gating_reasons": ["task_artifact_missing"]}
    return {"status": "available" if any(value.get("status") == "research_only" for _, value in matches) else str(matches[0][1].get("status", "unavailable")), "scopes": {key: value for key, value in matches}}


def _artifact_evidence(run: dict[str, Any]) -> dict[str, Any]:
    """Validate task manifests when a task actually produced one.

    A partial/free-data run is allowed to have no artifacts, but the absence
    is explicit and cannot be mistaken for an empty prediction object.  When
    manifests exist, their task and governance fields are checked here and
    model hashes are compared across tasks to catch accidental reuse.
    """
    entries: list[dict[str, Any]] = []
    missing: list[str] = []
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
        model_hash = hashes.get("model") or hashes.get("model_file")
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
        entries.append({"scope": scope, "status": "complete" if not reasons else "blocked", "manifest_ref": _portable_ref(path), "task": payload.get("task"), "model_hash": model_hash, "reasons": reasons})
    reused = {key: scopes for key, scopes in model_hashes.items() if len({item.rsplit("/", 1)[-1] for item in scopes}) > 1}
    return {"entries": entries, "missing_tasks": missing, "reused_model_hashes": reused}


def _quality_status(item: dict[str, Any]) -> str:
    if item.get("status") in {"unsupported", "fetch_failed"}:
        return "unavailable" if item.get("status") == "fetch_failed" else "missing"
    if item.get("degraded_reason") or len(item.get("provider_chain", [])) > 1 or item.get("status") == "partial":
        return "degraded"
    return "complete" if item.get("status") in {"backfilled", "complete"} else "unavailable"


def _shadow_summary(root: Path) -> dict[str, Any]:
    sessions = []
    if root.is_dir():
        for path in (root / "sessions").rglob("*.json") if (root / "sessions").is_dir() else []:
            try:
                sessions.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    outcomes = Counter()
    for session in sessions:
        base = root / "outcomes" / str(session.get("id"))
        for path in base.glob("*.json") if base.is_dir() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("data_complete"):
                    outcomes[str(item.get("horizon_sessions"))] += 1
            except (OSError, ValueError):
                continue
    return {
        "session_count": len(sessions),
        "valid_session_count": sum(bool(item.get("evidence_valid")) for item in sessions),
        "abstain_count": sum(bool(item.get("abstained")) for item in sessions),
        "completed_outcomes": dict(outcomes),
        "shadow_root_ref": _portable_ref(root) if root.exists() else None,
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


if __name__ == "__main__":
    raise SystemExit(main())
