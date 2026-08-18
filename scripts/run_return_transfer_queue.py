#!/usr/bin/env python3
"""GPU0-only, resumable 240-session relative-return experiment queue.

Each trial owns immutable artifacts and epoch checkpoints.  Restarting this
controller safely skips completed trials and resumes an interrupted trial from
its latest fold/final epoch checkpoint.  Trials are intentionally sequential:
one 4090 is faster and more stable than competing GPU processes.
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

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from investment_research.training.resource_guard import ResourceMonitor, recommended_threads


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-manifest-file", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--rebuild-index", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--init-checkpoint", type=Path, required=True)
    parser.add_argument("--sequence-cache", type=Path, required=True)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--monitor-interval", type=float, default=5.0)
    return parser.parse_args()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def trials() -> list[dict]:
    # First five reuse the completed StockMixer representation.  Challengers
    # keep the same data/holdout definition, so selection is comparable.
    return [
        {"id": "warm-lr3e-4-s42", "architecture": "stockmixer", "hidden": 128, "lr": 3e-4, "seed": 42, "warm": True},
        {"id": "warm-lr7e-4-s42", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 42, "warm": True},
        {"id": "warm-lr15e-4-s42", "architecture": "stockmixer", "hidden": 128, "lr": 1.5e-3, "seed": 42, "warm": True},
        {"id": "warm-lr7e-4-s2026", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 2026, "warm": True},
        {"id": "warm-lr7e-4-s3407", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 3407, "warm": True},
        {"id": "stockmixer-h256", "architecture": "stockmixer", "hidden": 256, "lr": 7e-4, "seed": 42, "warm": False},
        {"id": "master-h128", "architecture": "master", "hidden": 128, "lr": 5e-4, "seed": 42, "warm": False},
        {"id": "master-h256", "architecture": "master", "hidden": 256, "lr": 5e-4, "seed": 42, "warm": False},
        # Stability: independent end-date windows rather than one favourable
        # holdout.  No cache is shared across these clipped universes.
        {"id": "stability-end-126", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 42, "warm": True, "evaluation_end_offset": 126, "holdout_sessions": 126},
        {"id": "stability-end-180", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 42, "warm": True, "evaluation_end_offset": 180, "holdout_sessions": 126},
        # Controlled feature ablations establish whether existing financial
        # and valuation features add value; they are not invented features.
        {"id": "ablate-fundamental", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 42, "warm": False, "exclude": ["fundamental_", "missing__fundamental_"]},
        {"id": "ablate-valuation", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 42, "warm": False, "exclude": ["valuation_", "missing__valuation_"]},
        # A separate downside model supplies the risk leg of the eventual
        # potential-plus-risk scorecard under the identical panel contract.
        {"id": "risk-stockmixer-transfer", "task": "future_max_drawdown_240d", "architecture": "stockmixer", "hidden": 128, "lr": 7e-4, "seed": 42, "warm": True},
        {"id": "risk-master-h256", "task": "future_max_drawdown_240d", "architecture": "master", "hidden": 256, "lr": 5e-4, "seed": 42, "warm": False},
    ]


def report_path(root: Path, trial: dict) -> Path:
    return root / "cn/close_confirmed/cn_equity_core" / trial.get("task", "excess_return_240d") / "panel" / trial["architecture"] / "variants" / trial["id"] / "sequence_evaluation.json"


def env() -> dict[str, str]:
    threads = recommended_threads()
    values = os.environ.copy()
    values.update({"PYTHONPATH": str(PROJECT / "src"), "CUDA_VISIBLE_DEVICES": "0",
                   "INVESTMENT_RESEARCH_TORCH_DEVICE": "cuda", "INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION": "0.90",
                   "OMP_NUM_THREADS": str(threads), "MKL_NUM_THREADS": str(threads),
                   "OPENBLAS_NUM_THREADS": str(threads), "NUMEXPR_NUM_THREADS": str(threads),
                   "OMP_DYNAMIC": "FALSE", "PYTHONUNBUFFERED": "1"})
    return values


def command(a: argparse.Namespace, trial: dict) -> list[str]:
    command = [sys.executable, str(PROJECT / "scripts/run_panel_research_training.py"),
        "--sample-manifest-file", str(a.sample_manifest_file), "--object-store", str(a.object_store),
        "--data-root", str(a.data_root), "--rebuild-index", str(a.rebuild_index), "--allow-research-only",
        "--output-root", str(a.output_root), "--task", trial.get("task", "excess_return_240d"), "--architecture", trial["architecture"],
        "--variant", trial["id"], "--cohort", "cn_equity_core", "--maximum-dates", str(trial.get("maximum_dates", 1500)), "--window", "20",
        "--batch-dates", "64", "--max-epochs", "48", "--hidden-size", str(trial["hidden"]),
        "--learning-rate", str(trial["lr"]), "--weight-decay", "0.0001", "--early-stop-patience", "6",
        "--seed", str(trial["seed"]),
        "--training-run-id", f"{a.output_root.name}-{trial['id']}"]
    if trial.get("evaluation_end_offset", 0):
        command += ["--evaluation-end-offset", str(trial["evaluation_end_offset"])]
    if trial.get("holdout_sessions"):
        command += ["--holdout-sessions", str(trial["holdout_sessions"])]
    if trial["warm"]:
        command += ["--init-checkpoint", str(a.init_checkpoint), "--warm-start-mode", "backbone", "--warmup-epochs", "5"]
    for prefix in trial.get("exclude", []):
        command += ["--exclude-feature-prefix", prefix]
    return command


def metric(report: Path) -> float:
    payload = read(report, {})
    try:
        key = "risk_rank_ic" if payload.get("task") == "future_max_drawdown_240d" else "rank_ic"
        return float(payload["result"]["holdout_metrics"][key])
    except (KeyError, TypeError, ValueError):
        return float("-inf")


def main() -> int:
    a = args(); a.output_root.mkdir(parents=True, exist_ok=True)
    status_path = a.output_root / "transfer-queue-status.json"
    status = read(status_path, {"schema_version": "return-transfer-queue-v1", "started_at": now(), "trials": []})
    status["status"] = "running"; status["resource_policy"] = {"gpu": "GPU0 only", "sequential_gpu": True, "gpu_memory_fraction": 0.90, "cpu_threads": recommended_threads(), "epoch_resume": True}
    for trial in trials():
        report = report_path(a.output_root, trial)
        prior = next((item for item in status["trials"] if item["id"] == trial["id"]), None)
        if report.is_file():
            item = {**trial, "status": "completed", "report": str(report), "holdout_rank_ic": metric(report), "finished_at": now()}
        else:
            item = {**trial, "status": "running", "started_at": now()}; status["trials"] = [x for x in status["trials"] if x["id"] != trial["id"]] + [item]; write(status_path, status)
            log = a.output_root / "logs" / f"{trial['id']}.log"; log.parent.mkdir(parents=True, exist_ok=True)
            code = 1
            for attempt in range(1, a.max_retries + 2):
                with log.open("a", encoding="utf-8") as out:
                    out.write(f"\n=== {now()} attempt {attempt} ===\n")
                    process = subprocess.Popen(command(a, trial), cwd=PROJECT, env=env(), stdout=out, stderr=subprocess.STDOUT)
                    monitor = ResourceMonitor(a.output_root / "monitoring" / f"{trial['id']}.jsonl", interval_seconds=a.monitor_interval, pid=process.pid)
                    monitor.start(); code = process.wait(); monitor.stop(); out.write(f"exit_code={code}\n")
                if code == 0: break
                time.sleep(min(60, attempt * 10))
            item.update({"status": "completed" if code == 0 else "failed", "exit_code": code, "attempts": attempt, "report": str(report), "holdout_rank_ic": metric(report) if report.is_file() else None, "finished_at": now()})
        status["trials"] = [x for x in status["trials"] if x["id"] != trial["id"]] + [item]
        status["updated_at"] = now(); write(status_path, status)
        if item["status"] == "failed": status["status"] = "paused_after_failure"; write(status_path, status); return int(item["exit_code"])
    complete = [item for item in status["trials"] if item["status"] == "completed" and item.get("task", "excess_return_240d") == "excess_return_240d"]
    winner = max(complete, key=lambda item: item["holdout_rank_ic"])
    status.update({"status": "completed", "finished_at": now(), "winner": winner})
    write(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
