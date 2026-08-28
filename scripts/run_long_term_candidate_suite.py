#!/usr/bin/env python3
"""Run the long-term candidate suite against an immutable research rebuild.

This is an experiment runner, not a production activation path.  It creates
one bound manifest list from the rebuild index, runs each target independently,
and reuses completed reports and per-fold checkpoints after interruption.
CUDA is deliberately restricted to GPU0; a research-only run never writes an
active snapshot or changes the production roster.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = (
    "excess_return_120d",
    "excess_return_240d",
    "future_max_drawdown_120d",
    "future_max_drawdown_240d",
)
EVALUATION_FIELDS = (
    "rank_ic",
    "rank_icir",
    "top_k_excess_return_after_cost",
    "top_bottom_spread_after_cost",
    "turnover",
    "max_drawdown_after_cost",
    "capacity_estimate",
    "year_rank_ic",
    "industry_rank_ic",
    "regime_rank_ic",
    "data_completeness_rank_ic",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-index", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, default=PROJECT / "artifacts/long_term_training/candidate-suite")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/parquet")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument("--tasks", nargs="+", default=list(DEFAULT_TARGETS))
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--enrich-liquidity-from-rebuild", action="store_true",
        help="Join same-date amount/turnover from the immutable rebuild standard layer.",
    )
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    return parser.parse_args()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _metric_contract(report: dict) -> dict:
    """Return an explicit per-model metric contract without filling gaps.

    Baseline reports are allowed to remain research-only, but a missing metric
    is never represented as zero.  The suite report is consequently useful to
    both the readiness audit and the UI even when a run is interrupted.
    """
    models = report.get("models") if isinstance(report, dict) else None
    if not isinstance(models, dict):
        return {"status": "not_recorded", "models": {}}
    by_model = {}
    for name, model in sorted(models.items()):
        holdout = model.get("holdout_metrics") if isinstance(model, dict) else None
        if not isinstance(holdout, dict):
            by_model[str(name)] = {field: "not_recorded" for field in EVALUATION_FIELDS}
            continue
        by_model[str(name)] = {
            field: "recorded" if field in holdout and holdout[field] not in (None, {}) else "not_recorded"
            for field in EVALUATION_FIELDS
        }
    missing = [
        f"{model}:{field}"
        for model, fields in by_model.items()
        for field, state in fields.items()
        if state != "recorded"
    ]
    return {
        "status": "complete" if not missing else "incomplete",
        "required_fields": list(EVALUATION_FIELDS),
        "models": by_model,
        "missing": missing,
    }


def _task_artifact(output: Path, predictions: Path) -> dict:
    report = _read_json(output)
    prediction_hash = _sha256(predictions)
    return {
        "status": report.get("status", "unavailable"),
        "deployment_ready": report.get("deployment_ready"),
        "snapshot_id": report.get("snapshot_id"),
        "data_tier": report.get("data_tier"),
        "report_ref": str(output),
        "report_sha256": _sha256(output),
        "predictions_ref": str(predictions) if prediction_hash else None,
        "predictions_sha256": prediction_hash,
        "prediction_row_count": report.get("prediction_row_count"),
        "evaluation_metric_contract": _metric_contract(report),
        "blocking_reasons": list(report.get("blocking_reasons") or report.get("gate_reasons") or []),
    }


def _write_suite_report(root: Path, status: dict, *, finished: bool = False) -> dict:
    tasks = {}
    for task in DEFAULT_TARGETS:
        stage = next((item for item in status.get("stages", []) if item.get("task") == task), {})
        output = Path(stage.get("output", root / "reports" / f"{task}.json"))
        predictions = Path(stage.get("predictions", root / "predictions" / f"{task}.parquet"))
        tasks[task] = {
            "stage_status": stage.get("status", "pending"),
            **_task_artifact(output, predictions),
        }
    complete = all(
        item["stage_status"] in {"completed", "skipped_completed"}
        and item["status"] == "research_only"
        and item["deployment_ready"] is False
        for item in tasks.values()
    )
    payload = {
        "schema_version": "long-term-candidate-suite-report-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "research_only" if complete else ("blocked" if finished else "running"),
        "deployment_ready": False,
        "task_contract": {
            "primary_tasks": list(DEFAULT_TARGETS),
            "task_count": len(DEFAULT_TARGETS),
            "evaluation_fields": list(EVALUATION_FIELDS),
            "minimum_shadow_sessions": 60,
        },
        "tasks": tasks,
        "blocking_reasons": sorted({
            reason
            for item in tasks.values()
            for reason in item.get("blocking_reasons", [])
        }),
        "suite_status_ref": str(root / "suite-status.json"),
    }
    write_json(root / "suite-report.json", payload)
    return payload


def _bound_manifest_file(rebuild_index: Path, output: Path) -> tuple[Path, int]:
    rebuild = json.loads(rebuild_index.read_text(encoding="utf-8"))
    context = rebuild.get("contexts", {}).get("close_confirmed", {})
    grouped = context.get("sample_manifests", {})
    values = [value for group in grouped.values() for value in group]
    if not values:
        raise SystemExit("rebuild index contains no close_confirmed sample manifests")
    manifest_file = output / "manifest-lists" / "cn_research_only.json"
    write_json(manifest_file, {
        "schema_version": "research-only-bound-manifest-list-v1",
        "rebuild_index": str(rebuild_index),
        "snapshot_id": rebuild.get("as_of") or rebuild.get("snapshot_id"),
        "sample_manifests": values,
    })
    return manifest_file, len(values)


def _complete(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("status") == "research_only" and payload.get("deployment_ready") is False


def main() -> int:
    args = parse_args()
    rebuild = args.rebuild_index.resolve()
    root = args.run_root.resolve()
    object_store = args.object_store.resolve()
    data_root = args.data_root.resolve()
    requested_tasks = tuple(args.tasks)
    if requested_tasks != DEFAULT_TARGETS:
        raise SystemExit(
            "the long-term candidate suite is fixed to the four canonical tasks: "
            + ", ".join(DEFAULT_TARGETS)
        )
    root.mkdir(parents=True, exist_ok=True)
    manifest_file, manifest_count = _bound_manifest_file(rebuild, root)
    status_path = root / "suite-status.json"
    status = {
        "schema_version": "long-term-candidate-suite-v2",
        "status": "running",
        "mode": "research_only",
        "gpu_policy": {"CUDA_VISIBLE_DEVICES": "0", "INVESTMENT_RESEARCH_USE_GPU": "1"},
        "rebuild_index": str(rebuild),
        "manifest_file": str(manifest_file),
        "manifest_count": manifest_count,
        "tasks": list(DEFAULT_TARGETS),
        "task_contract": {"primary_tasks": list(DEFAULT_TARGETS), "minimum_shadow_sessions": 60},
        "stages": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(status_path, status)
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": str(PROJECT / "src"),
        "CUDA_VISIBLE_DEVICES": "0",
        "INVESTMENT_RESEARCH_USE_GPU": "1",
        "INVESTMENT_RESEARCH_TORCH_DEVICE": "cuda",
        "INVESTMENT_RESEARCH_CPU_THREADS": str(args.threads),
        "OMP_NUM_THREADS": str(args.threads),
        "MKL_NUM_THREADS": str(args.threads),
        "OPENBLAS_NUM_THREADS": str(args.threads),
        "NUMEXPR_NUM_THREADS": str(args.threads),
        "OMP_DYNAMIC": "FALSE",
        "PYTHONUNBUFFERED": "1",
    })
    for task in args.tasks:
        output = root / "reports" / f"{task}.json"
        predictions = root / "predictions" / f"{task}.parquet"
        checkpoint = root / "checkpoints" / task
        stage = {
            "task": task,
            "output": str(output),
            "predictions": str(predictions),
            "checkpoint_dir": str(checkpoint),
        }
        status["stages"] = [item for item in status["stages"] if item.get("task") != task] + [stage]
        write_json(status_path, status)
        if not args.no_resume and _complete(output) and predictions.is_file():
            stage.update({"status": "skipped_completed", "resumed": True})
            write_json(status_path, status)
            _write_suite_report(root, status)
            continue
        command = [
            sys.executable, str(PROJECT / "scripts/run_long_term_training.py"),
            "--samples", str(manifest_file),
            "--object-store", str(object_store),
            "--data-root", str(data_root),
            "--rebuild-index", str(rebuild),
            "--allow-research-only",
            "--target", task,
            "--output", str(output),
            "--predictions-output", str(predictions),
            "--checkpoint-dir", str(checkpoint),
        ]
        if args.enrich_liquidity_from_rebuild:
            command.append("--enrich-liquidity-from-rebuild")
        if args.no_resume:
            command.append("--no-resume")
        log = root / "logs" / f"{task}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n$ " + " ".join(command) + "\n")
            completed = subprocess.run(command, env=environment, stdout=handle, stderr=subprocess.STDOUT, check=False)
        stage.update({
            "status": "completed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "log": str(log),
        })
        write_json(status_path, status)
        _write_suite_report(root, status)
        if completed.returncode != 0:
            status["status"] = "failed"
            write_json(status_path, status)
            _write_suite_report(root, status, finished=True)
            return completed.returncode
    status["status"] = "completed_research_only"
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(status_path, status)
    suite = _write_suite_report(root, status, finished=True)
    return 0 if suite["status"] == "research_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
