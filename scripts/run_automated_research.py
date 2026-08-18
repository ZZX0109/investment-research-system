#!/usr/bin/env python3
"""Run the research training matrix with stage-level resume support.

Each tabular task and sequence architecture is an independent subprocess. A
successful stage writes an atomic marker only after its expected artifacts are
valid. Re-running the same ``--run-id`` therefore skips completed stages and
retries only missing or incomplete stages. This is intentionally research-only
and never changes deployment eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT = Path(__file__).resolve().parent.parent
TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")
ARCHITECTURES = ("patchtst", "tcn", "itransformer", "deep_mlp")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run resumable research-only training stages")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--sample-manifest-file",
        type=Path,
        default=Path("artifacts/free_research_models/runs/retrain-v42-20260814/manifest-lists/cn_equity_core.json"),
    )
    parser.add_argument("--object-store", type=Path, default=Path("var/cn-research/parquet"))
    parser.add_argument("--data-root", type=Path, default=Path("var/cn-research"))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--cohort", choices=("cn_equity_core", "cn_etf_benchmark"), default="cn_equity_core")
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--architectures", nargs="+", choices=ARCHITECTURES, default=list(ARCHITECTURES))
    parser.add_argument("--window", type=int, choices=(20, 60, 120), default=60)
    parser.add_argument("--screen-symbols", type=int, default=20)
    parser.add_argument("--maximum-dates", type=int, default=1260)
    parser.add_argument("--device", choices=("cuda", "cpu", "auto"), default="cuda")
    parser.add_argument("--gpu-memory-fraction", type=float, default=0.80)
    parser.add_argument("--sequence-batch-size", type=int, default=128)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT / path


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _tabular_artifacts(root: Path, cohort: str, task: str) -> Path:
    return root / "cn" / "close_confirmed" / cohort / task


def _sequence_artifacts(root: Path, cohort: str, task: str, architecture: str) -> Path:
    return _tabular_artifacts(root, cohort, task) / "sequence" / architecture


def _artifacts_complete(
    *,
    root: Path,
    cohort: str,
    task: str,
    architecture: str | None,
    stage_run_id: str,
) -> bool:
    if architecture is None:
        scope = _tabular_artifacts(root, cohort, task)
        required = (scope / "evaluation.json", scope / "task_manifest.json", scope / "research_model_roster.json")
        manifest = _read_json(scope / "task_manifest.json")
        return all(path.is_file() and path.stat().st_size > 0 for path in required) and bool(
            manifest and manifest.get("training_run_id") == stage_run_id
        )
    scope = _sequence_artifacts(root, cohort, task, architecture)
    required = (scope / "sequence_evaluation.json", scope / "sequence_manifest.json", scope / "model.pt")
    manifest = _read_json(scope / "sequence_manifest.json")
    # The native sequence manifest intentionally does not carry the runner's
    # training_run_id. Validate its immutable task/architecture identity
    # instead; the stage marker records the run-specific identity.
    return all(path.is_file() and path.stat().st_size > 0 for path in required) and bool(
        manifest
        and manifest.get("task") == task
        and manifest.get("architecture") == architecture
        and manifest.get("status") == "research_only"
    )


def _stage_name(task: str, architecture: str | None) -> str:
    return f"tabular_{task}" if architecture is None else f"sequence_{task}_{architecture}"


def _build_environment(args: argparse.Namespace) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(PROJECT / "src"),
            "CUDA_VISIBLE_DEVICES": "0" if args.device == "cuda" else environment.get("CUDA_VISIBLE_DEVICES", ""),
            "OMP_NUM_THREADS": "8",
            "MKL_NUM_THREADS": "8",
            "INVESTMENT_RESEARCH_SEQUENCE_BATCH_SIZE": str(args.sequence_batch_size),
        }
    )
    if args.device == "cuda":
        environment["INVESTMENT_RESEARCH_TORCH_DEVICE"] = "cuda"
        environment["INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION"] = str(args.gpu_memory_fraction)
    elif args.device == "cpu":
        environment["INVESTMENT_RESEARCH_TORCH_DEVICE"] = "cpu"
    return environment


def _command(
    *,
    args: argparse.Namespace,
    output_root: Path,
    task: str,
    architecture: str | None,
    stage_run_id: str,
) -> list[str]:
    if architecture is None:
        return [
            sys.executable,
            str(PROJECT / "scripts/run_free_research_training.py"),
            "--sample-manifest-file",
            str(_absolute(args.sample_manifest_file)),
            "--object-store",
            str(_absolute(args.object_store)),
            "--data-root",
            str(_absolute(args.data_root)),
            "--output-root",
            str(output_root),
            "--training-run-id",
            stage_run_id,
            "--tasks",
            task,
            "--cohort",
            args.cohort,
        ]
    return [
        sys.executable,
        str(PROJECT / "scripts/run_sequence_research_training.py"),
        "--sample-manifest-file",
        str(_absolute(args.sample_manifest_file)),
        "--object-store",
        str(_absolute(args.object_store)),
        "--data-root",
        str(_absolute(args.data_root)),
        "--output-root",
        str(output_root),
        "--task",
        task,
        "--architecture",
        architecture,
        "--window",
        str(args.window),
        "--cohort",
        args.cohort,
        "--training-run-id",
        stage_run_id,
        "--screen-symbols",
        str(args.screen_symbols),
        "--maximum-dates",
        str(args.maximum_dates),
    ]


def _stage_run_id(run_id: str, task: str, architecture: str | None) -> str:
    suffix = f"tabular-{task}" if architecture is None else f"sequence-{task}-{architecture}"
    return f"{run_id}-{suffix}"


def main() -> int:
    args = parse_args()
    output_root = _absolute(args.output_root or Path("artifacts/free_research_models/runs") / args.run_id)
    automation_root = output_root / "automation"
    stage_root = automation_root / "stages"
    output_root.mkdir(parents=True, exist_ok=True)
    stage_root.mkdir(parents=True, exist_ok=True)
    lock_path = automation_root / "run.lock"
    lock_handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"another automation process holds {lock_path}", file=sys.stderr)
        return 20

    resume_command = " ".join(
        [
            sys.executable,
            str(PROJECT / "scripts/run_automated_research.py"),
            "--run-id",
            args.run_id,
            "--sample-manifest-file",
            str(_absolute(args.sample_manifest_file)),
            "--cohort",
            args.cohort,
            "--device",
            args.device,
            "--sequence-batch-size",
            str(args.sequence_batch_size),
        ]
    )
    (automation_root / "resume_command.txt").write_text(resume_command + "\n", encoding="utf-8")
    environment = _build_environment(args)
    stages: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    ordered_stages = [(task, None) for task in args.tasks]
    ordered_stages.extend((task, architecture) for task in args.tasks for architecture in args.architectures)
    for task, architecture in ordered_stages:
        name = _stage_name(task, architecture)
        stage_run_id = _stage_run_id(args.run_id, task, architecture)
        marker = stage_root / f"{name}.json"
        log_path = stage_root / f"{name}.log"
        if args.no_resume is False and _artifacts_complete(
            root=output_root,
            cohort=args.cohort,
            task=task,
            architecture=architecture,
            stage_run_id=stage_run_id,
        ):
            result = {"name": name, "status": "skipped", "return_code": 0, "finished_at": _utc_now()}
            stages.append(result)
            _write_json_atomic(marker, result)
            print(f"SKIP {name}", flush=True)
            continue

        started_at = _utc_now()
        command = _command(
            args=args,
            output_root=output_root,
            task=task,
            architecture=architecture,
            stage_run_id=stage_run_id,
        )
        _write_json_atomic(marker, {"name": name, "status": "running", "started_at": started_at, "command": command})
        print(f"START {name} {started_at}", flush=True)
        with log_path.open("w", encoding="utf-8") as log_handle:
            log_handle.write("$ " + " ".join(command) + "\n")
            log_handle.flush()
            completed = subprocess.run(
                command,
                cwd=PROJECT,
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        finished_at = _utc_now()
        status = "completed" if completed.returncode == 0 and _artifacts_complete(
            root=output_root,
            cohort=args.cohort,
            task=task,
            architecture=architecture,
            stage_run_id=stage_run_id,
        ) else "failed"
        result = {
            "name": name,
            "status": status,
            "return_code": completed.returncode,
            "started_at": started_at,
            "finished_at": finished_at,
            "log": str(log_path.relative_to(output_root)),
        }
        stages.append(result)
        _write_json_atomic(marker, result)
        print(f"{status.upper()} {name} rc={completed.returncode}", flush=True)
        if status == "failed":
            failed.append(result)
            if args.stop_on_error:
                break

    report = {
        "schema_version": "investment-research-automation-report-v2",
        "status": "completed_with_failures" if failed else "completed",
        "research_only": True,
        "deployment_ready": False,
        "training_run_id": args.run_id,
        "generated_at": _utc_now(),
        "resumable": True,
        "device_policy": {
            "requested": args.device,
            "cuda_visible_devices": environment.get("CUDA_VISIBLE_DEVICES"),
            "torch_device": environment.get("INVESTMENT_RESEARCH_TORCH_DEVICE"),
        },
        "stage_count": len(stages),
        "failed_stage_count": len(failed),
        "stages": stages,
    }
    _write_json_atomic(automation_root / "summary.json", report)
    report_path = PROJECT / "output" / f"auto-experiment-report-{args.run_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(report_path, report)
    print(report_path)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
