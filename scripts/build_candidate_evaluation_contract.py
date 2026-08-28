#!/usr/bin/env python3
"""Index four-task candidate reports without promoting them to production.

Candidate-suite reports are useful research evidence, but they are not the
formal model registry: they may lack a serialized model artifact, capacity
model or interval calibration.  This contract records exactly what is present
and what is missing, including prediction/report hashes, so the next formal
promotion run has an auditable hand-off.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

TASKS = (
    "excess_return_120d",
    "excess_return_240d",
    "future_max_drawdown_120d",
    "future_max_drawdown_240d",
)
METRIC_FIELDS = (
    "rank_ic", "rank_icir", "top_k_excess_return_after_cost",
    "top_bottom_spread_after_cost", "turnover", "max_drawdown_after_cost",
    "capacity_estimate", "year_rank_ic", "industry_rank_ic", "regime_rank_ic",
    "data_completeness_rank_ic", "pinball_loss", "mae", "interval_coverage",
)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _recorded(value: object) -> bool:
    return value not in (None, {}) and (not isinstance(value, dict) or bool(value))


def build(root: Path, reports_root: Path) -> dict:
    tasks: dict[str, dict] = {}
    blocking: list[str] = []
    for task in TASKS:
        report_path = reports_root / f"{task}.json"
        report = _read(report_path)
        predictions_ref = report.get("predictions_ref")
        prediction_path = Path(predictions_ref) if isinstance(predictions_ref, str) else reports_root.parent / "predictions" / f"{task}.parquet"
        if not prediction_path.is_absolute():
            prediction_path = root / prediction_path
        models: dict[str, dict] = {}
        for name, model in sorted((report.get("models") or {}).items()):
            holdout = model.get("holdout_metrics") if isinstance(model, dict) else {}
            holdout = holdout if isinstance(holdout, dict) else {}
            artifact_ref = None
            if isinstance(model, dict):
                artifact_ref = model.get("artifact_ref") or model.get("model_artifact_ref")
            artifact_path = Path(artifact_ref) if isinstance(artifact_ref, str) else Path()
            if isinstance(artifact_ref, str) and not artifact_path.is_absolute():
                artifact_path = root / artifact_path
            fields = {
                field: {
                    "status": "recorded" if _recorded(holdout.get(field)) else "not_recorded",
                    "value": holdout.get(field) if _recorded(holdout.get(field)) else None,
                }
                for field in METRIC_FIELDS
            }
            missing = [field for field, item in fields.items() if item["status"] != "recorded"]
            models[str(name)] = {
                "status": model.get("status", "research_only"),
                "holdout_sample_count": holdout.get("sample_count"),
                "fields": fields,
                "missing_fields": missing,
                "artifact_ref": str(artifact_ref) if artifact_ref else None,
                "artifact_exists": bool(artifact_ref and artifact_path.is_file()),
                "artifact_sha256": _sha256(artifact_path) if artifact_ref else None,
            }
        model_names = list(models)
        complete_models = [
            name for name, item in models.items()
            if not item["missing_fields"] and item["artifact_exists"]
        ]
        complete_metric_models = [name for name, item in models.items() if not item["missing_fields"]]
        task_payload = {
            "task": task,
            "report_ref": str(report_path),
            "report_sha256": _sha256(report_path),
            "report_status": report.get("status", "unavailable"),
            "deployment_ready": report.get("deployment_ready", False),
            "predictions_ref": str(prediction_path),
            "predictions_sha256": _sha256(prediction_path),
            "prediction_exists": prediction_path.is_file(),
            "model_count": len(model_names),
            "complete_model_names": complete_models,
            "complete_metric_model_names": complete_metric_models,
            "models": models,
            "gate_reasons": list(report.get("gate_reasons") or report.get("blocking_reasons") or []),
            "formal_promotion_eligible": bool(
                report.get("status") == "validated"
                and report.get("deployment_ready") is True
                and complete_models
                and prediction_path.is_file()
            ),
        }
        if not report:
            blocking.append(f"candidate_report_missing:{task}")
        if not prediction_path.is_file():
            blocking.append(f"candidate_predictions_missing:{task}")
        if not complete_models:
            blocking.append(f"candidate_metrics_incomplete:{task}")
            if not any(item["artifact_exists"] for item in models.values()):
                blocking.append(f"candidate_model_artifact_missing:{task}")
        tasks[task] = task_payload

    return {
        "schema_version": "long-term-candidate-evaluation-contract-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "tasks": tasks,
        "task_count": len(tasks),
        "metric_fields": list(METRIC_FIELDS),
        "status": "complete" if not blocking else "incomplete",
        "blocking_reasons": sorted(set(blocking)),
        "promotion_rule": "all task reports, predictions, model artifacts and required metrics must be validated; this index never promotes a candidate",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--reports-root", type=Path, default=PROJECT / "artifacts/long_term_training/candidate-suite/reports")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/long_term_training/candidate-suite/evaluation-contract.json")
    args = parser.parse_args()
    payload = build(args.project_root.resolve(), args.reports_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"status": payload["status"], "task_count": payload["task_count"], "blocking_reasons": payload["blocking_reasons"]}, ensure_ascii=False))
    return 0 if payload["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
