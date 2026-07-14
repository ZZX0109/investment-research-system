#!/usr/bin/env python3
"""Run a reproducible training job and persist status for later inspection."""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RUNS = PROJECT / "runs"
OUTPUT = PROJECT / "output"
DEFAULT_STATUS = RUNS / "training-status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AI Investment Research Console training as a resumable job.")
    parser.add_argument("--data-source", choices=("synthetic", "real", "auto"), default="real")
    parser.add_argument("--profile", choices=("quick", "full"), default="quick")
    parser.add_argument("--resume", action="store_true", help="Resume from the existing status file and skip reusable successful steps.")
    parser.add_argument(
        "--force-step",
        action="append",
        choices=("fetch_real_data", "fetch_real_events", "retraining", "audits"),
        default=[],
        help="Re-run a step even when --resume finds a reusable successful result.",
    )
    parser.add_argument("--refresh-real-data", action="store_true", help="Fetch real OHLCV bundles before training.")
    parser.add_argument("--refresh-real-events", action="store_true", help="Fetch earnings/news events before training.")
    parser.add_argument("--skip-audits", action="store_true", help="Skip post-training audit script.")
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--log", type=Path, default=None)
    return parser.parse_args()


def write_status(path: Path, status: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status["updated_at"] = utc_now()
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")


def sync_audit_training_status(status: dict) -> None:
    for audit_path in (AUDITS / "data_coverage.json", AUDITS / "audit_data.json"):
        if not audit_path.exists():
            continue
        try:
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        payload["training_status"] = status
        global_summary = payload.setdefault("global_summary", {})
        global_summary["training_status"] = status
        audit_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_status(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def append_skipped_step(*, status: dict, status_path: Path, name: str, command: list[str], detail: str) -> None:
    status.setdefault("steps", []).append(
        {
            "name": name,
            "command": command,
            "state": "skipped",
            "started_at": utc_now(),
            "ended_at": utc_now(),
            "returncode": 0,
            "detail": detail,
        }
    )
    status["current_step"] = None
    write_status(status_path, status)


def last_matching_step(status: dict, *, name: str, command: list[str]) -> dict | None:
    for step in reversed(status.get("steps", [])):
        if step.get("name") == name and step.get("command") == command:
            return step
    return None


def is_step_reusable(name: str, *, data_source: str, profile: str) -> tuple[bool, str]:
    if name == "fetch_real_data":
        return is_real_data_fetch_complete()
    if name == "fetch_real_events":
        missing = [str(OUTPUT / f"events_{market}.pkl") for market in ("us", "cn", "hk", "jp") if not (OUTPUT / f"events_{market}.pkl").exists()]
        if missing:
            return False, f"missing event files: {missing}"
        return True, "event files exist"
    if name == "retraining":
        if not (data_source == "real" and profile == "full"):
            return False, "non-authoritative retraining does not reuse formal output artifacts"
        results_path = OUTPUT / "results.json"
        evaluation_path = OUTPUT / "evaluation.json"
        labels_path = OUTPUT / "labels.csv"
        if not results_path.exists() or not evaluation_path.exists() or not labels_path.exists():
            return False, "training outputs are incomplete"
        try:
            results = json.loads(results_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False, "results.json is not valid JSON"
        if not results.get("models"):
            return False, "results.json has no model entries"
        if results.get("data_source") != data_source:
            return False, f"results data_source={results.get('data_source')!r} does not match {data_source!r}"
        if results.get("training_profile") != profile:
            return False, f"results training_profile={results.get('training_profile')!r} does not match {profile!r}"
        return True, "training outputs exist"
    if name == "audits":
        if not (data_source == "real" and profile == "full"):
            return False, "non-authoritative retraining does not reuse formal audit artifacts"
        expected = [
            AUDITS / "data_coverage.json",
            AUDITS / "label_coverage.json",
            AUDITS / "event_feature_coverage.json",
            AUDITS / "pit_audit.json",
            AUDITS / "regime_breakdown.json",
            AUDITS / "recent_window_breakdown.json",
        ]
        missing = [str(path) for path in expected if not path.exists()]
        if missing:
            return False, f"missing audit files: {missing}"
        results_path = OUTPUT / "results.json"
        if results_path.exists():
            stale = [str(path) for path in expected if path.stat().st_mtime < results_path.stat().st_mtime]
            if stale:
                return False, f"audit files older than results.json: {stale}"
        return True, "audit outputs exist"
    return False, "unknown step"


def is_real_data_fetch_complete() -> tuple[bool, str]:
    validation_path = PROJECT / "temp" / "fetch_validation.json"
    if not validation_path.exists():
        return False, "missing fetch validation report"
    try:
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "fetch validation report is not valid JSON"
    missing_by_market = {
        market: report.get("missing_symbols", [])
        for market, report in validation.items()
        if report.get("missing_symbols")
    }
    if missing_by_market:
        return False, f"validation has missing symbols: {missing_by_market}"
    missing_bundles = [
        str(OUTPUT / f"bundle_{market}.pkl")
        for market in ("us", "cn", "hk", "jp")
        if not (OUTPUT / f"bundle_{market}.pkl").exists()
    ]
    if missing_bundles:
        return False, f"missing bundle files: {missing_bundles}"
    return True, "all real bundle symbols fetched"


def run_step(*, status: dict, status_path: Path, log_path: Path, name: str, command: list[str]) -> None:
    step = {
        "name": name,
        "command": command,
        "state": "running",
        "started_at": utc_now(),
        "ended_at": None,
        "returncode": None,
    }
    status["current_step"] = name
    status["steps"].append(step)
    write_status(status_path, status)

    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{utc_now()}] STEP {name}: {' '.join(command)}\n")
        log_file.flush()
        env = os.environ.copy()
        lib_path = str(PROJECT / "lib")
        env["DYLD_LIBRARY_PATH"] = f"{lib_path}:{env.get('DYLD_LIBRARY_PATH', '')}"
        process = subprocess.Popen(
            command,
            cwd=PROJECT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        step["pid"] = process.pid
        write_status(status_path, status)
        try:
            returncode = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            step["state"] = "failed"
            step["ended_at"] = utc_now()
            step["returncode"] = process.returncode
            step["detail"] = "interrupted"
            write_status(status_path, status)
            raise

    step["state"] = "succeeded" if returncode == 0 else "failed"
    step["ended_at"] = utc_now()
    step["returncode"] = returncode
    write_status(status_path, status)
    if returncode != 0:
        raise RuntimeError(f"step {name} failed with return code {returncode}")


AUDITS = PROJECT / "audits"


def summarize_outputs() -> dict:
    summary: dict = {}
    labels_path = OUTPUT / "labels.csv"
    if labels_path.exists():
        symbols: set[str] = set()
        rows = 0
        with labels_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows += 1
                if row.get("symbol"):
                    symbols.add(row["symbol"])
        summary["labels"] = {"rows": rows, "symbols": len(symbols)}

    results_path = OUTPUT / "results.json"
    if results_path.exists():
        results = json.loads(results_path.read_text(encoding="utf-8"))
        models = results.get("models", [])
        summary["results"] = {
            "generated_at": results.get("generated_at"),
            "data_source": results.get("data_source"),
            "training_profile": results.get("training_profile"),
            "included_markets": results.get("included_markets", []),
            "excluded_markets": results.get("excluded_markets", []),
            "models": len(models),
            "approved_models": [
                model.get("trainer_name")
                for model in models
                if model.get("eligible_for_approval")
            ],
            "approval_summary": results.get("approval_summary", {}),
            "samples_with_events": results.get("samples_with_events"),
        }
    return summary


def make_initial_status(args: argparse.Namespace, *, stamp: str, log_path: Path) -> dict:
    return {
        "run_id": f"training-job-{stamp}",
        "state": "running",
        "pid": os.getpid(),
        "started_at": utc_now(),
        "updated_at": utc_now(),
        "completed_at": None,
        "data_source": args.data_source,
        "profile": args.profile,
        "refresh_real_data": args.refresh_real_data,
        "refresh_real_events": args.refresh_real_events,
        "skip_audits": args.skip_audits,
        "current_step": None,
        "log_path": str(log_path),
        "steps": [],
        "output_summary": {},
    }


def prepare_status(args: argparse.Namespace) -> tuple[dict, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    existing = load_status(args.status) if args.resume else None
    if existing is None:
        log_path = args.log or (RUNS / f"training-job-{stamp}.log")
        return make_initial_status(args, stamp=stamp, log_path=log_path), log_path

    log_path = args.log or Path(existing.get("log_path") or RUNS / f"training-job-{stamp}.log")
    existing["state"] = "running"
    existing.pop("error", None)
    existing["completed_at"] = None
    existing["pid"] = os.getpid()
    existing["resumed_at"] = utc_now()
    existing["data_source"] = args.data_source
    existing["profile"] = args.profile
    existing["refresh_real_data"] = args.refresh_real_data
    existing["refresh_real_events"] = args.refresh_real_events
    existing["skip_audits"] = args.skip_audits
    existing["current_step"] = None
    existing["log_path"] = str(log_path)
    existing.setdefault("steps", [])
    existing.setdefault("output_summary", {})
    return existing, log_path


def maybe_run_step(
    *,
    status: dict,
    status_path: Path,
    log_path: Path,
    name: str,
    command: list[str],
    resume: bool,
    forced_steps: set[str],
) -> None:
    if resume and name not in forced_steps:
        previous = last_matching_step(status, name=name, command=command)
        reusable, reason = is_step_reusable(
            name,
            data_source=status.get("data_source", ""),
            profile=status.get("profile", ""),
        )
        if previous is not None and previous.get("state") in {"succeeded", "skipped"} and reusable:
            append_skipped_step(
                status=status,
                status_path=status_path,
                name=name,
                command=command,
                detail=f"resume reused previous successful step: {reason}",
            )
            return
        if previous is not None and previous.get("state") in {"succeeded", "skipped"} and not reusable:
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"\n[{utc_now()}] RESUME invalidated {name}: {reason}\n")

    run_step(status=status, status_path=status_path, log_path=log_path, name=name, command=command)


def main() -> int:
    args = parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    status, log_path = prepare_status(args)
    write_status(args.status, status)

    python = sys.executable
    forced_steps = set(args.force_step or [])
    try:
        if args.data_source == "real" and args.refresh_real_data:
            maybe_run_step(
                status=status,
                status_path=args.status,
                log_path=log_path,
                name="fetch_real_data",
                command=[python, "scripts/fetch_real_data.py", "--allow-partial"],
                resume=args.resume,
                forced_steps=forced_steps,
            )
        if args.data_source == "real" and args.refresh_real_events:
            maybe_run_step(
                status=status,
                status_path=args.status,
                log_path=log_path,
                name="fetch_real_events",
                command=[python, "scripts/fetch_real_events.py"],
                resume=args.resume,
                forced_steps=forced_steps,
            )

        maybe_run_step(
            status=status,
            status_path=args.status,
            log_path=log_path,
            name="retraining",
            command=[
                python,
                "scripts/run_retraining.py",
                "--data-source",
                args.data_source,
                "--profile",
                args.profile,
            ],
            resume=args.resume,
            forced_steps=forced_steps,
        )

        if not args.skip_audits:
            maybe_run_step(
                status=status,
                status_path=args.status,
                log_path=log_path,
                name="audits",
                command=[python, "scripts/run_audits.py"],
                resume=args.resume,
                forced_steps=forced_steps,
            )
            maybe_run_step(
                status=status,
                status_path=args.status,
                log_path=log_path,
                name="feature_ablation",
                command=[python, "scripts/run_feature_ablation.py"],
                resume=args.resume,
                forced_steps=forced_steps,
            )

        status["state"] = "succeeded"
        status.pop("error", None)
        status["current_step"] = None
        status["completed_at"] = utc_now()
        status["output_summary"] = summarize_outputs()
        write_status(args.status, status)
        sync_audit_training_status(status)
        return 0
    except BaseException as exc:
        status["state"] = "failed"
        status["error"] = str(exc)
        status["completed_at"] = utc_now()
        status["output_summary"] = summarize_outputs()
        write_status(args.status, status)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{utc_now()}] JOB FAILED: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
