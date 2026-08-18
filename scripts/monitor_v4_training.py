#!/usr/bin/env python3
"""Hourly health monitor for the V4 A-share research retraining run.

Read-only watchdog.  It never kills or restarts anything; it only records the
state of the latest run so an unattended crash is noticed.  Designed to be run
once per hour by an external scheduler (see the hourly automation).

Outputs:
  <run_dir>/training_watch.json            (latest snapshot)
  <run_dir>/training_watch_history.jsonl   (append-only log)
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RUNS_ROOT = PROJECT / "artifacts" / "free_research_models" / "runs"
TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")
DEEP_ARCH = ("patchtst", "tcn", "itransformer", "deep_mlp")
COHORT = "cn/close_confirmed/cn_equity_core"

ERROR_PATTERNS = [
    "Traceback",
    "IndexError",
    "RuntimeError",
    "ValueError",
    "NaN",
    "Inf",
    "overflow",
    "division by zero",
    "CUDA out of memory",
    "sequence_manifest_missing",
]

STALE_MINUTES = 90
LOCK_PATH = PROJECT / "artifacts" / "free_research_models" / "monitor.lock"


def _latest_run_dir() -> Path | None:
    if not RUNS_ROOT.exists():
        return None
    dirs = [d for d in RUNS_ROOT.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def _pids_for(pattern: str) -> list[int]:
    try:
        out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    except FileNotFoundError:
        return []
    pids = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _scan_errors(run_dir: Path) -> list[str]:
    hits: list[str] = []
    for log in run_dir.rglob("*.log"):
        try:
            text = log.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in ERROR_PATTERNS:
            if pat in text:
                hits.append(f"{log.name}:{pat}")
    # inspect the final top-level report stderr tails if present
    for name in ("cn-research-demo-20260812T050519Z.json", "latest-v4-rerun.json"):
        report = PROJECT / "artifacts" / "cn_research_demo" / name
        if report.exists():
            try:
                data = json.loads(report.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, ValueError):
                continue
            stages = data.get("stages", []) if isinstance(data, dict) else []
            for idx, stage in enumerate(stages):
                tail = (stage.get("stderr_tail") or "") if isinstance(stage, dict) else ""
                if "Traceback" in tail or "sequence_manifest_missing" in tail:
                    hits.append(f"{name}:stage[{idx}]:crash")
    # dedupe by the noisy report prefix so the list stays actionable
    seen = set()
    unique = []
    for h in hits:
        key = h.split(":")[0]
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)
    return unique[:20]


def _task_state(run_dir: Path, task: str) -> str:
    base = run_dir / COHORT / task
    if not base.exists():
        return "missing"
    roster = (base / "research_model_roster.json").exists()
    eval_ok = (base / "evaluation.json").exists()
    manifest = (base / "task_manifest.json").exists()
    if roster and eval_ok and manifest:
        return "completed"
    if (base / "research_model.joblib").exists() or eval_ok:
        return "running"
    return "missing"


def _deep_state(run_dir: Path, task: str) -> dict[str, str]:
    out: dict[str, str] = {}
    base = run_dir / COHORT / task / "sequence"
    for arch in DEEP_ARCH:
        m = base / arch / "sequence_manifest.json"
        if m.exists():
            try:
                payload = json.loads(m.read_text(encoding="utf-8", errors="ignore"))
                out[arch] = payload.get("research_status", "unknown") or "unknown"
            except (OSError, ValueError):
                out[arch] = "unknown"
        else:
            out[arch] = "missing"
    return out


def monitor(run_dir: Path) -> dict:
    demo_pids = _pids_for("run_cn_research_demo.py")
    tabular_pids = _pids_for("run_free_research_training.py")
    seq_pids = _pids_for("run_sequence_research_training.py")
    active_pids = sorted(set(demo_pids + tabular_pids + seq_pids))
    run_id = run_dir.name

    task_states = {t: _task_state(run_dir, t) for t in TASKS}
    completed = [t for t, s in task_states.items() if s == "completed"]
    running = [t for t, s in task_states.items() if s == "running"]
    missing = [t for t, s in task_states.items() if s == "missing"]

    deep: dict[str, dict[str, str]] = {}
    for t in TASKS:
        deep[t] = _deep_state(run_dir, t)

    latest_mtime = run_dir.stat().st_mtime
    for root, _dirs, files in os.walk(run_dir):
        for f in files:
            try:
                m = os.path.getmtime(os.path.join(root, f))
            except OSError:
                continue
            if m > latest_mtime:
                latest_mtime = m
    latest_dt = datetime.fromtimestamp(latest_mtime, tz=timezone.utc)
    age_min = (datetime.now(tz=timezone.utc) - latest_dt).total_seconds() / 60.0

    errors = _scan_errors(run_dir)

    deep_total = sum(len(models) for models in deep.values())
    deep_trained = sum(
        1 for models in deep.values() for state in models.values() if state == "trained"
    )
    deep_not_trained = deep_total - deep_trained

    if demo_pids or tabular_pids or seq_pids:
        if age_min > STALE_MINUTES and not completed:
            overall = "stale"
        else:
            overall = "running"
        recommendation = "continue"
    elif completed and not missing:
        # Tabular tasks finished, but the run is only truly healthy when the
        # deep-model cohort trained as well and no crash was recorded.
        if deep_not_trained or errors:
            overall = "completed_degraded"
            recommendation = "retrain_required"
        else:
            overall = "completed"
            recommendation = "verify"
    elif not active_pids and (missing or running):
        overall = "failed"
        recommendation = "restart_required"
    else:
        overall = "partial"
        recommendation = "inspect"

    if overall == "completed_degraded":
        summary = (
            f"run {run_id}: tabular tasks finished, but {deep_not_trained}/{deep_total} "
            f"deep-model slots are not trained"
            + (f" and {len(errors)} error marker(s) found" if errors else "")
            + " -- NOT a healthy run, retrain required"
        )
    elif overall == "completed":
        summary = f"run {run_id}: all tasks and {deep_trained}/{deep_total} deep models completed"
    elif overall == "running":
        summary = f"run {run_id}: training in progress ({len(completed)}/{len(TASKS)} tasks done)"
    else:
        summary = f"run {run_id}: status={overall}"

    return {
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": run_id,
        "overall_status": overall,
        "summary": summary,
        "active_pids": active_pids,
        "completed_tasks": completed,
        "running_tasks": running,
        "failed_tasks": [],
        "missing_tasks": missing,
        "deep_models_trained": deep_trained,
        "deep_models_total": deep_total,
        "deep_model_state": deep,
        "latest_artifact_mtime": latest_dt.isoformat(),
        "artifact_age_minutes": round(age_min, 1),
        "last_errors": errors,
        "recommendation": recommendation,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Hourly V4 training monitor")
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--runs-root", type=Path, default=RUNS_ROOT)
    args = ap.parse_args()

    run_dir = args.run_dir or _latest_run_dir()
    if run_dir is None:
        print(json.dumps({"overall_status": "no_run", "recommendation": "start_training"}, indent=2))
        return 0

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print(json.dumps({"overall_status": "locked", "recommendation": "already_running"}, indent=2))
            return 0
        snapshot = monitor(run_dir)
        (run_dir / "training_watch.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        history = run_dir / "training_watch_history.jsonl"
        with history.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
