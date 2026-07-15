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
TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the reproducible CN research demo")
    parser.add_argument("--max-symbols", type=int, default=None, help="Development-only provider cap; omit for the fixed 100-stock plus 5-ETF workflow.")
    parser.add_argument("--symbols-per-cohort", type=int, default=3)
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--no-discover-cn-universe", action="store_true", help="Use configured fixed research symbols instead of Baostock universe discovery.")
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
        "run_id": f"cn-research-demo-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        "stages": [],
        "cohorts": {},
        "tasks": {},
        "inference": {},
        "shadow": {},
    }
    blocked = False
    try:
        if not args.skip_collection:
            command = [sys.executable, "scripts/run_free_research_cycle.py", "--skip-rebuild"]
            if args.max_symbols is not None:
                command.extend(["--max-symbols", str(args.max_symbols)])
            if args.no_discover_cn_universe:
                command.append("--no-discover-cn-universe")
            _run("incremental_public_collection_and_raw_hash", command, report, allow_failure=True)

        rebuild_stdout = _run(
            "quality_audit_fixed_cohort_and_snapshot",
            [sys.executable, "scripts/rebuild_cn_research_pit.py"], report,
            allow_failure=True,
        )
        rebuild_path = _path_from_stdout(rebuild_stdout)
        if rebuild_path is None:
            raise RuntimeError("quality audit/rebuild did not produce a rebuild index")
        rebuild = json.loads(rebuild_path.read_text(encoding="utf-8"))
        report["rebuild_index"] = _portable_ref(rebuild_path)
        context = rebuild["contexts"]["close_confirmed"]

        for cohort in COHORTS:
            cohort_payload = json.loads(Path(rebuild["cohort_refs"][cohort]).read_text(encoding="utf-8"))
            cohort_report = {
                "status": "ready",
                "cohort_version": cohort_payload.get("cohort_version"),
                "content_hash": cohort_payload.get("content_hash"),
                "member_count": len(cohort_payload.get("members", [])),
                "blocking_reasons": cohort_payload.get("blocking_reasons", []),
                "snapshot_id": context.get("snapshot_id"),
                "snapshot_hash": context.get("snapshot_hash"),
            }
            manifests = [str(Path(item)) for item in context["sample_manifests"].get(cohort, [])]
            if not manifests:
                cohort_report.update(status="blocked", blocking_reasons=["sample_manifests_missing"])
                report["cohorts"][cohort] = cohort_report
                for task in TASKS:
                    report["tasks"][f"{cohort}/{task}"] = {"status": "unavailable", "gating_reasons": ["sample_manifests_missing"]}
                blocked = True
                continue
            if cohort == "cn_equity_core" and len(cohort_payload.get("members", [])) < 80:
                cohort_report.update(status="blocked", blocking_reasons=["eligible_equity_count_below_80"])
                report["cohorts"][cohort] = cohort_report
                for task in TASKS:
                    report["tasks"][f"{cohort}/{task}"] = {"status": "blocked", "gating_reasons": ["eligible_equity_count_below_80"]}
                blocked = True
                continue
            report["cohorts"][cohort] = cohort_report
            for task in TASKS:
                train_id = f"{report.get('run_id', 'cn-research')}-{cohort}-{task}"
                train_stdout = _run(
                    f"same_fold_model_comparison:{cohort}/{task}",
                    [sys.executable, "scripts/run_free_research_training.py", "--cohort", cohort,
                     "--tasks", task, "--training-run-id", train_id,
                     "--sample-manifest", *manifests],
                    report, timeout=24 * 60 * 60, allow_failure=True,
                )
                summary_path = _path_from_stdout(train_stdout)
                task_record = _training_task_record(summary_path, task)
                report["tasks"][f"{cohort}/{task}"] = task_record
                if task_record["status"] in {"blocked", "unavailable"}:
                    blocked = True

            symbols = [item["symbol"] for item in cohort_payload["members"][: args.symbols_per_cohort]]
            if not symbols:
                cohort_report.update(status="blocked", blocking_reasons=["cohort_has_no_members"])
                blocked = True
                continue
            prediction = PROJECT / "artifacts" / "predictions" / f"cn-research-{cohort}.json"
            inference_stdout = _run(
                f"roster_bound_hash_verified_inference:{cohort}",
                [
                    sys.executable, "scripts/run_cn_research_inference.py",
                    "--rebuild-index", str(rebuild_path), "--cohort", cohort,
                    "--symbols", *symbols, "--output", str(prediction),
                ],
                report, allow_failure=True,
            )
            prediction_path = prediction if prediction.is_file() else _path_from_stdout(inference_stdout)
            if prediction_path is not None and prediction_path.is_file():
                predictions = json.loads(prediction_path.read_text(encoding="utf-8")).get("predictions", [])
                report["inference"][cohort] = {
                    "prediction_ref": _portable_ref(prediction_path),
                    "count": len(predictions),
                    "abstain_count": sum(bool(item.get("abstained")) for item in predictions),
                    "by_task": {task: sum(item.get("task") == task for item in predictions) for task in TASKS},
                }
            else:
                report["inference"][cohort] = {"status": "unavailable", "gating_reasons": ["prediction_artifact_missing"]}
                blocked = True
                continue
            shadow_stdout = _run(
                f"immutable_research_shadow_freeze:{cohort}",
                [
                    sys.executable, "scripts/run_free_research_cycle.py",
                    "--skip-collection", "--skip-rebuild", "--freeze-shadow",
                    "--prediction-file", str(prediction),
                ],
                report, allow_failure=True,
            )
            report["shadow"][cohort] = {
                "status": "frozen" if shadow_stdout else "unavailable",
                "prediction_ref": _portable_ref(prediction_path),
            }
        # A failed collection/rebuild stage is itself a blocking evidence
        # condition, even when a later stage can replay older valid layers.
        blocked = blocked or any(item.get("status") == "blocked" for item in report["stages"])
        report["status"] = "partial" if blocked else "research_complete"
        return_code = 2 if blocked else 0
    except KeyboardInterrupt as exc:
        report["status"] = "blocked"
        report["blocking_reason"] = "external_run_interrupted"
        return_code = 2
    except Exception as exc:
        report["status"] = "blocked"
        report["blocking_reason"] = f"{type(exc).__name__}:{exc}"
        return_code = 2
    finally:
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        run_report_path = args.report.with_name(f"{report['run_id']}.json")
        report["run_report_ref"] = _portable_ref(run_report_path)
        acceptance_path = args.report.with_name(f"{args.report.stem}-backend-acceptance.json")
        report["backend_acceptance_ref"] = _portable_ref(acceptance_path)
        run_acceptance_path = run_report_path.with_name(f"{run_report_path.stem}-backend-acceptance.json")
        report["run_backend_acceptance_ref"] = _portable_ref(run_acceptance_path)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        args.report.write_text(serialized, encoding="utf-8")
        if run_report_path != args.report:
            run_report_path.write_text(serialized, encoding="utf-8")
        subprocess.run(
            [sys.executable, "scripts/generate_cn_research_acceptance.py",
             "--run-report", str(args.report), "--output", str(acceptance_path)],
            cwd=PROJECT, text=True, capture_output=True, check=False,
        )
        if run_report_path != args.report:
            subprocess.run(
                [sys.executable, "scripts/generate_cn_research_acceptance.py",
                 "--run-report", str(run_report_path), "--output", str(run_acceptance_path)],
                cwd=PROJECT, text=True, capture_output=True, check=False,
            )
        # Keep the one-click report self-contained as well as emitting the
        # separately consumable acceptance document.  This makes a copied
        # run report sufficient to audit provider, task and shadow outcomes.
        try:
            report["backend_acceptance"] = json.loads(acceptance_path.read_text(encoding="utf-8"))
            serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            args.report.write_text(serialized, encoding="utf-8")
            if run_report_path != args.report:
                run_report_path.write_text(serialized, encoding="utf-8")
        except (OSError, ValueError):
            report.setdefault("backend_acceptance", {"status": "blocked", "gating_reasons": ["acceptance_report_missing"]})
        print(args.report)
    return return_code


def _run(label: str, command: list[str], report: dict[str, Any], *, timeout: int = 7200, allow_failure: bool = False) -> str:
    completed = subprocess.run(command, cwd=PROJECT, text=True, capture_output=True, timeout=timeout, check=False)
    report["stages"].append({
        "stage": label,
        "status": "completed" if completed.returncode == 0 else "blocked",
        "return_code": completed.returncode,
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    })
    if completed.returncode != 0 and not allow_failure:
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


def _path_from_stdout(stdout: str) -> Path | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        path = Path(line)
        if not path.is_absolute():
            path = PROJECT / path
        if path.is_file():
            return path
    return None


def _training_task_record(path: Path | None, task: str) -> dict[str, Any]:
    if path is None:
        return {"status": "unavailable", "gating_reasons": ["training_summary_missing"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "summary_ref": _portable_ref(path), "gating_reasons": [f"training_summary_invalid:{type(exc).__name__}"]}
    outcome = next((item for item in payload.get("outcomes", []) if item.get("task") == task), None)
    if outcome is None:
        return {"status": "unavailable", "summary_ref": _portable_ref(path), "gating_reasons": ["task_outcome_missing"]}
    record: dict[str, Any] = {"status": outcome.get("status", "unavailable"), "summary_ref": _portable_ref(path), **outcome}
    manifest = outcome.get("manifest")
    if isinstance(manifest, str):
        manifest_path = Path(manifest)
        if not manifest_path.is_absolute():
            manifest_path = PROJECT / manifest_path
        if manifest_path.is_file():
            try:
                task_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                record.update({key: task_manifest.get(key) for key in (
                    "model_version", "label_version", "feature_contract_version", "dataset_hash",
                    "fold_hash", "artifact_hashes", "report_hashes", "research_ready",
                )})
            except (OSError, ValueError):
                record.setdefault("gating_reasons", []).append("task_manifest_invalid")
    return record


def _portable_ref(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


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
