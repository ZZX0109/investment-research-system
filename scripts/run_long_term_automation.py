#!/usr/bin/env python3
"""Run the guarded long-term research DAG.

This is the single orchestration entry point described in the training handoff.
It deliberately separates a read-only ``dry-run`` from a ``formal`` run:

* dry-run parses the contract, snapshots and optional manifest list, writes a
  resource/stage plan, and never creates checkpoints or predictions;
* formal requires an active, hash-verified snapshot and a passing PIT gate
  before it can launch the existing per-target trainer.

The orchestrator never creates or changes ``active.json`` and never treats a
research-only rebuild as a formal input.  State is written atomically and the
queue/GPU locks are process locks, so stale lock files cannot block recovery.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any, Iterator

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.active_snapshot_guard import (  # noqa: E402
    ActiveSnapshotInputError,
    assert_training_sources,
    require_active_snapshot,
)
from investment_research.training.long_term_config import load_long_term_training_config  # noqa: E402
from investment_research.training.snapshot_landing import (  # noqa: E402
    SnapshotGateConfig,
    evaluate_snapshot_gate,
)

PRIMARY_TASKS = (
    "excess_return_120d",
    "excess_return_240d",
    "future_max_drawdown_120d",
    "future_max_drawdown_240d",
)
EXIT_DRY_RUN_BLOCKED = 20
EXIT_GATE_BLOCKED = 23
EXIT_STAGE_FAILED = 24


class LockBusy(RuntimeError):
    """A second orchestrator is already holding the same process lock."""


@contextmanager
def process_lock(path: Path, *, metadata: dict[str, Any]) -> Iterator[None]:
    """Acquire a non-blocking advisory lock and release it on every exit."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockBusy(f"lock_busy:{path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "formal"), required=True)
    parser.add_argument("--config", type=Path, default=PROJECT / "config/long_term_training.yaml")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--rebuild-index", type=Path, default=None,
                        help="immutable research rebuild used only for a dry-run/research plan")
    parser.add_argument("--samples", type=Path, default=None,
                        help="bound sample manifest list; required for formal mode")
    parser.add_argument("--sample-audit", type=Path, default=None,
                        help="pre-existing immutable sample audit used by dry-run")
    parser.add_argument("--run-root", type=Path, default=PROJECT / "artifacts/long_term_training/runs")
    parser.add_argument("--run-id", default=None, help="resume an explicit existing run id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--targets", nargs="+", default=None)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--stage-timeout-hours", type=float, default=24.0)
    parser.add_argument("--lock-root", type=Path, default=PROJECT / "var/locks")
    parser.add_argument("--skip-promotion", action="store_true",
                        help="formal-only: stop after target reports and artifact indexing")
    return parser.parse_args(argv)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _automation_code_hash() -> str:
    """Hash the orchestrator plus the guarded training modules it invokes."""
    paths = [
        Path(__file__),
        PROJECT / "src/investment_research/training/active_snapshot_guard.py",
        PROJECT / "src/investment_research/training/snapshot_landing.py",
        PROJECT / "src/investment_research/training/long_term_pipeline.py",
        PROJECT / "src/investment_research/training/long_term_config.py",
        PROJECT / "scripts/run_long_term_training.py",
        PROJECT / "scripts/audit_research_optimization_data.py",
    ]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(PROJECT)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    with temporary.open("r+", encoding="utf-8") as handle:
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_resume_id(base: Path) -> str | None:
    candidates = []
    for child in base.iterdir() if base.is_dir() else []:
        if not child.is_dir() or not (child / "run-manifest.json").is_file():
            continue
        status = _read_json(child / "run-status.json")
        if status.get("status") in {"succeeded", "failed_terminal"}:
            continue
        candidates.append((child.stat().st_mtime, child.name))
    return max(candidates)[1] if candidates else None


def _flatten_sample_refs(index: dict[str, Any]) -> list[str]:
    context = index.get("contexts", {}).get("close_confirmed", {})
    groups = context.get("sample_manifests", {}) if isinstance(context, dict) else {}
    if not isinstance(groups, dict):
        return []
    return [str(value) for values in groups.values() if isinstance(values, list) for value in values]


def _manifest_summary(path: Path | None, rebuild_path: Path | None = None) -> dict[str, Any]:
    if path is None:
        if rebuild_path is not None and rebuild_path.is_file():
            payload = _read_json(rebuild_path)
            context = payload.get("contexts", {}).get("close_confirmed", {})
            sample_groups = context.get("sample_manifests", {}) if isinstance(context, dict) else {}
            count = sum(len(values) for values in sample_groups.values() if isinstance(values, list)) if isinstance(sample_groups, dict) else 0
            return {
                "provided": False,
                "exists": True,
                "source": "rebuild_index",
                "path": str(rebuild_path.resolve()),
                "count": count,
                "sha256": _sha256(rebuild_path),
                "snapshot_id": context.get("snapshot_id") if isinstance(context, dict) else None,
                "snapshot_hash": context.get("snapshot_hash") if isinstance(context, dict) else None,
                "formal_binding": False,
            }
        return {"provided": False, "exists": False, "count": 0, "sha256": None, "formal_binding": False}
    path = path.resolve()
    if not path.is_file():
        return {"provided": True, "exists": False, "path": str(path), "count": 0, "sha256": None}
    payload = _read_json(path)
    values = payload.get("sample_manifests") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        values = []
    return {
        "provided": True,
        "exists": True,
        "path": str(path),
        "count": len(values),
        "sha256": _sha256(path),
        "snapshot_id": payload.get("market_snapshot_id"),
        "snapshot_hash": payload.get("market_snapshot_hash"),
    }


def _make_run_id(mode: str, dataset_hash: str, config_hash: str, code_hash: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"lt-{mode}-{stamp}-{dataset_hash[:12]}-{config_hash[:12]}-{code_hash[:12]}"


def _stage(status: dict[str, Any], name: str, state: str, **extra: Any) -> None:
    stages = status.setdefault("stages", [])
    existing = next((item for item in stages if item.get("name") == name), None)
    payload = {"name": name, "status": state, "updated_at": datetime.now(timezone.utc).isoformat(), **extra}
    if existing is None:
        stages.append(payload)
    else:
        existing.update(payload)


def _write_child_command(command: list[str], log_path: Path, *, timeout_seconds: float) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + shlex.join(command) + "\n")
        log.flush()
        try:
            process = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT)
            code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            log.write("timeout\n")
            return 124, "timeout"
        return code, "completed"


def _run_with_retries(command: list[str], log_path: Path, *, retries: int, timeout_seconds: float) -> tuple[int, int, str]:
    attempts = max(1, retries + 1)
    last_code = 1
    reason = "failed"
    for attempt in range(1, attempts + 1):
        last_code, reason = _write_child_command(command, log_path, timeout_seconds=timeout_seconds)
        if last_code == 0:
            return 0, attempt, reason
        if attempt < attempts:
            time.sleep(min(30, 5 * attempt))
    return last_code, attempts, reason


def _gate(args: argparse.Namespace, config) -> tuple[dict[str, Any], Any | None]:
    data_root = _resolve(args.data_root)
    evidence: dict[str, Any] = {"active_pointer": str(data_root / "active.json"), "active_available": False}
    try:
        active = require_active_snapshot(data_root)
    except (ActiveSnapshotInputError, OSError, ValueError) as exc:
        evidence["blocking_reasons"] = [f"active_snapshot_unavailable:{exc}"]
        return evidence, None
    evidence.update({
        "active_available": True,
        "snapshot_id": active.snapshot_id,
        "snapshot_manifest_hash": active.manifest_hash,
    })
    result = evaluate_snapshot_gate(
        active.manifest,
        config=SnapshotGateConfig(
            required_datasets=set(config.required_snapshot_datasets),
            minimum_financial_coverage=config.minimum_financial_coverage,
        ),
        labels_mature=True,
    )
    evidence.update({"passed": result.passed, "reasons": result.reasons, "dataset_names": result.dataset_names})
    return evidence, active


def _build_dry_run_plan(args: argparse.Namespace, config, gate: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    targets = list(args.targets or config.primary_targets)
    return {
        "status": "dry_run_complete" if gate.get("active_available") and gate.get("passed") else "dry_run_complete_blocked",
        "mode": "dry-run",
        "gate": gate,
        "manifest": manifest,
        "planned_stages": [
            {"name": "gate", "action": "read_only_snapshot_and_pit_gate"},
            {"name": "readiness_audit", "action": "audit_long_term_readiness"},
            {"name": "data_audit", "action": "audit_research_optimization_data"},
            *[{"name": f"baseline:{target}", "action": "run_long_term_training"} for target in targets],
            {"name": "promotion", "action": "evaluate_long_term_promotion"},
            {"name": "artifact_index", "action": "index_training_artifacts"},
        ],
        "safety": {
            "writes_model_weights": False,
            "writes_predictions": False,
            "mutates_active_pointer": False,
            "reads_mutable_landing": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = _resolve(args.config)
    config = load_long_term_training_config(config_path)
    targets = list(args.targets or config.primary_targets)
    invalid = sorted(set(targets) - set(config.targets))
    if invalid:
        raise SystemExit("targets are not in long-term config: " + ",".join(invalid))
    if args.mode == "formal" and args.samples is None:
        raise SystemExit("formal mode requires --samples bound to the active snapshot")

    rebuild_path = _resolve(args.rebuild_index) if args.rebuild_index else None
    samples_path = _resolve(args.samples) if args.samples else None
    dataset_path = rebuild_path if rebuild_path and rebuild_path.is_file() else samples_path
    dataset_hash = _sha256(dataset_path) if dataset_path and dataset_path.is_file() else "unbound"
    config_hash = config.canonical_hash()
    code_hash = _automation_code_hash()
    base_root = _resolve(args.run_root)
    run_id = args.run_id or (_find_resume_id(base_root) if args.resume else None)
    if run_id is None:
        run_id = _make_run_id(args.mode, dataset_hash, config_hash, code_hash)
    run_dir = base_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    status_path = run_dir / "run-status.json"
    manifest_path = run_dir / "run-manifest.json"
    manifest_summary = _manifest_summary(samples_path, rebuild_path)
    run_manifest = {
        "schema_version": "long-term-automation-run-v1",
        "run_id": run_id,
        "mode": args.mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT),
        "config": str(config_path.resolve()),
        "config_hash": config_hash,
        "code_hash": code_hash,
        "dataset_hash": dataset_hash,
        "rebuild_index": str(rebuild_path) if rebuild_path else None,
        "samples": str(samples_path) if samples_path else None,
        "object_store": str(_resolve(args.object_store)),
        "data_root": str(_resolve(args.data_root)),
        "targets": targets,
        "environment": {
            "python": sys.version.split()[0],
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "0"),
            "gpu_policy": "GPU0-only; formal stages hold gpu0-training.lock",
            "max_retries": args.max_retries,
            "stage_timeout_hours": args.stage_timeout_hours,
        },
        "formal_pit_required": True,
        "deployment_ready": False,
    }
    _atomic_json(manifest_path, run_manifest)
    status: dict[str, Any] = {
        "schema_version": "long-term-automation-status-v1",
        "run_id": run_id,
        "mode": args.mode,
        "status": "preflight",
        "run_manifest": str(manifest_path),
        "stages": [],
    }
    _atomic_json(status_path, status)

    lock_root = _resolve(args.lock_root)
    lock_metadata = {"pid": os.getpid(), "run_id": run_id, "mode": args.mode, "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        with process_lock(lock_root / "long-term-queue.lock", metadata=lock_metadata):
            if args.mode == "formal":
                with process_lock(lock_root / "gpu0-training.lock", metadata=lock_metadata):
                    return _run_locked(args, config, targets, run_dir, status_path, status, run_manifest, manifest_summary)
            return _run_locked(args, config, targets, run_dir, status_path, status, run_manifest, manifest_summary)
    except LockBusy as exc:
        status.update({"status": "blocked_lock", "blocking_reasons": [str(exc)]})
        _atomic_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return EXIT_GATE_BLOCKED


def _run_locked(args, config, targets, run_dir: Path, status_path: Path, status: dict[str, Any], run_manifest: dict[str, Any], manifest_summary: dict[str, Any]) -> int:
    gate, active = _gate(args, config)
    _stage(status, "gate", "passed" if gate.get("passed") else "blocked", evidence=gate)
    status["gate"] = gate
    _atomic_json(status_path, status)
    if args.mode == "dry-run":
        readiness_path = run_dir / "gate" / "readiness.json"
        readiness_command = [
            sys.executable, str(PROJECT / "scripts/audit_long_term_readiness.py"),
            "--project-root", str(PROJECT), "--output", str(readiness_path),
        ]
        _stage(status, "readiness_audit", "running", command=readiness_command)
        _atomic_json(status_path, status)
        readiness_code, readiness_attempts, readiness_reason = _run_with_retries(
            readiness_command, run_dir / "logs" / "readiness.log",
            retries=0, timeout_seconds=args.stage_timeout_hours * 3600,
        )
        readiness = _read_json(readiness_path)
        _stage(status, "readiness_audit", "passed" if readiness.get("status") == "complete" else "blocked", exit_code=readiness_code, attempts=readiness_attempts, output=str(readiness_path), reason=readiness_reason, blocking_reasons=readiness.get("blocking_reasons", []))
        status["readiness_audit"] = readiness
        plan = _build_dry_run_plan(args, config, gate, manifest_summary)
        if plan["status"] == "dry_run_complete" and readiness.get("status") != "complete":
            plan["status"] = "dry_run_complete_blocked"
            plan.setdefault("blocking_reasons", []).append("readiness_audit_blocked")
        status.update(plan)
        _atomic_json(run_dir / "gate" / "dry-run-report.json", plan)
        _atomic_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return 0 if plan["status"] == "dry_run_complete" else EXIT_DRY_RUN_BLOCKED

    if active is None or not gate.get("passed"):
        status.update({"status": "blocked_gate", "blocking_reasons": gate.get("blocking_reasons") or gate.get("reasons") or ["active_snapshot_gate_unavailable"]})
        _atomic_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return EXIT_GATE_BLOCKED
    samples_path = _resolve(args.samples)
    object_store = _resolve(args.object_store)
    try:
        assert_training_sources(active, samples_path.resolve(), object_store.resolve())
    except (ActiveSnapshotInputError, OSError, ValueError) as exc:
        status.update({"status": "blocked_input_binding", "blocking_reasons": [str(exc)]})
        _atomic_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return EXIT_GATE_BLOCKED

    audit_path = run_dir / "gate" / "data-audit.json"
    audit_command = [
        sys.executable, str(PROJECT / "scripts/audit_research_optimization_data.py"),
        "--sample-manifest-file", str(samples_path), "--object-store", str(object_store),
        "--output", str(audit_path), "--all-partitions",
    ]
    _stage(status, "data_audit", "running", command=audit_command)
    _atomic_json(status_path, status)
    code, attempts, reason = _run_with_retries(
        audit_command, run_dir / "logs" / "data-audit.log",
        retries=args.max_retries, timeout_seconds=args.stage_timeout_hours * 3600,
    )
    audit = _read_json(audit_path)
    _stage(status, "data_audit", "passed" if code == 0 and audit.get("status") == "ready_for_full_pool_baseline" else "blocked", exit_code=code, attempts=attempts, audit=str(audit_path), reason=reason)
    status["data_audit"] = audit
    _atomic_json(status_path, status)
    if code != 0 or audit.get("status") != "ready_for_full_pool_baseline":
        status.update({"status": "blocked_data_gate", "blocking_reasons": ["sample_data_audit_not_ready"]})
        _atomic_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return EXIT_GATE_BLOCKED

    for target in targets:
        output = run_dir / "stages" / target / "report.json"
        predictions = run_dir / "predictions" / f"{target}.parquet"
        checkpoint = run_dir / "checkpoints" / target
        if args.resume and _read_json(output).get("status") in {"research_only", "formal"} and predictions.is_file():
            _stage(status, f"baseline:{target}", "skipped_reused", output=str(output), predictions=str(predictions))
            continue
        command = [
            sys.executable, str(PROJECT / "scripts/run_long_term_training.py"),
            "--samples", str(samples_path), "--config", str(_resolve(args.config)),
            "--data-root", str(_resolve(args.data_root)), "--object-store", str(object_store),
            "--target", target, "--output", str(output), "--predictions-output", str(predictions),
            "--checkpoint-dir", str(checkpoint),
        ]
        _stage(status, f"baseline:{target}", "running", command=command)
        _atomic_json(status_path, status)
        code, attempts, reason = _run_with_retries(
            command, run_dir / "logs" / f"{target}.log",
            retries=args.max_retries, timeout_seconds=args.stage_timeout_hours * 3600,
        )
        report = _read_json(output)
        good = code == 0 and report.get("status") in {"research_only", "formal"}
        _stage(status, f"baseline:{target}", "succeeded" if good else "failed_terminal", exit_code=code, attempts=attempts, output=str(output), predictions=str(predictions), reason=reason)
        _atomic_json(status_path, status)
        if not good:
            status.update({"status": "failed_terminal", "blocking_reasons": [f"training_stage_failed:{target}"]})
            _atomic_json(status_path, status)
            print(json.dumps(status, ensure_ascii=False))
            return EXIT_STAGE_FAILED

    promotion_states: list[str] = []
    if args.skip_promotion:
        _stage(status, "promotion", "skipped", reason="explicit_skip_promotion")
    else:
        for target in targets:
            report_path = run_dir / "stages" / target / "report.json"
            promotion_path = run_dir / "promotion" / f"{target}.json"
            promotion_command = [
                sys.executable, str(PROJECT / "scripts/evaluate_long_term_promotion.py"),
                "--report", str(report_path), "--shadow-directory", str(PROJECT / "artifacts/research_shadow"),
                "--config", str(_resolve(args.config)), "--output", str(promotion_path),
            ]
            _stage(status, f"promotion:{target}", "running", command=promotion_command)
            _atomic_json(status_path, status)
            code, attempts, reason = _run_with_retries(
                promotion_command, run_dir / "logs" / f"promotion-{target}.log",
                retries=args.max_retries, timeout_seconds=args.stage_timeout_hours * 3600,
            )
            result = _read_json(promotion_path)
            candidate = result.get("status") == "candidate_for_review"
            state = "candidate_for_review" if candidate else "blocked_review"
            promotion_states.append(state)
            _stage(status, f"promotion:{target}", state, exit_code=code, attempts=attempts, output=str(promotion_path), reason=reason, blocking_reasons=result.get("blocking_reasons", []))
            _atomic_json(status_path, status)

    index_output = run_dir / "artifact-index.json"
    index_command = [sys.executable, str(PROJECT / "scripts/index_training_artifacts.py"), "--root", str(run_dir), "--output", str(index_output), "--kind", "long_term_automation_artifact", "--retention-days", "730"]
    _stage(status, "artifact_index", "running", command=index_command)
    _atomic_json(status_path, status)
    code, attempts, reason = _run_with_retries(index_command, run_dir / "logs" / "artifact-index.log", retries=args.max_retries, timeout_seconds=args.stage_timeout_hours * 3600)
    _stage(status, "artifact_index", "succeeded" if code == 0 else "failed_terminal", exit_code=code, attempts=attempts, output=str(index_output), reason=reason)
    _atomic_json(status_path, status)
    if code != 0:
        status.update({"status": "failed_terminal", "blocking_reasons": ["artifact_index_failed"]})
        _atomic_json(status_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return EXIT_STAGE_FAILED

    review_required = args.skip_promotion or (bool(promotion_states) and any(item != "candidate_for_review" for item in promotion_states))
    status.update({"status": "completed_review_required" if review_required else "succeeded", "deployment_ready": False, "promotion_states": promotion_states, "finished_at": datetime.now(timezone.utc).isoformat(), "success_marker": str(run_dir / "SUCCESS")})
    _atomic_json(status_path, status)
    (run_dir / "SUCCESS").write_text("formal training stages completed; promotion remains review-only\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
