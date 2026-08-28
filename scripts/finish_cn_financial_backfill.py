#!/usr/bin/env python3
"""Safely finish the staged CN financial backfill after the current writer exits.

This supervisor is deliberately conservative: it waits for the exact
all-universe ratio process, retries only the resumable ratio failures, then
imports the four already-audited statement families and refreshes the
non-activating reconciliation/audit artifacts.  It never creates an active
snapshot and stops before import if the ratio contract is still incomplete.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


PROJECT = Path(__file__).resolve().parents[1]
RATIO_SCRIPT = "fetch_cn_financial_ratios_akshare.py"


def _ps_rows() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-ax", "-o", "pid=,command="],
        cwd=PROJECT, text=True, capture_output=True, check=False,
    )
    rows: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            pid_text, command = value.split(None, 1)
            rows.append((int(pid_text), command))
        except (TypeError, ValueError):
            continue
    return rows


def _pid_command(pid: int) -> str | None:
    return next((command for value, command in _ps_rows() if value == pid), None)


def _progress() -> dict:
    path = PROJECT / "artifacts/cn_financial_ratios_akshare/progress.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    version = payload.get("metric_contract_version")
    states = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else {}
    complete = sum(
        1 for state in states.values()
        if isinstance(state, dict)
        and state.get("status") == "complete"
        and state.get("metric_contract_version") == version
    )
    failed = sum(
        1
        for state in states.values()
        if isinstance(state, dict)
        and state.get("status") not in {"complete"}
    )
    target = int(payload.get("target_equity_count", 0) or 0)
    return {"complete": complete, "failed": failed, "target": target, "version": version}


def _append_log(path: Path, title: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{datetime.now(timezone.utc).isoformat()}] {title}\n{value}\n")


def _run(command: list[str], log: Path) -> int:
    completed = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, check=False)
    _append_log(log, "COMMAND " + " ".join(command), completed.stdout[-12000:] + "\n" + completed.stderr[-12000:])
    print(json.dumps({"command": command[1] if len(command) > 1 else command[0], "return_code": completed.returncode}, ensure_ascii=False), flush=True)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--ratio-retry-passes", type=int, default=3)
    parser.add_argument(
        "--ratio-retry-delay-seconds",
        type=float,
        default=60.0,
        help="cooldown between provider-throttle retry passes",
    )
    parser.add_argument("--log", type=Path, default=PROJECT / "artifacts/cn_financial_backfill_supervisor.log")
    args = parser.parse_args()
    if args.poll_seconds <= 0 or args.ratio_retry_passes <= 0 or args.ratio_retry_delay_seconds < 0:
        raise SystemExit("poll-seconds and ratio-retry-passes must be positive and retry delay cannot be negative")

    initial = _pid_command(args.wait_pid)
    if initial is None or RATIO_SCRIPT not in initial or "--all-current-universe" not in initial:
        raise SystemExit("wait_pid_is_not_the_expected_all_universe_ratio_writer")
    _append_log(args.log, "START", f"waiting for pid={args.wait_pid}: {initial}")
    while True:
        command = _pid_command(args.wait_pid)
        if command is None:
            break
        if RATIO_SCRIPT not in command or "--all-current-universe" not in command:
            raise SystemExit("wait_pid_command_changed_before_completion")
        state = _progress()
        print(json.dumps({"waiting_for_pid": args.wait_pid, **state}, ensure_ascii=False), flush=True)
        time.sleep(args.poll_seconds)

    # Do not race a replacement writer that may have been started manually.
    active_ratio = [pid for pid, command in _ps_rows() if pid != args.wait_pid and RATIO_SCRIPT in command]
    if active_ratio:
        raise SystemExit(f"another_ratio_writer_is_active:{active_ratio}")

    ratio_command = [
        sys.executable, "scripts/fetch_cn_financial_ratios_akshare.py",
        "--all-current-universe", "--workers", "1", "--request-interval-seconds", "1.0",
    ]
    for attempt in range(1, args.ratio_retry_passes + 1):
        _run(ratio_command, args.log)
        state = _progress()
        print(json.dumps({"ratio_retry_pass": attempt, **state}, ensure_ascii=False), flush=True)
        if state.get("target", 0) > 0 and state.get("complete", 0) >= state["target"] and state.get("failed", 0) == 0:
            break
        if attempt < args.ratio_retry_passes and args.ratio_retry_delay_seconds:
            time.sleep(args.ratio_retry_delay_seconds)
    state = _progress()
    if state.get("target", 0) <= 0 or state.get("complete", 0) < state["target"] or state.get("failed", 0):
        _append_log(args.log, "BLOCKED", json.dumps(state, ensure_ascii=False))
        print(json.dumps({"status": "blocked", "reason": "ratio_backfill_incomplete", **state}, ensure_ascii=False), flush=True)
        return 2

    commands = [
        [sys.executable, "scripts/import_cn_financial_eastmoney_landing.py", "--report-family", "all"],
        [sys.executable, "scripts/run_cn_financial_pit_reconciliation.py"],
        [sys.executable, "scripts/run_cn_data_completion.py", "--project-root", str(PROJECT)],
        [sys.executable, "scripts/audit_project_completion.py", "--project-root", str(PROJECT)],
    ]
    return_codes = [_run(command, args.log) for command in commands]
    final_state = {
        "schema_version": "cn-financial-backfill-supervisor-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if all(code == 0 for code in return_codes) else "partial",
        "ratio_progress": _progress(),
        "return_codes": return_codes,
        "log": str(args.log),
    }
    output = PROJECT / "artifacts/cn_financial_backfill_supervisor/latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(final_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final_state, ensure_ascii=False), flush=True)
    return 0 if final_state["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
