#!/usr/bin/env python3
"""Time-boxed, GPU0-only long-horizon tuning with safe epoch-level resume."""
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


def _args():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("sample-manifest-file", "object-store", "data-root", "rebuild-index", "output-root", "init-checkpoint", "wait-status-file"):
        p.add_argument(f"--{name}", type=Path, required=True)
    p.add_argument("--hours", type=float, default=4.0)
    p.add_argument("--max-wait-minutes", type=float, default=90.0)
    p.add_argument("--minimum-free-gib", type=float, default=12.0)
    return p.parse_args()


def _now(): return datetime.now(timezone.utc).isoformat()


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _ready(path: Path) -> bool:
    try: return json.loads(path.read_text())["status"] == "completed"
    except (OSError, ValueError, KeyError): return False


def _trials():
    output = []
    for window in (20, 60):
        for lr in (0.00045, 0.0006, 0.0008, 0.0010):
            for seed in (42, 2026, 3407):
                output.append({"id": f"return-w{window}-lr{lr:g}-s{seed}", "task": "excess_return_240d", "arch": "stockmixer", "hidden": 128, "window": window, "lr": lr, "seed": seed, "warm": True})
    for lr in (0.00035, 0.0005, 0.0007, 0.0009):
        output.append({"id": f"risk-lr{lr:g}", "task": "future_max_drawdown_240d", "arch": "stockmixer", "hidden": 128, "window": 60, "lr": lr, "seed": 42, "warm": True})
    for seed in (42, 2026, 3407):
        output.append({"id": f"master-h256-s{seed}", "task": "excess_return_240d", "arch": "master", "hidden": 256, "window": 60, "lr": 0.0005, "seed": seed, "warm": False})
    return output


def _report(root, trial):
    return root / "cn/close_confirmed/cn_equity_core" / trial["task"] / "panel" / trial["arch"] / "variants" / trial["id"] / "sequence_evaluation.json"


def _command(a, trial):
    value = [sys.executable, str(PROJECT / "scripts/run_panel_research_training.py"),
        "--sample-manifest-file", str(a.sample_manifest_file), "--object-store", str(a.object_store),
        "--data-root", str(a.data_root), "--rebuild-index", str(a.rebuild_index), "--allow-research-only",
        "--output-root", str(a.output_root), "--task", trial["task"], "--architecture", trial["arch"], "--variant", trial["id"],
        "--cohort", "cn_equity_core", "--maximum-dates", "1500", "--window", str(trial["window"]), "--batch-dates", "64",
        "--max-epochs", "72", "--hidden-size", str(trial["hidden"]), "--learning-rate", str(trial["lr"]),
        "--weight-decay", "0.0001", "--early-stop-patience", "8", "--seed", str(trial["seed"]),
        "--training-run-id", f"{a.output_root.name}-{trial['id']}"]
    if trial["warm"]:
        value += ["--init-checkpoint", str(a.init_checkpoint), "--warm-start-mode", "backbone", "--warmup-epochs", "6"]
    return value


def _env():
    n = recommended_threads(); env = os.environ.copy()
    env.update({"PYTHONPATH": str(PROJECT / "src"), "CUDA_VISIBLE_DEVICES": "0", "INVESTMENT_RESEARCH_TORCH_DEVICE": "cuda", "INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION": "0.90", "OMP_NUM_THREADS": str(n), "MKL_NUM_THREADS": str(n), "OPENBLAS_NUM_THREADS": str(n), "NUMEXPR_NUM_THREADS": str(n), "OMP_DYNAMIC": "FALSE", "PYTHONUNBUFFERED": "1"})
    return env


def main():
    a = _args(); a.output_root.mkdir(parents=True, exist_ok=True); status_path = a.output_root / "timebox-status.json"
    status = {"schema_version": "timeboxed-tuning-v1", "status": "waiting_for_prior_queue", "started_at": _now(), "budget_hours": a.hours, "trials": [], "policy": {"gpu": "GPU0 only", "epoch_resume": True, "disk_minimum_gib": a.minimum_free_gib, "no_sequence_cache": True, "sequential": True}}
    _write(status_path, status)
    wait_deadline = time.monotonic() + a.max_wait_minutes * 60
    while not _ready(a.wait_status_file):
        if time.monotonic() >= wait_deadline:
            status.update({"status": "blocked_prior_queue_timeout", "finished_at": _now()}); _write(status_path, status); return
        _write(status_path, status)
        time.sleep(60)
    deadline = time.monotonic() + a.hours * 3600; status["status"] = "running"; status["training_started_at"] = _now()
    for trial in _trials():
        report = _report(a.output_root, trial)
        if report.is_file():
            status["trials"].append({**trial, "status": "completed", "resumed": True, "report": str(report)}); _write(status_path, status); continue
        if time.monotonic() >= deadline or shutil.disk_usage(a.output_root).free < int(a.minimum_free_gib * 1024**3): break
        item = {**trial, "status": "running", "started_at": _now()}; status["trials"].append(item); _write(status_path, status)
        log = a.output_root / "logs" / f"{trial['id']}.log"; log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as out:
            proc = subprocess.Popen(_command(a, trial), cwd=PROJECT, env=_env(), stdout=out, stderr=subprocess.STDOUT)
            monitor = ResourceMonitor(a.output_root / "monitoring" / f"{trial['id']}.jsonl", interval_seconds=5, pid=proc.pid); monitor.start()
            while proc.poll() is None and time.monotonic() < deadline: time.sleep(10)
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=60)
            monitor.stop(); item.update({"status": "completed" if proc.returncode == 0 else "checkpointed", "exit_code": proc.returncode, "finished_at": _now(), "report": str(report)})
        _write(status_path, status)
    status.update({"status": "timebox_finished", "finished_at": _now()}); _write(status_path, status)


if __name__ == "__main__": main()
