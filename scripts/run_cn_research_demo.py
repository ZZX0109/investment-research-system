#!/usr/bin/env python3
"""Run the fixed zero-budget CN research demonstration end to end.

The command deliberately stops at the first failed evidence stage.  It never
turns public backfills into formal PIT data and never bypasses cohort, model,
artifact, or shadow gates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT / "scripts"
COHORTS = ("cn_equity_core", "cn_etf_benchmark")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the reproducible CN research demo")
    parser.add_argument("--max-symbols", type=int, default=None, help="Development-only provider cap; omit for the fixed 100-stock plus 5-ETF workflow.")
    parser.add_argument("--symbols-per-cohort", type=int, default=3)
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=PROJECT / "artifacts/cn_research_demo/latest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = [
        "incremental_public_collection_and_raw_hash",
        "quality_audit_fixed_cohort_and_snapshot",
        "same_fold_four_task_model_comparison",
        "research_roster_and_report_hash_freeze",
        "roster_bound_hash_verified_inference",
        "immutable_research_shadow_freeze",
    ]
    if args.dry_run:
        print(json.dumps({"data_tier": "research_pit", "deployment_ready": False, "stages": plan}, ensure_ascii=False, indent=2))
        return 0

    report: dict[str, Any] = {
        "schema_version": "cn-zero-budget-research-demo-v1",
        "data_tier": "research_pit",
        "status": "running",
        "deployment_ready": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "stages": [],
    }
    try:
        if not args.skip_collection:
            command = [sys.executable, "scripts/run_free_research_cycle.py", "--skip-rebuild"]
            if args.max_symbols is not None:
                command.extend(["--max-symbols", str(args.max_symbols)])
            _run("incremental_public_collection_and_raw_hash", command, report)

        rebuild_path = _run_path(
            "quality_audit_fixed_cohort_and_snapshot",
            [sys.executable, "scripts/rebuild_cn_research_pit.py"], report,
        )
        rebuild = json.loads(rebuild_path.read_text(encoding="utf-8"))
        if rebuild.get("training_blocked"):
            raise RuntimeError("fixed cohort training gate blocked: " + ",".join(rebuild.get("training_blocking_reasons", [])))
        context = rebuild["contexts"]["close_confirmed"]

        for cohort in COHORTS:
            manifests = [str(Path(item)) for item in context["sample_manifests"].get(cohort, [])]
            if not manifests:
                raise RuntimeError(f"no frozen sample manifests for {cohort}")
            _run(
                f"same_fold_four_task_model_comparison:{cohort}",
                [sys.executable, "scripts/run_free_research_training.py", "--cohort", cohort, "--sample-manifest", *manifests],
                report,
                timeout=24 * 60 * 60,
            )
            _verify_rosters(cohort, report)
            cohort_manifest = json.loads(Path(rebuild["cohort_refs"][cohort]).read_text(encoding="utf-8"))
            symbols = [item["symbol"] for item in cohort_manifest["members"][: args.symbols_per_cohort]]
            if not symbols:
                raise RuntimeError(f"cohort has no inference members: {cohort}")
            prediction = PROJECT / "artifacts" / "predictions" / f"cn-research-{cohort}.json"
            _run(
                f"roster_bound_hash_verified_inference:{cohort}",
                [
                    sys.executable, "scripts/run_cn_research_inference.py",
                    "--rebuild-index", str(rebuild_path), "--cohort", cohort,
                    "--symbols", *symbols, "--output", str(prediction),
                ],
                report,
            )
            _run(
                f"immutable_research_shadow_freeze:{cohort}",
                [
                    sys.executable, "scripts/run_free_research_cycle.py",
                    "--skip-collection", "--skip-rebuild", "--freeze-shadow",
                    "--prediction-file", str(prediction),
                ],
                report,
            )
        report["status"] = "research_complete"
        return_code = 0
    except Exception as exc:
        report["status"] = "blocked"
        report["blocking_reason"] = f"{type(exc).__name__}:{exc}"
        return_code = 2
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(args.report)
    return return_code


def _run(label: str, command: list[str], report: dict[str, Any], *, timeout: int = 7200) -> str:
    completed = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, timeout=timeout, check=False)
    report["stages"].append({
        "stage": label,
        "status": "completed" if completed.returncode == 0 else "blocked",
        "return_code": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    })
    if completed.returncode != 0:
        raise RuntimeError(f"{label} returned {completed.returncode}")
    return completed.stdout


def _run_path(label: str, command: list[str], report: dict[str, Any]) -> Path:
    stdout = _run(label, command, report)
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{label} did not return an artifact path")
    path = Path(lines[-1])
    if not path.is_absolute():
        path = PROJECT / path
    if not path.is_file():
        raise RuntimeError(f"{label} artifact does not exist")
    return path


def _verify_rosters(cohort: str, report: dict[str, Any]) -> None:
    missing = []
    for task in ("direction_1d", "direction_5d", "return_20d", "drawdown_20d"):
        path = PROJECT / "artifacts/free_research_models/cn/close_confirmed" / cohort / task / "research_model_roster.json"
        if not path.is_file():
            missing.append(task)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "research_only" or payload.get("deployment_ready") is not False:
            raise RuntimeError(f"research roster governance violation: {cohort}/{task}")
    if missing:
        raise RuntimeError(f"missing research rosters for {cohort}: {','.join(missing)}")
    report["stages"].append({"stage": f"research_roster_and_report_hash_freeze:{cohort}", "status": "completed"})


if __name__ == "__main__":
    raise SystemExit(main())
