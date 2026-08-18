"""Compact, auditable storage for model-evaluation predictions.

Evaluation JSON is intended for manifests and dashboards, not for carrying
millions of row-level predictions.  This module keeps the JSON summary small
and writes the reproducible prediction rows to a compressed Parquet sidecar.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


_PREDICTION_FIELDS = {
    "raw_oof_scores", "oof_scores", "oof_labels", "oof_fold_ids",
    "raw_probabilities", "probabilities", "labels",
    "quantiles", "targets",
    "holdout_scores", "holdout_labels", "stress_scores", "stress_labels",
    "holdout_probabilities", "stress_probabilities",
    "holdout_quantiles", "stress_quantiles", "holdout_targets", "stress_targets",
}


def write_compact_evaluation(
    task: str,
    result: Any,
    output_path: Path,
    *,
    reference: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Write prediction rows to compressed Parquet and return a JSON summary.

    The returned payload contains metrics and a content hash/reference only;
    no row-level prediction arrays are embedded in the JSON artifact.
    """
    payload = _jsonable(result)
    rows = _prediction_rows(task, payload)
    if not rows:
        raise ValueError(f"evaluation has no prediction rows: {task}")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - dependency is part of train extra
        raise RuntimeError("compact evaluation output requires pyarrow") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, output_path, compression="zstd", use_dictionary=True)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    summary = _strip_prediction_fields(payload)
    summary["prediction_artifact"] = {
        "ref": reference or output_path.name,
        "sha256": digest,
        "row_count": len(rows),
        "compression": "zstd",
        "format": "parquet",
    }
    return summary, digest


def _prediction_rows(task: str, payload: dict[str, Any]) -> list[dict[str, str | int | None]]:
    rows: list[dict[str, str | int | None]] = []
    candidates = payload.get("candidates", [])
    for candidate in candidates:
        name = str(candidate.get("name", "unknown"))
        if task == "drawdown_20d":
            rows.extend(_rows_for_split(task, "oof", name, candidate.get("oof_scores", []), candidate.get("oof_labels", []), candidate.get("raw_oof_scores", []), candidate.get("oof_fold_ids", [])))
        elif task.startswith("direction_"):
            rows.extend(_rows_for_split(task, "oof", name, candidate.get("probabilities", []), candidate.get("labels", []), candidate.get("raw_probabilities", []), []))
        elif task == "return_20d":
            rows.extend(_rows_for_split(task, "oof", name, candidate.get("quantiles", []), candidate.get("targets", []), [], []))
    selected = str(payload.get("selected_candidate", "selected"))
    if task == "drawdown_20d":
        rows.extend(_rows_for_split(task, "holdout", selected, payload.get("holdout_scores", []), payload.get("holdout_labels", []), [], []))
        rows.extend(_rows_for_split(task, "stress", selected, payload.get("stress_scores", []), payload.get("stress_labels", []), [], []))
    elif task.startswith("direction_"):
        rows.extend(_rows_for_split(task, "holdout", selected, payload.get("holdout_probabilities", []), payload.get("holdout_labels", []), [], []))
        rows.extend(_rows_for_split(task, "stress", selected, payload.get("stress_probabilities", []), payload.get("stress_labels", []), [], []))
    elif task == "return_20d":
        rows.extend(_rows_for_split(task, "holdout", selected, payload.get("holdout_quantiles", []), payload.get("holdout_targets", []), [], []))
        rows.extend(_rows_for_split(task, "stress", selected, payload.get("stress_quantiles", []), payload.get("stress_targets", []), [], []))
    return rows


def _rows_for_split(task: str, split: str, candidate: str, predictions: Any, targets: Any, raw: Any, fold_ids: Any) -> list[dict[str, str | int | None]]:
    predictions = list(predictions or [])
    targets = list(targets or [])
    raw = list(raw or [])
    fold_ids = list(fold_ids or [])
    rows = []
    for index, prediction in enumerate(predictions):
        rows.append({
            "task": task,
            "split": split,
            "candidate": candidate,
            "row_index": index,
            "fold_id": str(fold_ids[index]) if index < len(fold_ids) else None,
            "prediction_json": _stable_json(prediction),
            "raw_prediction_json": _stable_json(raw[index]) if index < len(raw) else None,
            "target_json": _stable_json(targets[index]) if index < len(targets) else None,
        })
    return rows


def _strip_prediction_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_prediction_fields(item) for key, item in value.items() if key not in _PREDICTION_FIELDS}
    if isinstance(value, list):
        return [_strip_prediction_fields(item) for item in value]
    return value


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
