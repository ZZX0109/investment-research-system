#!/usr/bin/env python3
"""Continue the CN research backfill after the staged financial job.

The financial ratio writer and its supervisor deliberately run alone because
they write the SQLite catalog.  This supervisor waits for that process to
finish, then executes the remaining resumable research-only collectors in a
fixed order.  It never activates a PIT snapshot and it records non-zero
collector exits as partial rather than hiding them.
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


def _ps_rows() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-ax", "-o", "pid=,command="],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        check=False,
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


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _append_log(path: Path, title: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{datetime.now(timezone.utc).isoformat()}] {title}\n{value}\n")


def _run(command: list[str], log: Path) -> int:
    completed = subprocess.run(
        command,
        cwd=PROJECT,
        text=True,
        capture_output=True,
        check=False,
    )
    _append_log(
        log,
        "COMMAND " + " ".join(command),
        completed.stdout[-16000:] + "\n" + completed.stderr[-16000:],
    )
    print(
        json.dumps(
            {"command": command[1] if len(command) > 1 else command[0], "return_code": completed.returncode},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return completed.returncode


def _ratio_is_complete() -> bool:
    progress = _json(PROJECT / "artifacts/cn_financial_ratios_akshare/progress.json")
    version = progress.get("metric_contract_version")
    states = progress.get("symbols") if isinstance(progress.get("symbols"), dict) else {}
    complete = sum(
        1
        for state in states.values()
        if isinstance(state, dict)
        and state.get("status") == "complete"
        and state.get("metric_contract_version") == version
    )
    failed = sum(1 for state in states.values() if isinstance(state, dict) and state.get("status") == "failed")
    target = int(progress.get("target_equity_count", 0) or 0)
    return target > 0 and complete >= target and failed == 0


def _qfq_remaining() -> int:
    # The project audit currently derives this from the append-only catalog;
    # use the same authoritative query here without modifying the database.
    import sqlite3

    database = PROJECT / "var/cn-research/catalog.db"
    if not database.exists():
        return 0
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            """
            SELECT DISTINCT json_extract(payload_json, '$.symbol')
            FROM raw_data_batches
            WHERE data_tier='research_pit' AND dataset='daily_bars_raw'
            EXCEPT
            SELECT DISTINCT json_extract(payload_json, '$.symbol')
            FROM raw_data_batches
            WHERE data_tier='research_pit' AND dataset='daily_bars_qfq'
            """
        )
        return sum(1 for row in rows if row[0])
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--skip-lifecycle", action="store_true")
    parser.add_argument("--skip-corporate-actions", action="store_true")
    parser.add_argument("--log", type=Path, default=PROJECT / "artifacts/cn_research_backfill_supervisor.log")
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        raise SystemExit("poll-seconds must be positive")

    initial = _pid_command(args.wait_pid)
    if initial is None or "finish_cn_financial_backfill.py" not in initial:
        raise SystemExit("wait_pid_is_not_the_financial_backfill_supervisor")
    _append_log(args.log, "START", f"waiting for pid={args.wait_pid}: {initial}")
    while _pid_command(args.wait_pid) is not None:
        print(json.dumps({"waiting_for_financial_supervisor": args.wait_pid}, ensure_ascii=False), flush=True)
        time.sleep(args.poll_seconds)

    # A failed audit is expected while the broader project remains incomplete;
    # only an incomplete ratio contract prevents downstream ingestion.
    if not _ratio_is_complete():
        report = {
            "schema_version": "cn-research-backfill-supervisor-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "blocked",
            "reason": "financial_ratio_contract_incomplete",
        }
        output = PROJECT / "artifacts/cn_research_backfill_supervisor/latest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 2

    return_codes: list[int] = []
    stages: list[dict[str, object]] = []

    remaining_qfq = _qfq_remaining()
    if remaining_qfq:
        command = [
            sys.executable,
            "scripts/backfill_bse_legacy_qfq.py",
            "--delay-seconds",
            "1.0",
            "--timeout-seconds",
            "30",
        ]
        code = _run(command, args.log)
        return_codes.append(code)
        stages.append({"name": "bse_legacy_qfq", "before": remaining_qfq, "return_code": code})
    else:
        stages.append({"name": "bse_legacy_qfq", "before": 0, "return_code": 0, "skipped": True})

    if not args.skip_corporate_actions:
        action_report = _json(PROJECT / "artifacts/cn_corporate_actions_detailed/latest.json")
        target = int(action_report.get("target_equity_count", 0) or 0)
        completed = int(action_report.get("completed_equity_count", 0) or 0)
        if target == 0 or completed < target:
            command = [
                sys.executable,
                "scripts/backfill_cn_corporate_actions_detailed.py",
                "--all-current-universe",
                "--workers",
                "4",
            ]
            code = _run(command, args.log)
            return_codes.append(code)
            stages.append({"name": "corporate_actions", "before": completed, "target": target, "return_code": code})
        else:
            stages.append({"name": "corporate_actions", "before": completed, "target": target, "return_code": 0, "skipped": True})

    # Refresh the official NBS article archive after the financial writer has
    # released the catalog lock.  The listing date is not treated as a
    # publication timestamp; the collector only admits an explicit article
    # timestamp and leaves the remainder as an evidence gap.
    command = [
        sys.executable,
        "scripts/fetch_cn_macro_actual_release_nbs.py",
        "--page-count",
        "200",
        "--workers",
        "6",
    ]
    code = _run(command, args.log)
    return_codes.append(code)
    stages.append({"name": "macro_actual_release", "return_code": code})

    if not args.skip_lifecycle:
        command = [
            sys.executable,
            "scripts/fetch_cn_security_lifecycle_akshare.py",
            "--all-current-universe",
            "--workers",
            "4",
        ]
        code = _run(command, args.log)
        return_codes.append(code)
        stages.append({"name": "security_lifecycle", "return_code": code})

    for command in (
        [sys.executable, "scripts/run_cn_data_completion.py", "--project-root", str(PROJECT)],
        [sys.executable, "scripts/audit_project_completion.py", "--project-root", str(PROJECT)],
    ):
        code = _run(command, args.log)
        return_codes.append(code)
        stages.append({"name": command[1], "return_code": code})

    final = {
        "schema_version": "cn-research-backfill-supervisor-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if all(code == 0 for code in return_codes) else "partial",
        "qfq_remaining_after": _qfq_remaining(),
        "financial_ratio_contract_complete": _ratio_is_complete(),
        "stages": stages,
        "return_codes": return_codes,
        "log": str(args.log),
    }
    output = PROJECT / "artifacts/cn_research_backfill_supervisor/latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final, ensure_ascii=False), flush=True)
    return 0 if final["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
