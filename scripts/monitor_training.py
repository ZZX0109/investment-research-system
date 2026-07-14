#!/usr/bin/env python3
"""Inspect or watch the latest training job status."""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RUNS = PROJECT / "runs"
OUTPUT = PROJECT / "output"
DEFAULT_STATUS = RUNS / "training-status.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor AI Investment Research Console training status.")
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--tail", type=int, default=30, help="Number of log lines to show.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    return parser.parse_args()


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def summarize_artifacts() -> dict:
    summary: dict = {"artifacts": {}}
    for name in ["labels.csv", "results.json", "evaluation.json", "model_cards.json", "invest_agent_models.json"]:
        path = OUTPUT / name
        if path.exists():
            stat = path.stat()
            summary["artifacts"][name] = {
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }

    labels = OUTPUT / "labels.csv"
    if labels.exists():
        rows = 0
        symbols: set[str] = set()
        with labels.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows += 1
                if row.get("symbol"):
                    symbols.add(row["symbol"])
        summary["labels"] = {"rows": rows, "symbols": len(symbols)}

    results = OUTPUT / "results.json"
    if results.exists():
        data = json.loads(results.read_text(encoding="utf-8"))
        models = data.get("models", [])
        summary["results"] = {
            "generated_at": data.get("generated_at"),
            "data_source": data.get("data_source"),
            "training_profile": data.get("training_profile"),
            "sample_count": data.get("sample_count"),
            "symbol_count": data.get("symbol_count"),
            "samples_with_events": data.get("samples_with_events"),
            "models": len(models),
            "approved_models": [
                model.get("trainer_name")
                for model in models
                if model.get("eligible_for_approval")
            ],
        }
    return summary


def tail_lines(path: Path, count: int) -> list[str]:
    if count <= 0 or not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-count:]


def read_snapshot(status_path: Path, tail: int) -> dict:
    status = {}
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        status = {"state": "missing_status", "status_path": str(status_path)}

    active_pid = None
    current_step = status.get("current_step")
    for step in reversed(status.get("steps", [])):
        if step.get("state") == "running":
            active_pid = step.get("pid")
            break
    status["job_pid_alive"] = pid_alive(status.get("pid"))
    status["step_pid_alive"] = pid_alive(active_pid)
    status["active_step_pid"] = active_pid
    status["current_step"] = current_step
    status["artifact_summary"] = summarize_artifacts()

    log_path = Path(status.get("log_path", "")) if status.get("log_path") else None
    status["log_tail"] = tail_lines(log_path, tail) if log_path else []
    return status


def print_human(snapshot: dict) -> None:
    print(f"state: {snapshot.get('state')}  current_step: {snapshot.get('current_step')}")
    print(f"run_id: {snapshot.get('run_id')}  profile: {snapshot.get('profile')}  data_source: {snapshot.get('data_source')}")
    print(f"job_pid_alive: {snapshot.get('job_pid_alive')}  step_pid_alive: {snapshot.get('step_pid_alive')}")
    if snapshot.get("error"):
        print(f"error: {snapshot['error']}")

    artifact_summary = snapshot.get("artifact_summary", {})
    labels = artifact_summary.get("labels")
    results = artifact_summary.get("results")
    if labels:
        print(f"labels: rows={labels.get('rows')} symbols={labels.get('symbols')}")
    if results:
        print(
            "results: "
            f"data_source={results.get('data_source')} "
            f"profile={results.get('training_profile')} "
            f"samples={results.get('sample_count')} "
            f"symbols={results.get('symbol_count')} "
            f"event_samples={results.get('samples_with_events')} "
            f"approved={results.get('approved_models')}"
        )

    print("steps:")
    for step in snapshot.get("steps", []):
        print(
            f"  - {step.get('name')}: {step.get('state')} "
            f"returncode={step.get('returncode')} pid={step.get('pid')}"
        )

    if snapshot.get("log_tail"):
        print("log tail:")
        for line in snapshot["log_tail"]:
            print(f"  {line}")


def main() -> int:
    args = parse_args()
    while True:
        snapshot = read_snapshot(args.status, args.tail)
        if args.json:
            print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        else:
            print_human(snapshot)
        if not args.watch:
            return 0
        time.sleep(args.interval)
        print("\n" + "=" * 80)


if __name__ == "__main__":
    raise SystemExit(main())
