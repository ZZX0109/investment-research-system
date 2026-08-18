#!/usr/bin/env python3
"""GPU0-only, resumable deep-model optimization after the long-term baseline.

The controller deliberately runs one GPU stage at a time.  It first screens
four sequence architectures, selects the two strongest candidates per target
from holdout ranking quality, then runs larger multi-seed refinements and the
StockMixer/MASTER panel comparison.  Every child writes an immutable artifact;
restarting this controller skips completed artifacts and retries recoverable
resource failures with a smaller batch.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.resource_guard import ResourceMonitor, recommended_threads

TARGETS = (
    "excess_return_120d", "excess_return_240d",
    "future_max_drawdown_120d", "future_max_drawdown_240d",
)
ARCHITECTURES = ("patchtst", "tcn", "itransformer", "deep_mlp")
PANEL_ARCHITECTURES = ("stockmixer", "master")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-status", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--rebuild-index", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=30)
    parser.add_argument("--max-wait-hours", type=float, default=24.0)
    parser.add_argument("--minimum-free-gib", type=float, default=3.0)
    parser.add_argument("--monitor-interval", type=float, default=5.0)
    parser.add_argument("--max-retries", type=int, default=2)
    return parser.parse_args()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _env(batch_size: int) -> dict[str, str]:
    threads = recommended_threads()
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(PROJECT / "src"),
        "CUDA_VISIBLE_DEVICES": "0",
        "INVESTMENT_RESEARCH_TORCH_DEVICE": "cuda",
        "INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION": "0.85",
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
    return env


def _baseline_complete(path: Path) -> bool:
    return (_read(path, {}) or {}).get("status") in {
        "long_term_baseline_completed_auxiliary_short_horizon_queued",
        "long_term_baseline_completed_primary_and_auxiliary",
    }


def _sequence_report(root: Path, task: str, architecture: str, variant: str) -> Path:
    return root / "cn" / "close_confirmed" / "cn_equity_core" / task / "sequence" / architecture / "variants" / variant / "sequence_evaluation.json"


def _panel_report(root: Path, task: str, architecture: str, variant: str) -> Path:
    return root / "cn" / "close_confirmed" / "cn_equity_core" / task / "panel" / architecture / "variants" / variant / "sequence_evaluation.json"


def _metric(payload: dict, task: str) -> float:
    metrics = ((payload.get("result") or {}).get("holdout_metrics") or {})
    key = "risk_rank_ic" if task.startswith("future_max_drawdown_") else "rank_ic"
    try:
        return float(metrics.get(key, float("-inf")))
    except (TypeError, ValueError):
        return float("-inf")


def _stage_completed(status: dict, identifier: str) -> bool:
    return any(item.get("id") == identifier and item.get("status") == "completed" for item in status.get("stages", []))


def _ensure_disk(args: argparse.Namespace, status: dict, status_path: Path) -> None:
    free = shutil.disk_usage(args.output_root).free
    if free >= int(args.minimum_free_gib * 1024 ** 3):
        return
    status.update({"status": "blocked_low_disk", "free_bytes": free, "required_free_gib": args.minimum_free_gib, "updated_at": _now()})
    _write(status_path, status)
    raise SystemExit(31)


def _clear_sequence_cache(root: Path, task: str | None = None) -> int:
    """Remove rebuildable sample caches only after every trial using them finished."""
    cache_root = root / "sequence-cache"
    if not cache_root.is_dir():
        return 0
    patterns = ("*.pkl",) if task is None else (f"{task}.pkl", f"{task}-*.pkl")
    removed = 0
    for pattern in patterns:
        for path in cache_root.glob(pattern):
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
    return removed


def _run(
    command: list[str], *, log_path: Path, monitor_path: Path, args: argparse.Namespace, batch_size: int,
) -> tuple[int, int, int]:
    """Run one isolated trial; OOM failures reduce only its batch size."""
    attempts = max(1, args.max_retries + 1)
    current_batch = batch_size
    for attempt in range(1, attempts + 1):
        command_with_batch = list(command)
        if "--batch-size" in command_with_batch:
            position = command_with_batch.index("--batch-size") + 1
            command_with_batch[position] = str(current_batch)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n=== attempt {attempt}/{attempts}; batch={current_batch} ===\n")
            process = subprocess.Popen(command_with_batch, cwd=PROJECT, env=_env(current_batch), stdout=log, stderr=subprocess.STDOUT)
            monitor = ResourceMonitor(monitor_path, interval_seconds=args.monitor_interval, pid=process.pid)
            monitor.start()
            exit_code = process.wait()
            monitor.stop()
            log.write(f"=== exit_code {exit_code} ===\n")
        if exit_code == 0:
            return 0, attempt, current_batch
        text = log_path.read_text(encoding="utf-8", errors="replace")[-20000:].lower()
        if "out of memory" in text or "cuda error" in text:
            current_batch = max(32, current_batch // 2)
        time.sleep(min(30, attempt * 5))
    return exit_code, attempts, current_batch


def _record_stage(status: dict, stage: dict) -> None:
    status["stages"] = [item for item in status.get("stages", []) if item.get("id") != stage["id"]] + [stage]


def _maximum_dates(task: str) -> int:
    """Keep enough pre-label history after the 240-day purge and holdout."""
    return 1500 if task.endswith("240d") else 1260


def _sequence_command(args: argparse.Namespace, task: str, architecture: str, variant: str, *, hidden: int, epochs: int, seeds: str, batch: int) -> list[str]:
    maximum_dates = _maximum_dates(task)
    return [
        sys.executable, str(PROJECT / "scripts/run_sequence_research_training.py"),
        "--sample-manifest-file", str(args.manifest_file), "--object-store", str(args.object_store),
        "--data-root", str(args.data_root), "--rebuild-index", str(args.rebuild_index), "--allow-research-only",
        "--output-root", str(args.output_root), "--task", task, "--architecture", architecture,
        "--variant", variant, "--cohort", "cn_equity_core", "--screen-symbols", "0",
        "--maximum-dates", str(maximum_dates), "--window", "20", "--hidden-size", str(hidden),
        "--layers", "3", "--max-epochs", str(epochs), "--patience", "5", "--batch-size", str(batch),
        "--learning-rate", "0.0007", "--dropout", "0.10", "--seeds", seeds,
        "--training-run-id", f"{args.output_root.name}-{task}-{architecture}-{variant}",
        "--sequence-cache", str(args.output_root / "sequence-cache" / f"{task}-{maximum_dates}.pkl"),
    ]


def _panel_command(args: argparse.Namespace, task: str, architecture: str, variant: str) -> list[str]:
    maximum_dates = _maximum_dates(task)
    return [
        sys.executable, str(PROJECT / "scripts/run_panel_research_training.py"),
        "--sample-manifest-file", str(args.manifest_file), "--object-store", str(args.object_store),
        "--data-root", str(args.data_root), "--rebuild-index", str(args.rebuild_index), "--allow-research-only",
        "--output-root", str(args.output_root), "--task", task, "--architecture", architecture,
        "--variant", variant, "--cohort", "cn_equity_core", "--maximum-dates", str(maximum_dates),
        "--window", "20", "--batch-dates", "16", "--max-epochs", "24", "--hidden-size", "128",
        "--training-run-id", f"{args.output_root.name}-{task}-{architecture}-{variant}",
        "--sequence-cache", str(args.output_root / "sequence-cache" / f"{task}-{maximum_dates}.pkl"),
    ]


def main() -> int:
    args = _args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    status_path = args.output_root / "deep-optimization-status.json"
    status = _read(status_path, {}) or {"schema_version": "long-term-deep-optimization-v1", "run_id": args.output_root.name, "started_at": _now(), "stages": []}
    status.update({"status": "waiting_for_baseline", "updated_at": _now(), "resource_policy": {"gpu": "0 only", "gpu_memory_fraction": 0.85, "cpu_threads": recommended_threads(), "sequential_gpu_jobs": True, "adaptive_oom_batch": True}})
    _write(status_path, status)
    deadline = time.monotonic() + args.max_wait_hours * 3600
    while not _baseline_complete(args.baseline_status):
        baseline = _read(args.baseline_status, {}) or {}
        if str(baseline.get("status", "")).startswith(("failed", "blocked")):
            status.update({"status": "blocked_baseline", "baseline_status": baseline.get("status"), "updated_at": _now()})
            _write(status_path, status)
            return 20
        if time.monotonic() >= deadline:
            status.update({"status": "blocked_baseline_timeout", "updated_at": _now()})
            _write(status_path, status)
            return 21
        time.sleep(max(5, args.wait_seconds))

    # Stage 1: broad but low-cost screening.  One seed keeps the search broad.
    status.update({"status": "screening_sequence_models", "updated_at": _now()})
    _write(status_path, status)
    for task in TARGETS:
        for architecture in ARCHITECTURES:
            identifier = f"screen:{task}:{architecture}"
            report = _sequence_report(args.output_root, task, architecture, "screen")
            if report.is_file() or _stage_completed(status, identifier):
                _record_stage(status, {"id": identifier, "status": "completed", "resumed": True, "report": str(report)})
                _write(status_path, status)
                continue
            _ensure_disk(args, status, status_path)
            stage = {"id": identifier, "kind": "sequence_screen", "task": task, "architecture": architecture, "status": "running", "started_at": _now()}
            _record_stage(status, stage); _write(status_path, status)
            code, attempts, batch = _run(_sequence_command(args, task, architecture, "screen", hidden=96, epochs=8, seeds="42", batch=512), log_path=args.output_root / "logs" / f"{identifier}.log", monitor_path=args.output_root / "monitoring" / f"{identifier}.jsonl", args=args, batch_size=512)
            stage.update({"status": "completed" if code == 0 else "failed", "exit_code": code, "attempts": attempts, "final_batch_size": batch, "report": str(report), "finished_at": _now()})
            _record_stage(status, stage); _write(status_path, status)
            if code != 0:
                status.update({"status": "failed_screen", "updated_at": _now()}); _write(status_path, status); return code

    # Screen reports are immutable; their large row/sequence caches are no
    # longer needed and would otherwise crowd out multi-seed refinement.
    status["screen_cache_files_released"] = _clear_sequence_cache(args.output_root)
    _write(status_path, status)

    # Stage 2: conditional promotion, using the two strongest screen reports
    # per task.  This is the automatic judgement step rather than blindly
    # spending GPU time on every weak architecture.
    status.update({"status": "refining_selected_sequence_models", "updated_at": _now(), "selected": {}})
    for task in TARGETS:
        ranked = sorted(((_metric(_read(_sequence_report(args.output_root, task, architecture, "screen"), {}) or {}, task), architecture) for architecture in ARCHITECTURES), reverse=True)
        winners = [architecture for _score, architecture in ranked[:2]]
        status["selected"][task] = [{"architecture": architecture, "screen_holdout_metric": score} for score, architecture in ranked]
        _write(status_path, status)
        for architecture in winners:
            for variant, hidden in (("refine-h128", 128), ("refine-h256", 256)):
                identifier = f"refine:{task}:{architecture}:{variant}"
                report = _sequence_report(args.output_root, task, architecture, variant)
                if report.is_file() or _stage_completed(status, identifier):
                    _record_stage(status, {"id": identifier, "status": "completed", "resumed": True, "report": str(report)})
                    _write(status_path, status); continue
                _ensure_disk(args, status, status_path)
                stage = {"id": identifier, "kind": "sequence_refinement", "task": task, "architecture": architecture, "variant": variant, "status": "running", "started_at": _now()}
                _record_stage(status, stage); _write(status_path, status)
                code, attempts, batch = _run(_sequence_command(args, task, architecture, variant, hidden=hidden, epochs=24, seeds="42,2026,3407", batch=768), log_path=args.output_root / "logs" / f"{identifier}.log", monitor_path=args.output_root / "monitoring" / f"{identifier}.jsonl", args=args, batch_size=768)
                stage.update({"status": "completed" if code == 0 else "failed", "exit_code": code, "attempts": attempts, "final_batch_size": batch, "report": str(report), "finished_at": _now()})
                _record_stage(status, stage); _write(status_path, status)
                if code != 0:
                    status.update({"status": "failed_refinement", "updated_at": _now()}); _write(status_path, status); return code
        _clear_sequence_cache(args.output_root, task)

    # Stage 3: StockMixer and MASTER are run for every long-horizon target.
    status.update({"status": "running_panel_models", "updated_at": _now()}); _write(status_path, status)
    for task in TARGETS:
        for architecture in PANEL_ARCHITECTURES:
            identifier = f"panel:{task}:{architecture}"
            report = _panel_report(args.output_root, task, architecture, "full")
            if report.is_file() or _stage_completed(status, identifier):
                _record_stage(status, {"id": identifier, "status": "completed", "resumed": True, "report": str(report)})
                _write(status_path, status); continue
            _ensure_disk(args, status, status_path)
            stage = {"id": identifier, "kind": "panel", "task": task, "architecture": architecture, "status": "running", "started_at": _now()}
            _record_stage(status, stage); _write(status_path, status)
            code, attempts, batch = _run(_panel_command(args, task, architecture, "full"), log_path=args.output_root / "logs" / f"{identifier}.log", monitor_path=args.output_root / "monitoring" / f"{identifier}.jsonl", args=args, batch_size=512)
            stage.update({"status": "completed" if code == 0 else "failed", "exit_code": code, "attempts": attempts, "final_batch_size": batch, "report": str(report), "finished_at": _now()})
            _record_stage(status, stage); _write(status_path, status)
            if code != 0:
                status.update({"status": "failed_panel", "updated_at": _now()}); _write(status_path, status); return code
        _clear_sequence_cache(args.output_root, task)

    status.update({"status": "completed_research_only", "finished_at": _now(), "updated_at": _now()})
    _write(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
