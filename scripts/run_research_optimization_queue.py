#!/usr/bin/env python3
"""Resumable queue for the excess-return research program.

The queue intentionally gates training on a completed PIT rebuild and label
coverage audit.  It runs only the currently supported single-stock baselines;
panel architectures are recorded as a later stage because they require a
date-batched panel input contract.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.resource_guard import ResourceMonitor, recommended_threads
from investment_research.training.active_snapshot_guard import (
    ActiveSnapshotInputError,
    assert_training_sources,
    require_active_snapshot,
    require_training_snapshot_gate,
)
from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.snapshot_landing import SnapshotGateConfig
PRIMARY_TASKS = (
    "excess_return_120d", "excess_return_240d",
    "future_max_drawdown_120d", "future_max_drawdown_240d",
)
AUXILIARY_TASKS = (
    "future_quality_persistence_4q", "future_quality_persistence_8q",
)
TASKS = PRIMARY_TASKS + AUXILIARY_TASKS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-index", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument("--queue-root", type=Path, default=PROJECT / "artifacts/free_research_models/runs/research-optimization-v1")
    parser.add_argument("--wait-seconds", type=int, default=30)
    parser.add_argument("--max-wait-hours", type=float, default=12.0)
    parser.add_argument("--maximum-dates", type=int, default=1260)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--monitor-interval", type=float, default=5.0)
    parser.add_argument("--no-resume", action="store_true", help="ignore completed tasks and fold checkpoints")
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    index = args.rebuild_index if args.rebuild_index.is_absolute() else PROJECT / args.rebuild_index
    root = args.queue_root if args.queue_root.is_absolute() else PROJECT / args.queue_root
    data_root = args.data_root if args.data_root.is_absolute() else PROJECT / args.data_root
    object_store = args.object_store if args.object_store.is_absolute() else PROJECT / args.object_store
    status_path = root / "queue-status.json"
    status = {
        "schema_version": "research-optimization-queue-run-v1",
        "run_id": root.name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "waiting_for_rebuild",
        "gpu_policy": {"CUDA_VISIBLE_DEVICES": "0", "torch_device": "cuda"},
        "rebuild_index": str(index),
        "primary_tasks": list(PRIMARY_TASKS),
        "auxiliary_tasks": list(AUXILIARY_TASKS),
        "stages": [],
    }
    write_json(status_path, status)
    deadline = time.monotonic() + args.max_wait_hours * 3600
    while not index.is_file():
        if time.monotonic() >= deadline:
            status["status"] = "blocked_rebuild_timeout"
            write_json(status_path, status)
            return 20
        time.sleep(max(5, args.wait_seconds))

    rebuild = json.loads(index.read_text(encoding="utf-8"))
    context = rebuild.get("contexts", {}).get("close_confirmed", {})
    groups = context.get("sample_manifests", {})
    manifest_values = [value for values in groups.values() for value in values]
    if len(manifest_values) == 0:
        status["status"] = "blocked_empty_rebuild"
        write_json(status_path, status)
        return 21
    manifest_file = root / "manifest-lists" / "cn_optimization.json"
    write_json(manifest_file, {"sample_manifests": manifest_values})
    # The queue performs an audit before launching any child trainer.  Bind
    # that audit input to the same immutable active snapshot first; otherwise
    # a direct queue invocation could read a mutable object store while a
    # downloader is still writing even though the child command is guarded.
    try:
        active = require_active_snapshot(data_root)
        contract = load_long_term_training_config(PROJECT / "config/long_term_training.yaml")
        require_training_snapshot_gate(
            active,
            config=SnapshotGateConfig(
                required_datasets=set(contract.required_snapshot_datasets),
                minimum_financial_coverage=contract.minimum_financial_coverage,
            ),
            labels_mature=True,
        )
        assert_training_sources(active, manifest_file, object_store)
    except (ActiveSnapshotInputError, OSError, ValueError) as exc:
        status["status"] = "blocked_active_snapshot_gate"
        status["blocking_reasons"] = [str(exc)]
        write_json(status_path, status)
        return 23
    status["manifest_file"] = str(manifest_file)
    status["manifest_count"] = len(manifest_values)
    status["status"] = "auditing"
    write_json(status_path, status)

    audit_path = root / "data-audit.json"
    audit_command = [
        sys.executable, str(PROJECT / "scripts/audit_research_optimization_data.py"),
        "--sample-manifest-file", str(manifest_file),
        "--object-store", str(args.object_store if args.object_store.is_absolute() else PROJECT / args.object_store),
        "--output", str(audit_path),
        "--all-partitions",
    ]
    audit_log = root / "logs" / "data-audit.log"
    audit_code, audit_attempts = _run_logged(
        audit_command,
        audit_log,
        env=_environment(args.batch_size),
        monitor_path=root / "monitoring" / "data-audit.jsonl",
        monitor_interval=args.monitor_interval,
        max_retries=args.max_retries,
    )
    status["audit_exit_code"] = audit_code
    status["audit_attempts"] = audit_attempts
    status["audit_log"] = str(audit_log)
    status["audit_file"] = str(audit_path)
    audit_payload = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
    status["audit_status"] = audit_payload.get("status")
    if audit_code != 0 or audit_payload.get("status") != "ready_for_full_pool_baseline":
        status["status"] = "blocked_data_gate"
        write_json(status_path, status)
        return 22

    status["status"] = "running_long_term_baseline"
    write_json(status_path, status)
    for task in TASKS:
        output_path = root / "long_term" / f"{task}.json"
        predictions_path = root / "long_term" / f"{task}.predictions.parquet"
        checkpoint_path = root / "checkpoints" / task
        if not args.no_resume and _task_complete(output_path, predictions_path):
            status["stages"].append({
                "task": task,
                "task_role": "primary" if task in PRIMARY_TASKS else "auxiliary",
                "stage": "quarterly_long_term_baselines",
                "status": "skipped_completed",
                "resumed_at": datetime.now(timezone.utc).isoformat(),
                "output": str(output_path),
            })
            write_json(status_path, status)
            continue
        stage = {
            "task": task,
            "task_role": "primary" if task in PRIMARY_TASKS else "auxiliary",
            "stage": "quarterly_long_term_baselines",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "resume": not args.no_resume,
            "checkpoint_dir": str(checkpoint_path),
        }
        status["stages"].append(stage)
        write_json(status_path, status)
        command = [
            sys.executable, str(PROJECT / "scripts/run_long_term_training.py"),
            "--samples", str(manifest_file),
            "--object-store", str(args.object_store if args.object_store.is_absolute() else PROJECT / args.object_store),
            "--data-root", str(args.data_root if args.data_root.is_absolute() else PROJECT / args.data_root),
            "--rebuild-index", str(index),
            "--allow-research-only",
            "--target", task,
            "--output", str(output_path),
            "--predictions-output", str(predictions_path),
            "--checkpoint-dir", str(checkpoint_path),
        ]
        if args.no_resume:
            command.append("--no-resume")
        log_path = root / "logs" / f"{task}.log"
        exit_code, attempts = _run_logged(
            command,
            log_path,
            env=_environment(args.batch_size),
            monitor_path=root / "monitoring" / f"{task}.jsonl",
            monitor_interval=args.monitor_interval,
            max_retries=args.max_retries,
        )
        stage["exit_code"] = exit_code
        stage["attempts"] = attempts
        stage["log"] = str(log_path)
        stage["status"] = "completed" if exit_code == 0 else "failed"
        stage["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(status_path, status)
        if exit_code != 0:
            status["status"] = "failed_long_term_baseline"
            write_json(status_path, status)
            return exit_code
    status["status"] = "long_term_baseline_completed_primary_and_auxiliary"
    status["primary_baselines_completed"] = list(PRIMARY_TASKS)
    status["auxiliary_baselines_completed"] = list(AUXILIARY_TASKS)
    status["auxiliary_models"] = {"direction_1d": "observation_only", "direction_5d": "observation_only", "return_20d": "observation_only", "drawdown_20d": "observation_only"}
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(status_path, status)
    return 0


def _environment(batch_size: int) -> dict[str, str]:
    threads = recommended_threads()
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": str(PROJECT / "src"),
        "CUDA_VISIBLE_DEVICES": "0",
        "INVESTMENT_RESEARCH_TORCH_DEVICE": "cuda",
        "INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION": "0.80",
        "INVESTMENT_RESEARCH_USE_GPU": "1",
        "INVESTMENT_RESEARCH_SEQUENCE_BATCH_SIZE": str(batch_size),
        "INVESTMENT_RESEARCH_CPU_THREADS": str(threads),
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
        "OPENBLAS_NUM_THREADS": str(threads),
        "NUMEXPR_NUM_THREADS": str(threads),
        "OMP_DYNAMIC": "FALSE",
        "PYTHONUNBUFFERED": "1",
    })
    return environment


def _task_complete(output_path: Path, predictions_path: Path) -> bool:
    if not output_path.is_file() or not predictions_path.is_file():
        return False
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("status") == "research_only" and payload.get("deployment_ready") is False


def _run_logged(
    command: list[str],
    log_path: Path,
    *,
    env: dict[str, str],
    monitor_path: Path,
    monitor_interval: float,
    max_retries: int,
) -> tuple[int, int]:
    """Run a subprocess with a bounded retry loop and resource telemetry."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = max(1, max_retries + 1)
    last_code = 1
    for attempt in range(1, attempts + 1):
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n=== attempt {attempt}/{attempts} ===\n")
            log.flush()
            process = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT)
            monitor = ResourceMonitor(monitor_path, interval_seconds=monitor_interval, pid=process.pid)
            monitor.start()
            last_code = process.wait()
            monitor.stop()
            log.write(f"=== exit_code {last_code} ===\n")
        if last_code == 0:
            return 0, attempt
        if attempt < attempts:
            time.sleep(min(30, 5 * attempt))
    return last_code, attempts


if __name__ == "__main__":
    raise SystemExit(main())
