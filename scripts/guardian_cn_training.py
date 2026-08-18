#!/usr/bin/env python3
"""Guardian for the CN research retrain.

Goal: keep the retrain running until a deadline (default 2026-08-14T09:00 CST),
and if it dies, resume (断点续跑) instead of restarting from zero.

Why resume works: the training scripts were patched to skip any task whose final
artifact already exists (run_free_research_training.py / run_sequence_research_training.py),
and run_cn_research_demo.py accepts a pinned --run-id so every relaunch targets the
SAME run directory. So a relaunch only (re)trains what is not yet done.

Liveness is decided WITHOUT relying on `ps` (which may be blocked in some
environments): we look at the newest artifact mtime under the run dir and the run
report, plus an optional pgrep check when ps is available, plus a relaunch lock to
avoid double-launching across frequent automation fires.

Self-contained: the scheduled automation just calls this script.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")
ARCHS = ("patchtst", "tcn", "itransformer", "deep_mlp")


def _log(msg: str, guardian_log: Path | None) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {msg}"
    print(line, flush=True)
    if guardian_log:
        guardian_log.parent.mkdir(parents=True, exist_ok=True)
        with open(guardian_log, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _newest_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    best = path.stat().st_mtime
    for p in path.rglob("*"):
        if p.is_file():
            try:
                m = p.stat().st_mtime
                if m > best:
                    best = m
            except OSError:
                pass
    return best


def _is_complete(run_dir: Path) -> bool:
    if not run_dir.exists():
        return False
    for t in TASKS:
        if not (run_dir / "cn" / "close_confirmed" / "cn_equity_core" / t / "evaluation.json").is_file():
            return False
    for t in TASKS:
        for a in ARCHS:
            if not (run_dir / "cn" / "close_confirmed" / "cn_equity_core" / t / "sequence" / a / "sequence_evaluation.json").is_file():
                return False
    return True


def _verify_constraints(report: Path, guardian_log: Path | None) -> None:
    """Read-only supervision check: confirm published artifacts keep the
    mandated constraints (data_tier=research_pit, status=research_only,
    deployment_ready=false) at BOTH the top level and every nested entry.
    Never mutates anything; only logs violations.
    """
    if not report.exists():
        _log("CONSTRAINT-CHECK: report not yet generated, skip.", guardian_log)
        return
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        _log(f"CONSTRAINT-CHECK: cannot parse {report}: {e}", guardian_log)
        return
    violations: list[str] = []
    top = {
        "data_tier": data.get("data_tier"),
        "status": data.get("status"),
        "deployment_ready": data.get("deployment_ready"),
    }
    if top["data_tier"] != "research_pit":
        violations.append(f"top.data_tier={top['data_tier']!r} (want research_pit)")
    if top["status"] != "research_only":
        violations.append(f"top.status={top['status']!r} (want research_only)")
    if top["deployment_ready"] is not False:
        violations.append(f"top.deployment_ready={top['deployment_ready']!r} (want false)")

    nested_status_bad = 0
    nested_status_examples: list[str] = []
    nested_deploy = 0
    nested_tier_bad = 0

    def _walk(o: object) -> None:
        nonlocal nested_status_bad, nested_deploy, nested_tier_bad, nested_status_examples
        if isinstance(o, dict):
            if "status" in o and o["status"] != "research_only":
                scope = o.get("scope_id") or o.get("cohort") or o.get("task") or "?"
                if len(nested_status_examples) < 5:
                    nested_status_examples.append(f"{scope}={o['status']!r}")
                nested_status_bad += 1
            if o.get("deployment_ready") is True:
                nested_deploy += 1
            if o.get("data_tier") not in (None, "research_pit"):
                nested_tier_bad += 1
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(data)
    if nested_status_bad:
        violations.append(
            f"nested status!=research_only: {nested_status_bad} entries "
            f"(e.g. {', '.join(nested_status_examples)})"
        )
    if nested_deploy:
        violations.append(f"nested deployment_ready=true: {nested_deploy} entries")
    if nested_tier_bad:
        violations.append(f"nested data_tier!=research_pit: {nested_tier_bad} entries")
    if violations:
        _log("CONSTRAINT VIOLATION: " + " | ".join(violations), guardian_log)
    else:
        _log("CONSTRAINTS OK: data_tier=research_pit, status=research_only, deployment_ready=false (top + nested)", guardian_log)


def _ps_has_training() -> bool | None:
    """True/False if determinable, None if ps/pgrep is unavailable.

    Matches any of the three training entrypoints (orchestrator + tabular/deep
    trainers) so we don't prematurely relaunch while a child is still working.
    """
    patterns = (
        "run_cn_research_demo.py",
        "run_free_research_training.py",
        "run_sequence_research_training.py",
    )
    try:
        for pat in patterns:
            out = subprocess.run(
                ["pgrep", "-f", pat],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                return True
        return False
    except (OSError, subprocess.TimeoutExpired):
        return None


def _relaunch(args: argparse.Namespace, run_dir: Path, guardian_log: Path | None) -> None:
    # Build the shell command string (nohup + redirect + &) and run via shell.
    shell = (
        f"cd {PROJECT} && nohup {args.python} scripts/run_cn_research_demo.py "
        f"--profile full --skip-collection "
        f"--rebuild-index {args.rebuild_index} "
        f"--run-id {args.run_id} "
        f"--report {args.report} "
        f"> {args.guardian_log_dir / f'retrain-{args.run_id}-guardian.log'} 2>&1 &"
    )
    _log(f"RELAUNCH: {shell}", guardian_log)
    if args.dry_run:
        _log("DRY-RUN: not executing relaunch", guardian_log)
        return
    # Write relaunch lock so subsequent fires within the window don't double-launch.
    lock = args.guardian_log_dir / "guardian_relaunch.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    subprocess.Popen(shell, shell=True, cwd=str(PROJECT))
    _log("RELAUNCH: issued", guardian_log)


def main() -> int:
    ap = argparse.ArgumentParser(description="Guardian: keep CN retrain alive until deadline, resume if dead.")
    ap.add_argument("--run-id", required=True, help="Pinned run_id (must match the live run's directory).")
    ap.add_argument("--report", type=Path, required=True, help="--report path used by the training run.")
    ap.add_argument("--rebuild-index", type=Path, required=True, help="Rebuild index consumed by the training run.")
    ap.add_argument("--python", default=sys.executable, help="Python interpreter to launch training.")
    ap.add_argument("--minimum-training-sessions", type=int, default=900)
    ap.add_argument("--guardian-log-dir", type=Path, default=PROJECT / "artifacts" / "cn_research_demo")
    ap.add_argument("--stale-minutes", type=int, default=120,
                    help="If newest artifact is older than this AND not complete -> considered dead.")
    ap.add_argument("--relaunch-lock-minutes", type=int, default=90,
                    help="Do not relaunch if a relaunch happened within this window (anti double-launch).")
    ap.add_argument("--deadline", default="2026-08-14T09:00:00+08:00",
                    help="ISO8601 deadline; after this the guardian stops relaunching.")
    ap.add_argument("--dry-run", action="store_true", help="Decide and log, but never relaunch.")
    args = ap.parse_args()

    guardian_log = args.guardian_log_dir / f"guardian-{args.run_id}.log"
    run_dir = PROJECT / "artifacts" / "free_research_models" / "runs" / args.run_id

    now = datetime.now(timezone.utc)
    _log(f"GUARDIAN tick run_id={args.run_id} now={now.isoformat()}", guardian_log)
    _verify_constraints(args.report, guardian_log)

    # 1) Past deadline -> stop.
    try:
        dl = datetime.fromisoformat(args.deadline)
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=timezone.utc)
        if now > dl:
            _log("PAST DEADLINE: stop guarding (no relaunch).", guardian_log)
            return 0
    except ValueError:
        _log(f"WARN: could not parse deadline {args.deadline}", guardian_log)

    # 2) Already complete -> stop.
    if _is_complete(run_dir):
        _log("COMPLETE: all 4 tabular + 16 deep artifacts present. Stop guarding.", guardian_log)
        return 0

    # 3) Liveness check.
    ps_running = _ps_has_training()
    newest = _newest_mtime(run_dir)
    report_newest = _newest_mtime(args.report.parent) if args.report.exists() else None
    newest_all = max([x for x in (newest, report_newest) if x is not None], default=None)
    age_min = (time.time() - newest_all) / 60.0 if newest_all is not None else float("inf")

    alive = False
    if ps_running is True:
        alive = True
        _log("ALIVE: pgrep found run_cn_research_demo.py process.", guardian_log)
    elif ps_running is None:
        # ps unavailable: fall back to mtime
        if newest_all is not None and age_min < args.stale_minutes:
            alive = True
            _log(f"ALIVE: newest artifact age {age_min:.1f}min < stale {args.stale_minutes}min (ps unavailable).", guardian_log)
        else:
            _log(f"DEAD(or-stale): newest artifact age {age_min:.1f}min >= stale {args.stale_minutes}min (ps unavailable).", guardian_log)
    else:
        _log("DEAD: pgrep found no run_cn_research_demo.py process.", guardian_log)

    if alive:
        _log("ALIVE: no action.", guardian_log)
        return 0

    # 4) Dead -> check relaunch lock to avoid double-launch.
    lock = args.guardian_log_dir / "guardian_relaunch.lock"
    if lock.is_file():
        try:
            lt = datetime.fromisoformat(lock.read_text(encoding="utf-8").strip())
            if (now - lt).total_seconds() < args.relaunch_lock_minutes * 60:
                _log(f"SUPPRESSED: relaunch lock fresh (<{args.relaunch_lock_minutes}min). Assume just-launched process still starting.", guardian_log)
                return 0
        except ValueError:
            pass

    # 5) Relaunch (resume via pinned run-id + skip-done logic in trainers).
    _relaunch(args, run_dir, guardian_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
