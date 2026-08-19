"""Read-only adapter for the four long-horizon sequence model artifacts.

The downloaded ``.pt`` files are research artifacts, not replacements for the
existing tabular inference path.  This module keeps their provenance and input
contract explicit, verifies every referenced file before loading it, and
returns quantile observations without turning them into trade instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from investment_research.training.sequence_models import SequenceTaskRunner
from investment_research.training.models import TrainingSample
from investment_research.training.sequence_dataset import (
    SequenceExample,
    build_sequence_examples,
    validate_sequence_examples,
)


LONG_TERM_TASKS = (
    "excess_return_120d",
    "excess_return_240d",
    "future_max_drawdown_120d",
    "future_max_drawdown_240d",
)


class DeepLongTermArtifactError(ValueError):
    """Raised when a research model artifact cannot be verified or loaded."""


def _reading_horizon(task: str) -> int:
    suffix = task.rsplit("_", 1)[-1]
    if not suffix.endswith("d"):
        raise DeepLongTermArtifactError(f"long_term_task_horizon_invalid:{task}")
    try:
        return int(suffix[:-1])
    except ValueError as exc:
        raise DeepLongTermArtifactError(f"long_term_task_horizon_invalid:{task}") from exc


def _validate_reading(task: str, reading: dict[str, Any]) -> dict[str, Any]:
    """Validate and copy one model reading before it becomes an artifact."""
    if task not in LONG_TERM_TASKS:
        raise DeepLongTermArtifactError(f"model_reading_task_unsupported:{task}")
    if not isinstance(reading, dict):
        raise DeepLongTermArtifactError(f"model_reading_invalid:{task}")
    required = ("symbol", "data_as_of", "snapshot_id", "snapshot_hash", "model", "model_version", "artifact_hash")
    if any(not reading.get(field) for field in required):
        raise DeepLongTermArtifactError(f"model_reading_provenance_missing:{task}")
    artifact_hash = str(reading.get("artifact_hash"))
    if len(artifact_hash) != 64 or any(char not in "0123456789abcdef" for char in artifact_hash):
        raise DeepLongTermArtifactError(f"model_reading_artifact_hash_invalid:{task}")
    if reading.get("status") != "research_only" or reading.get("deployment_ready") is not False:
        raise DeepLongTermArtifactError(f"model_reading_activation_boundary_invalid:{task}")
    if int(reading.get("horizon_days", -1)) != _reading_horizon(task):
        raise DeepLongTermArtifactError(f"model_reading_horizon_mismatch:{task}")
    try:
        quantiles = [float(reading[name]) for name in ("q10", "q50", "q90")]
    except (KeyError, TypeError, ValueError) as exc:
        raise DeepLongTermArtifactError(f"model_reading_quantiles_missing:{task}") from exc
    if not all(math.isfinite(value) for value in quantiles) or not (quantiles[0] <= quantiles[1] <= quantiles[2]):
        raise DeepLongTermArtifactError(f"model_reading_quantiles_invalid:{task}")
    normalized = dict(reading)
    horizon_days = _reading_horizon(task)
    normalized.update({
        "task": task,
        "horizon": f"{horizon_days}d",
        "horizon_days": horizon_days,
        "q10": quantiles[0],
        "q50": quantiles[1],
        "q90": quantiles[2],
    })
    normalized["prediction_interval_width"] = quantiles[2] - quantiles[0]
    normalized["deployment_ready"] = False
    normalized["status"] = "research_only"
    return normalized


def write_long_term_model_readings(
    project_root: Path,
    readings_by_task: dict[str, list[dict[str, Any]]],
    *,
    output_path: Path | None = None,
    generated_at: datetime | None = None,
) -> Path:
    """Persist complete four-task readings outside scorecards and snapshots.

    The output is intentionally restricted to ``artifacts/long_term_model_readings``.
    It is an atomic, research-only summary: no download/landing/raw/standard/pit
    or active snapshot path can be used as an output target.
    """
    root = project_root.resolve()
    output_root = (root / "artifacts" / "long_term_model_readings").resolve()
    target = (output_path or (output_root / "latest.json")).resolve()
    if target != output_root and output_root not in target.parents:
        raise DeepLongTermArtifactError("model_readings_output_outside_artifacts")
    if target.name.startswith(".") or target.suffix.lower() != ".json":
        raise DeepLongTermArtifactError("model_readings_output_invalid")
    if not isinstance(readings_by_task, dict) or set(readings_by_task) != set(LONG_TERM_TASKS):
        raise DeepLongTermArtifactError("model_readings_tasks_incomplete")

    grouped: dict[str, dict[str, Any]] = {}
    snapshot_pairs: set[tuple[str, str | None]] = set()
    feature_contracts: set[str] = set()
    label_versions: set[str] = set()
    for task in LONG_TERM_TASKS:
        rows = readings_by_task.get(task)
        if not isinstance(rows, list) or not rows:
            raise DeepLongTermArtifactError(f"model_readings_task_empty:{task}")
        for raw in rows:
            reading = _validate_reading(task, raw)
            symbol = str(reading["symbol"]).strip().upper()
            snapshot_pairs.add((str(reading["snapshot_id"]), reading.get("snapshot_hash")))
            if reading.get("feature_contract_version"):
                feature_contracts.add(str(reading["feature_contract_version"]))
            if reading.get("label_version") not in (None, "", "unknown", "not_recorded"):
                label_versions.add(str(reading["label_version"]))
            entry = grouped.setdefault(symbol, {"symbol": symbol, "data_as_of": reading["data_as_of"], "snapshot_id": reading["snapshot_id"], "label_version": reading.get("label_version"), "tasks": {}})
            if entry["data_as_of"] != reading["data_as_of"] or entry["snapshot_id"] != reading["snapshot_id"]:
                raise DeepLongTermArtifactError(f"model_readings_symbol_context_mismatch:{symbol}")
            if entry["label_version"] != reading.get("label_version"):
                raise DeepLongTermArtifactError(f"model_readings_symbol_label_version_mismatch:{symbol}")
            if task in entry["tasks"]:
                raise DeepLongTermArtifactError(f"model_readings_duplicate:{symbol}:{task}")
            entry["tasks"][task] = reading

    if len(snapshot_pairs) != 1:
        raise DeepLongTermArtifactError("model_readings_snapshot_mixed")
    expected_tasks = set(LONG_TERM_TASKS)
    incomplete = sorted(symbol for symbol, entry in grouped.items() if set(entry["tasks"]) != expected_tasks)
    if incomplete:
        raise DeepLongTermArtifactError(f"model_readings_symbol_tasks_incomplete:{','.join(incomplete)}")
    if len(feature_contracts) > 1:
        raise DeepLongTermArtifactError("model_readings_feature_contract_mixed")
    if len(label_versions) > 1:
        raise DeepLongTermArtifactError("model_readings_label_version_mixed")

    snapshot_id, snapshot_hash = next(iter(snapshot_pairs))
    payload = {
        "schema_version": "long-term-model-readings-v1",
        "status": "research_only",
        "deployment_ready": False,
        "generated_at": (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "feature_contract_version": next(iter(feature_contracts), None),
        "label_version": next(iter(label_versions), None),
        "task_contract": {task: {"horizon_days": _reading_horizon(task)} for task in LONG_TERM_TASKS},
        "symbol_count": len(grouped),
        "readings": [grouped[symbol] for symbol in sorted(grouped)],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return target


@dataclass(frozen=True)
class DeepLongTermModelSpec:
    task: str
    architecture: str
    variant: str
    model_ref: str
    evaluation_ref: str
    feature_order_ref: str
    normalizer_ref: str
    model_hash: str
    report_hash: str
    fold_hash: str
    feature_order_hash: str
    normalizer_hash: str
    snapshot_id: str | None
    snapshot_hash: str | None
    dataset_hash: str | None
    window_sessions: int
    feature_contract_version: str
    status: str
    deployment_ready: bool
    label_version: str | None = None


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _semantic_hash(value: object, *, sort_keys: bool = False) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":")).encode()
    return sha256(payload).hexdigest()


_EVALUATION_DETAIL_KEYS = (
    "sample_count",
    "rank_ic",
    "rank_icir",
    "rank_ic_std",
    "rank_ic_observations",
    "risk_rank_ic",
    "risk_rank_ic_std",
    "risk_rank_ic_observations",
    "top_k_mean_excess_return_after_cost",
    "top_bottom_spread_after_cost",
    "risk_top_k_mean_excess_return_after_cost",
    "risk_top_bottom_spread_after_cost",
    "pinball_loss",
    "p50_mae",
    "interval_coverage",
    "max_drawdown",
    "max_drawdown_after_cost",
    "risk_max_drawdown_after_cost",
    "turnover",
    "risk_turnover",
    "capacity",
    "capacity_estimate",
    "risk_capacity_estimate",
    "year_rank_ic",
    "risk_year_rank_ic",
    "industry_rank_ic",
    "risk_industry_rank_ic",
    "regime_metrics",
    "risk_regime_metrics",
    "data_completeness_rank_ic",
    "risk_data_completeness_rank_ic",
)


def _compact_evaluation_metrics(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, object] = {}
    for key in _EVALUATION_DETAIL_KEYS:
        raw = value.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(float(raw)):
            compact[key] = float(raw)
        elif isinstance(raw, dict):
            compact[key] = _compact_metric_mapping(raw)
    return compact


def _compact_metric_mapping(value: dict[object, object]) -> dict[str, object]:
    output: dict[str, object] = {}
    for bucket, metric in value.items():
        if isinstance(metric, (int, float)) and not isinstance(metric, bool) and math.isfinite(float(metric)):
            output[str(bucket)] = float(metric)
        elif isinstance(metric, dict):
            nested = _compact_metric_mapping(metric)
            if nested:
                output[str(bucket)] = nested
    return output


def _evaluation_metric_status(task: str, evaluation: dict[str, Any]) -> dict[str, Any]:
    """Describe which required evaluation fields are actually persisted.

    Older immutable deep-model reports predate the full metric contract.  A
    missing field is therefore surfaced explicitly instead of being silently
    omitted or interpreted as zero.  This metadata is diagnostic only and
    never promotes a model.
    """
    result = evaluation.get("result") if isinstance(evaluation.get("result"), dict) else {}
    holdout = result.get("holdout_metrics") if isinstance(result.get("holdout_metrics"), dict) else {}
    risk = task.startswith("future_max_drawdown_")
    prefix = "risk_" if risk else ""
    required = [
        "pinball_loss", "p50_mae", "interval_coverage",
        f"{prefix}rank_ic", f"{prefix}rank_icir",
        f"{prefix}top_k_mean_excess_return_after_cost",
        f"{prefix}top_bottom_spread_after_cost",
        f"{prefix}max_drawdown_after_cost", f"{prefix}turnover",
        f"{prefix}capacity_estimate", f"{prefix}year_rank_ic",
        f"{prefix}industry_rank_ic", f"{prefix}regime_metrics",
        f"{prefix}data_completeness_rank_ic",
    ]
    status = {
        key: {
            "status": "recorded" if _evaluation_field_recorded(holdout, key) else "not_recorded",
            "missing_reason": None if _evaluation_field_recorded(holdout, key) else (
                "evaluation_report_field_missing_or_null"
            ),
        }
        for key in required
    }
    return {
        "required_count": len(required),
        "recorded_count": sum(item["status"] == "recorded" for item in status.values()),
        "missing_count": sum(item["status"] != "recorded" for item in status.values()),
        "fields": status,
    }


def _evaluation_field_recorded(metrics: dict[str, Any], key: str) -> bool:
    """Treat null/empty diagnostic fields as absent, never as zero evidence."""
    if key not in metrics:
        return False
    value = metrics[key]
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    return isinstance(value, (int, float, str, bool))


def load_deep_long_term_registry_summary(
    *, project_root: Path, registry_path: Path | None = None,
) -> dict[str, Any]:
    """Read-only, UI-safe training details without loading Torch models.

    The inference service remains the authoritative hash-enforcing loader. This
    lighter summary is intended for the collapsed professional view and only
    reads the registry, evaluation JSON and feature-order metadata.
    """
    root = project_root.resolve()
    path = registry_path or (root / "config" / "long_term_deep_model_roster.json")
    base: dict[str, Any] = {
        "schema_version": "long-term-deep-model-summary-v1",
        "status": "unavailable",
        "deployment_ready": False,
        "source_ref": None,
        "source_hash": None,
        "models": [],
        "candidate_models": [],
        "candidate_count": 0,
        "candidate_architectures": [],
        "blocking_reasons": [],
        "artifact_registration_ref": None,
        "artifact_registration_hash": None,
        "artifact_registration_status": None,
    }
    try:
        raw_registry = path.read_bytes()
        payload = json.loads(raw_registry)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        base["blocking_reasons"] = ["model_registry_unreadable"]
        return base
    if not isinstance(payload, dict) or payload.get("schema_version") != "long-term-deep-model-roster-v1":
        base["blocking_reasons"] = ["model_registry_schema_invalid"]
        return base
    models = payload.get("models")
    if not isinstance(models, dict):
        base["blocking_reasons"] = ["model_registry_models_missing"]
        return base
    try:
        source_ref = str(path.resolve().relative_to(root))
    except ValueError:
        base["blocking_reasons"] = ["model_registry_reference_outside_project"]
        return base
    base["source_ref"] = source_ref
    base["source_hash"] = sha256(raw_registry).hexdigest()
    blocking: list[str] = []
    summaries: list[dict[str, Any]] = []
    for task in LONG_TERM_TASKS:
        raw_spec = models.get(task)
        if not isinstance(raw_spec, dict):
            blocking.append(f"model_registry_task_missing:{task}")
            continue
        try:
            evaluation_path = _safe_path(root, str(raw_spec["evaluation_ref"]))
            feature_path = _safe_path(root, str(raw_spec["feature_order_ref"]))
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
            feature_order = json.loads(feature_path.read_text(encoding="utf-8"))
        except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, DeepLongTermArtifactError) as exc:
            blocking.append(f"model_evaluation_unavailable:{task}")
            continue
        if not isinstance(evaluation, dict) or not isinstance(feature_order, list):
            blocking.append(f"model_evaluation_invalid:{task}")
            continue
        result = evaluation.get("result") if isinstance(evaluation.get("result"), dict) else {}
        holdout_metrics = result.get("holdout_metrics") if isinstance(result.get("holdout_metrics"), dict) else {}
        registry_fold_hash = raw_spec.get("fold_hash")
        evaluation_fold_hash = result.get("fold_hash")
        if (
            not isinstance(registry_fold_hash, str)
            or len(registry_fold_hash) != 64
            or any(char not in "0123456789abcdef" for char in registry_fold_hash)
            or evaluation_fold_hash != registry_fold_hash
        ):
            blocking.append(f"model_fold_hash_mismatch:{task}")
        summaries.append({
            "task": task,
            "architecture": raw_spec.get("architecture"),
            "variant": raw_spec.get("variant"),
            "model_version": f"{task}:{raw_spec.get('architecture')}:{raw_spec.get('variant')}",
            "training_symbol_count": evaluation.get("training_symbol_count"),
            "training_date_count": evaluation.get("training_date_count"),
            "training_date_range": evaluation.get("training_date_range"),
            "input_shape": evaluation.get("input_shape"),
            "feature_count": len(feature_order),
            "window_sessions": raw_spec.get("window_sessions"),
            "feature_contract_version": raw_spec.get("feature_contract_version"),
            "label_version": raw_spec.get("label_version") or evaluation.get("label_version") or "not_recorded",
            "data_tier": evaluation.get("data_tier"),
            "historical_visibility_assumption": evaluation.get("historical_visibility_assumption"),
            "snapshot_id": raw_spec.get("snapshot_id"),
            "snapshot_hash": raw_spec.get("snapshot_hash"),
            "dataset_hash": raw_spec.get("dataset_hash"),
            "model_hash": raw_spec.get("model_hash"),
            "report_hash": raw_spec.get("report_hash"),
            "fold_hash": registry_fold_hash,
            "provider": evaluation.get("provider"),
            "shadow_status": evaluation.get("shadow_status"),
            "holdout_metrics": _compact_evaluation_metrics(result.get("holdout_metrics")),
            "stress_metrics": _compact_evaluation_metrics(result.get("stress_metrics")),
            "evaluation_metric_status": _evaluation_metric_status(task, evaluation),
            "turnover": holdout_metrics.get("risk_turnover" if task.startswith("future_max_drawdown_") else "turnover"),
            "capacity_estimate": holdout_metrics.get("risk_capacity_estimate" if task.startswith("future_max_drawdown_") else "capacity_estimate"),
            "capacity_status": (
                "not_estimated_without_volume_impact_model"
                if holdout_metrics.get("risk_capacity_estimate" if task.startswith("future_max_drawdown_") else "capacity_estimate") is None
                else "estimated"
            ),
            "status": "research_only",
            "deployment_ready": False,
        })
    base["models"] = summaries
    run_id = str(payload.get("run_id", ""))
    candidate_bases = [root / "artifacts" / run_id]
    if run_id:
        candidate_bases.append(root / "artifacts" / f"server-run-{run_id}")
    candidate_root = next(
        (base / "deep" / "cn" / "close_confirmed" / "cn_equity_core" for base in candidate_bases if (base / "deep").is_dir()),
        candidate_bases[0] / "deep" / "cn" / "close_confirmed" / "cn_equity_core",
    )
    primary_evaluations = {str(item.get("evaluation_ref")) for item in models.values() if isinstance(item, dict)}
    candidates: list[dict[str, Any]] = []
    if candidate_root.is_dir():
        for evaluation_path in sorted(candidate_root.rglob("sequence_evaluation.json")):
            try:
                evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            task = evaluation.get("task") if isinstance(evaluation, dict) else None
            if task not in LONG_TERM_TASKS or not isinstance(evaluation, dict):
                continue
            result = evaluation.get("result") if isinstance(evaluation.get("result"), dict) else {}
            try:
                relative_ref = evaluation_path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            candidates.append({
                "task": task,
                "architecture": evaluation.get("architecture"),
                "variant": evaluation.get("variant"),
                "evaluation_ref": relative_ref,
                "model_hash": evaluation.get("model_hash"),
                "fold_hash": result.get("fold_hash"),
                "training_symbol_count": evaluation.get("training_symbol_count"),
                "training_date_count": evaluation.get("training_date_count"),
                "training_date_range": evaluation.get("training_date_range"),
                "holdout_metrics": _compact_evaluation_metrics(result.get("holdout_metrics")),
                "evaluation_metric_status": _evaluation_metric_status(task, evaluation),
                "status": evaluation.get("status", "research_only"),
                "deployment_ready": False,
                "is_primary": relative_ref in primary_evaluations,
            })
    base["candidate_models"] = candidates
    base["candidate_count"] = len(candidates)
    base["candidate_architectures"] = sorted({str(item["architecture"]) for item in candidates if item.get("architecture")})
    registration_path = root / "artifacts" / "long_term_model_registry" / "latest.json"
    try:
        registration_raw = registration_path.read_bytes()
        registration = json.loads(registration_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        registration = None
        registration_raw = None
    if isinstance(registration, dict) and registration.get("schema_version") == "long-term-model-artifact-registration-v1":
        base["artifact_registration_ref"] = registration_path.relative_to(root).as_posix()
        base["artifact_registration_hash"] = sha256(registration_raw or b"").hexdigest()
        registration_matches = registration.get("registry_sha256") == base["source_hash"]
        base["artifact_registration_status"] = (
            registration.get("registration_status") if registration_matches else "stale"
        )
        if not registration_matches:
            blocking.append("model_artifact_registration_stale")
    if len(summaries) == len(LONG_TERM_TASKS) and not blocking:
        base["status"] = "available"
    elif summaries:
        base["status"] = "partial"
    base["blocking_reasons"] = sorted(set(blocking))
    return base


def _safe_path(project_root: Path, reference: str) -> Path:
    if not isinstance(reference, str) or not reference:
        raise DeepLongTermArtifactError("artifact_reference_missing")
    candidate = (project_root / reference).resolve()
    root = project_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise DeepLongTermArtifactError(f"artifact_reference_outside_project:{reference}")
    return candidate


def load_deep_long_term_registry(
    *, project_root: Path, registry_path: Path | None = None,
) -> dict[str, DeepLongTermModelSpec]:
    """Load and validate the immutable four-task model roster.

    Missing model files are an explicit error.  Callers can convert that error
    to a neutral ``model readings unavailable`` response at the API boundary.
    """
    path = registry_path or (project_root / "config" / "long_term_deep_model_roster.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeepLongTermArtifactError(f"model_registry_unreadable:{path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "long-term-deep-model-roster-v1":
        raise DeepLongTermArtifactError("model_registry_schema_invalid")
    if payload.get("deployment_ready") is not False or payload.get("status") != "research_only":
        raise DeepLongTermArtifactError("model_registry_activation_boundary_invalid")
    models = payload.get("models")
    if not isinstance(models, dict):
        raise DeepLongTermArtifactError("model_registry_models_missing")
    result: dict[str, DeepLongTermModelSpec] = {}
    for task, raw in models.items():
        if task not in LONG_TERM_TASKS or not isinstance(raw, dict):
            raise DeepLongTermArtifactError(f"model_registry_task_invalid:{task}")
        try:
            spec = DeepLongTermModelSpec(
                task=task,
                architecture=str(raw["architecture"]),
                variant=str(raw["variant"]),
                model_ref=str(raw["model_ref"]),
                evaluation_ref=str(raw["evaluation_ref"]),
                feature_order_ref=str(raw["feature_order_ref"]),
                normalizer_ref=str(raw["normalizer_ref"]),
                model_hash=str(raw["model_hash"]),
                report_hash=str(raw["report_hash"]),
                fold_hash=str(raw["fold_hash"]),
                feature_order_hash=str(raw["feature_order_hash"]),
                normalizer_hash=str(raw["normalizer_hash"]),
                snapshot_id=str(raw["snapshot_id"]) if raw.get("snapshot_id") else None,
                snapshot_hash=str(raw["snapshot_hash"]) if raw.get("snapshot_hash") else None,
                dataset_hash=str(raw["dataset_hash"]) if raw.get("dataset_hash") else None,
                window_sessions=int(raw["window_sessions"]),
                feature_contract_version=str(raw["feature_contract_version"]),
                status=str(raw.get("status", "research_only")),
                deployment_ready=bool(raw.get("deployment_ready", False)),
                label_version=str(raw["label_version"]) if raw.get("label_version") else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DeepLongTermArtifactError(f"model_registry_entry_invalid:{task}") from exc
        if spec.status != "research_only" or spec.deployment_ready:
            raise DeepLongTermArtifactError(f"model_registry_entry_activation_boundary_invalid:{task}")
        model_path = _safe_path(project_root, spec.model_ref)
        evaluation_path = _safe_path(project_root, spec.evaluation_ref)
        feature_path = _safe_path(project_root, spec.feature_order_ref)
        normalizer_path = _safe_path(project_root, spec.normalizer_ref)
        if not all(item.is_file() and item.stat().st_size > 0 for item in (model_path, evaluation_path, feature_path, normalizer_path)):
            raise DeepLongTermArtifactError(f"model_artifact_missing:{task}")
        if _sha256(model_path) != spec.model_hash:
            raise DeepLongTermArtifactError(f"model_hash_mismatch:{task}")
        if _sha256(evaluation_path) != spec.report_hash:
            raise DeepLongTermArtifactError(f"evaluation_hash_mismatch:{task}")
        if len(spec.fold_hash) != 64 or any(char not in "0123456789abcdef" for char in spec.fold_hash):
            raise DeepLongTermArtifactError(f"fold_hash_invalid:{task}")
        try:
            feature_order = json.loads(feature_path.read_text(encoding="utf-8"))
            normalizer = json.loads(normalizer_path.read_text(encoding="utf-8"))
            evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeepLongTermArtifactError(f"model_metadata_invalid:{task}") from exc
        if not isinstance(feature_order, list) or not feature_order or not isinstance(normalizer, dict):
            raise DeepLongTermArtifactError(f"model_metadata_shape_invalid:{task}")
        if _semantic_hash(feature_order) != spec.feature_order_hash:
            raise DeepLongTermArtifactError(f"feature_order_hash_mismatch:{task}")
        if _semantic_hash(normalizer, sort_keys=True) != spec.normalizer_hash:
            raise DeepLongTermArtifactError(f"normalizer_hash_mismatch:{task}")
        if not isinstance(evaluation, dict) or evaluation.get("task") != task:
            raise DeepLongTermArtifactError(f"evaluation_task_mismatch:{task}")
        evaluation_result = evaluation.get("result") if isinstance(evaluation.get("result"), dict) else {}
        if evaluation_result.get("fold_hash") != spec.fold_hash:
            raise DeepLongTermArtifactError(f"fold_hash_mismatch:{task}")
        if evaluation.get("architecture") != spec.architecture or evaluation.get("variant") != spec.variant:
            raise DeepLongTermArtifactError(f"evaluation_model_mismatch:{task}")
        if spec.snapshot_id and evaluation.get("market_snapshot_id") not in {None, spec.snapshot_id}:
            raise DeepLongTermArtifactError(f"evaluation_snapshot_id_mismatch:{task}")
        if spec.snapshot_hash and evaluation.get("market_snapshot_hash") not in {None, spec.snapshot_hash}:
            raise DeepLongTermArtifactError(f"evaluation_snapshot_hash_mismatch:{task}")
        if spec.dataset_hash and evaluation.get("dataset_hash") not in {None, spec.dataset_hash}:
            raise DeepLongTermArtifactError(f"evaluation_dataset_hash_mismatch:{task}")
        if evaluation.get("feature_contract_version") not in {None, spec.feature_contract_version}:
            raise DeepLongTermArtifactError(f"evaluation_feature_contract_mismatch:{task}")
        result[task] = spec
    return result


def build_deep_long_term_artifact_manifest(
    *, project_root: Path, registry_path: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an immutable research-artifact registration manifest.

    Registration is intentionally reference-only: the manifest records the
    existing model/evaluation/feature-order/normalizer files and their hashes;
    it never copies them into a production model directory or changes their
    contents.  If the source evaluation did not persist a training date range,
    that absence is recorded explicitly rather than inferred from a nearby
    snapshot or sample file.
    """
    root = project_root.resolve()
    registry_file = (registry_path or (root / "config" / "long_term_deep_model_roster.json")).resolve()
    specs = load_deep_long_term_registry(project_root=root, registry_path=registry_file)
    try:
        registry_ref = registry_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise DeepLongTermArtifactError("model_registry_reference_outside_project") from exc

    def _date_range(evaluation: dict[str, Any], *, spec: DeepLongTermModelSpec) -> dict[str, Any]:
        candidates = (
            ("training_start_date", "training_end_date"),
            ("date_start", "date_end"),
            ("as_of_start", "as_of_end"),
        )
        for start_key, end_key in candidates:
            start, end = evaluation.get(start_key), evaluation.get(end_key)
            if start and end:
                return {"start": str(start), "end": str(end), "status": "recorded", "missing_reason": None}
        nested = evaluation.get("training_date_range")
        if isinstance(nested, dict) and nested.get("start") and nested.get("end"):
            return {
                "start": str(nested["start"]), "end": str(nested["end"]),
                "status": "recorded", "missing_reason": None,
            }
        # Older deep-run evaluations persisted only the year filter in the
        # immutable run log. Keep that evidence with explicit granularity
        # instead of fabricating day-level dates.
        model_parts = Path(spec.model_ref).parts
        run_root = root / Path(*model_parts[:2]) if len(model_parts) >= 2 and model_parts[0] == "artifacts" else None
        if run_root is not None:
            log = run_root / "deep" / "logs" / f"refine:{spec.task}:{spec.architecture}:{spec.variant}.log"
            if log.is_file():
                try:
                    text = log.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                match = re.search(r"years=\[([^\]]+)\]", text)
                if match:
                    years = sorted({int(value) for value in re.findall(r"\d{4}", match.group(1))})
                    if years:
                        return {
                            "start": str(years[0]), "end": str(years[-1]),
                            "granularity": "year", "exact": False,
                            "status": "recorded", "source_ref": log.relative_to(root).as_posix(),
                            "missing_reason": "source_run_recorded_year_filter_only",
                        }
        return {
            "start": None, "end": None, "granularity": None, "exact": False,
            "status": "not_recorded",
            "missing_reason": "source_evaluation_did_not_record_training_date_range",
        }

    models: list[dict[str, Any]] = []
    for task in LONG_TERM_TASKS:
        spec = specs[task]
        model_path = _safe_path(root, spec.model_ref)
        evaluation_path = _safe_path(root, spec.evaluation_ref)
        feature_path = _safe_path(root, spec.feature_order_ref)
        normalizer_path = _safe_path(root, spec.normalizer_ref)
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        if not isinstance(evaluation, dict):
            raise DeepLongTermArtifactError(f"model_evaluation_invalid:{task}")
        result = evaluation.get("result") if isinstance(evaluation.get("result"), dict) else {}
        models.append({
            "task": task,
            "architecture": spec.architecture,
            "variant": spec.variant,
            "status": "research_only",
            "deployment_ready": False,
            "model_ref": spec.model_ref,
            "evaluation_ref": spec.evaluation_ref,
            "feature_order_ref": spec.feature_order_ref,
            "normalizer_ref": spec.normalizer_ref,
            "model_sha256": _sha256(model_path),
            "evaluation_sha256": _sha256(evaluation_path),
            "feature_order_sha256": _sha256(feature_path),
            "normalizer_sha256": _sha256(normalizer_path),
            "model_hash": spec.model_hash,
            "report_hash": spec.report_hash,
            "feature_order_hash": spec.feature_order_hash,
            "normalizer_hash": spec.normalizer_hash,
            "dataset_hash": spec.dataset_hash,
            "snapshot_id": spec.snapshot_id,
            "snapshot_hash": spec.snapshot_hash,
            "fold_hash": spec.fold_hash,
            "feature_contract_version": spec.feature_contract_version,
            "label_version": spec.label_version or "not_recorded",
            "window_sessions": spec.window_sessions,
            "training_symbol_count": evaluation.get("training_symbol_count"),
            "training_date_count": evaluation.get("training_date_count"),
            "training_date_range": _date_range(evaluation, spec=spec),
            "training_run_id": evaluation.get("training_run_id"),
        })
    return {
        "schema_version": "long-term-model-artifact-registration-v1",
        "registration_status": "registered_research_only",
        "status": "research_only",
        "deployment_ready": False,
        "generated_at": (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "registry_ref": registry_ref,
        "registry_sha256": _sha256(registry_file),
        "reference_only": True,
        "production_copy_created": False,
        "task_count": len(models),
        "tasks": [item["task"] for item in models],
        "models": models,
    }


class DeepLongTermInferenceService:
    """Load four immutable research models and predict quantile readings."""

    def __init__(self, project_root: Path, *, registry_path: Path | None = None):
        self.project_root = project_root.resolve()
        self.registry_path = registry_path
        self._specs: dict[str, DeepLongTermModelSpec] | None = None
        self._runners: dict[str, SequenceTaskRunner] = {}

    @property
    def specs(self) -> dict[str, DeepLongTermModelSpec]:
        if self._specs is None:
            self._specs = load_deep_long_term_registry(
                project_root=self.project_root, registry_path=self.registry_path,
            )
        return self._specs

    def _runner(self, task: str) -> tuple[DeepLongTermModelSpec, SequenceTaskRunner]:
        if task not in LONG_TERM_TASKS:
            raise DeepLongTermArtifactError(f"long_term_task_unsupported:{task}")
        spec = self.specs.get(task)
        if spec is None:
            raise DeepLongTermArtifactError(f"long_term_task_missing_from_registry:{task}")
        if task not in self._runners:
            runner = SequenceTaskRunner.load(_safe_path(self.project_root, spec.model_ref))
            if runner.config.task != task or runner.config.architecture != spec.architecture:
                raise DeepLongTermArtifactError(f"loaded_model_contract_mismatch:{task}")
            if runner.config.window_sessions != spec.window_sessions or _semantic_hash(runner.feature_order) != spec.feature_order_hash:
                raise DeepLongTermArtifactError(f"loaded_model_feature_contract_mismatch:{task}")
            normalizer_path = _safe_path(self.project_root, spec.normalizer_ref)
            try:
                sidecar = json.loads(normalizer_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DeepLongTermArtifactError(f"model_normalizer_unreadable:{task}") from exc
            if not isinstance(sidecar, dict):
                raise DeepLongTermArtifactError(f"model_normalizer_invalid:{task}")
            if set(sidecar) != set(runner.feature_order):
                raise DeepLongTermArtifactError(f"model_normalizer_feature_set_mismatch:{task}")
            for feature in runner.feature_order:
                raw_stats = sidecar.get(feature)
                embedded = runner.stats.get(feature)
                if (
                    not isinstance(raw_stats, (list, tuple)) or len(raw_stats) != 2
                    or embedded is None
                    or not all(math.isfinite(float(value)) for value in raw_stats)
                    or not all(math.isfinite(float(value)) for value in embedded)
                    or not math.isclose(float(raw_stats[0]), float(embedded[0]), rel_tol=1e-9, abs_tol=1e-9)
                    or not math.isclose(float(raw_stats[1]), float(embedded[1]), rel_tol=1e-9, abs_tol=1e-9)
                ):
                    raise DeepLongTermArtifactError(f"model_normalizer_contract_mismatch:{task}:{feature}")
            self._runners[task] = runner
        return spec, self._runners[task]

    def predict(self, task: str, examples: list[SequenceExample]) -> list[dict[str, Any]]:
        spec, runner = self._runner(task)
        if not examples:
            return []
        for example in examples:
            try:
                decision_time = datetime.fromisoformat(example.decision_time.replace("Z", "+00:00"))
                feature_cutoff = datetime.fromisoformat(example.feature_cutoff.replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise DeepLongTermArtifactError(f"sequence_input_time_invalid:{task}:{example.symbol}") from exc
            if (
                decision_time.tzinfo is None or decision_time.utcoffset() is None
                or feature_cutoff.tzinfo is None or feature_cutoff.utcoffset() is None
                or feature_cutoff > decision_time
            ):
                raise DeepLongTermArtifactError(f"sequence_input_pit_invalid:{task}:{example.symbol}")
            if example.data_tier not in {"research_pit", "formal_pit"}:
                raise DeepLongTermArtifactError(f"sequence_input_data_tier_invalid:{task}:{example.symbol}")
            if not example.market_snapshot_id or not example.market_snapshot_hash or not example.sequence_hash:
                raise DeepLongTermArtifactError(f"sequence_input_provenance_missing:{task}:{example.symbol}")
            if list(example.feature_order) != list(runner.feature_order):
                raise DeepLongTermArtifactError(f"sequence_input_feature_order_mismatch:{task}:{example.symbol}")
            try:
                finite_values = all(math.isfinite(float(value)) for row in example.values for value in row)
                has_observed_feature = any(not bool(value) for row in example.missing_mask for value in row)
            except (TypeError, ValueError) as exc:
                raise DeepLongTermArtifactError(f"sequence_input_quality_invalid:{task}:{example.symbol}") from exc
            if not finite_values or not has_observed_feature:
                raise DeepLongTermArtifactError(f"sequence_input_quality_invalid:{task}:{example.symbol}")
        invalid = validate_sequence_examples(
            examples, window_sessions=spec.window_sessions, feature_order=runner.feature_order,
        )
        if invalid:
            raise DeepLongTermArtifactError(f"sequence_input_invalid:{task}:{invalid[0][0]}:{invalid[0][3]}")
        snapshot_pairs = {(item.market_snapshot_id, item.market_snapshot_hash) for item in examples}
        if len(snapshot_pairs) != 1:
            raise DeepLongTermArtifactError(f"sequence_snapshot_mixed:{task}")
        if spec.snapshot_id and next(iter(snapshot_pairs))[0] != spec.snapshot_id:
            raise DeepLongTermArtifactError(f"sequence_snapshot_mismatch:{task}")
        if spec.snapshot_hash and next(iter(snapshot_pairs))[1] != spec.snapshot_hash:
            raise DeepLongTermArtifactError(f"sequence_snapshot_hash_mismatch:{task}")
        raw_predictions = runner.predict_raw(examples)
        if len(raw_predictions) != len(examples) or any(len(row) != 3 for row in raw_predictions):
            raise DeepLongTermArtifactError(f"quantile_output_invalid:{task}")
        observations: list[dict[str, Any]] = []
        for example, row in zip(examples, raw_predictions):
            raw_quantiles = tuple(float(value) for value in row)
            if not all(math.isfinite(value) for value in raw_quantiles):
                raise DeepLongTermArtifactError(f"quantile_value_invalid:{task}:{example.symbol}")
            # The sequence heads are trained independently and may cross.  A
            # monotone projection keeps the public interval semantic (low,
            # middle, high) without inventing a point estimate.
            q10, q50, q90 = sorted(raw_quantiles)
            observations.append({
                "task": task,
                "horizon": f"{int(task.rsplit('_', 1)[-1][:-1])}d",
                "symbol": example.symbol,
                "horizon_days": int(task.rsplit("_", 1)[-1][:-1]),
                "q10": q10,
                "q50": q50,
                "q90": q90,
                "prediction_interval_width": q90 - q10,
                "quantile_projection": "monotone_sort",
                "model": spec.architecture,
                "model_version": f"{spec.task}:{spec.architecture}:{spec.variant}",
                "data_as_of": example.decision_time,
                "snapshot_id": example.market_snapshot_id,
                "snapshot_hash": example.market_snapshot_hash,
                "dataset_hash": spec.dataset_hash,
                "feature_contract_version": spec.feature_contract_version,
                "label_version": example.label_version if example.label_version not in {"", "unknown"} else (spec.label_version or "not_recorded"),
                "artifact_hash": spec.model_hash,
                "status": "research_only",
                "deployment_ready": False,
            })
        return observations

    def predict_all(self, examples_by_task: dict[str, list[SequenceExample]]) -> dict[str, list[dict[str, Any]]]:
        """Predict all four tasks, refusing partial model bundles.

        A partial response is dangerous at the product boundary because it can
        look like a complete long-term view after a caller silently drops a
        missing task.  Keep the permissive per-task ``predict`` method for
        diagnostics, but make the aggregate API fail closed.
        """
        if not isinstance(examples_by_task, dict) or set(examples_by_task) != set(LONG_TERM_TASKS):
            raise DeepLongTermArtifactError("long_term_prediction_tasks_incomplete")
        if any(not isinstance(examples_by_task[task], list) or not examples_by_task[task] for task in LONG_TERM_TASKS):
            raise DeepLongTermArtifactError("long_term_prediction_task_empty")
        return {task: self.predict(task, examples_by_task[task]) for task in LONG_TERM_TASKS}

    def build_latest_examples(
        self,
        samples: list[TrainingSample],
        *,
        as_of: datetime | None = None,
    ) -> dict[str, list[SequenceExample]]:
        """Build one aligned, most-recent 20-session window per symbol.

        The caller supplies rows already read from a frozen PIT sample
        artifact; this method never discovers or reads a mutable data path.
        Each task is built independently because its mature label can have a
        different tail, then only ``(symbol, decision_time)`` keys present in
        all four tasks are retained.  That prevents a mixed-date four-task
        reading from being persisted as one company observation.
        """
        if not samples:
            raise DeepLongTermArtifactError("long_term_sequence_samples_empty")
        snapshots = {(item.market_snapshot_id, item.market_snapshot_hash) for item in samples}
        if len(snapshots) != 1 or not next(iter(snapshots))[0] or not next(iter(snapshots))[1]:
            raise DeepLongTermArtifactError("long_term_sequence_snapshot_mixed_or_missing")
        tiers = {item.data_tier for item in samples}
        if not tiers.issubset({"research_pit", "formal_pit"}):
            raise DeepLongTermArtifactError("long_term_sequence_data_tier_invalid")
        if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
            raise DeepLongTermArtifactError("long_term_sequence_as_of_timezone_missing")
        by_task: dict[str, dict[tuple[str, str], SequenceExample]] = {}
        for task in LONG_TERM_TASKS:
            spec = self.specs.get(task)
            if spec is None:
                raise DeepLongTermArtifactError(f"long_term_task_missing_from_registry:{task}")
            # Use the model's canonical feature contract so examples match the
            # trained width; the runner validates this same order at predict().
            _, runner = self._runner(task)
            examples = build_sequence_examples(
                samples,
                target_name=task,
                window_sessions=spec.window_sessions,
                require_research_pit=True,
                allow_quality_degraded=True,
                require_label=False,
                feature_order=runner.feature_order,
            )
            if as_of is not None:
                examples = [
                    item for item in examples
                    if datetime.fromisoformat(item.decision_time.replace("Z", "+00:00")) <= as_of
                ]
            latest: dict[tuple[str, str], SequenceExample] = {}
            for item in examples:
                key = (item.symbol, item.decision_time)
                previous = latest.get(key)
                if previous is None or item.feature_cutoff > previous.feature_cutoff:
                    latest[key] = item
            if not latest:
                raise DeepLongTermArtifactError(f"long_term_sequence_task_no_mature_window:{task}")
            by_task[task] = latest
        common_keys = set.intersection(*(set(by_task[task]) for task in LONG_TERM_TASKS))
        if not common_keys:
            raise DeepLongTermArtifactError("long_term_sequence_tasks_have_no_aligned_window")
        # Each persisted reading must be a single (symbol, decision_time)
        # observation shared by all four tasks; keeping every common session
        # would emit one reading per session and trip the per-symbol context
        # check in write_long_term_model_readings.  Retain only the latest
        # aligned session per symbol.
        latest_per_symbol: dict[str, tuple[str, str]] = {}
        for sym, dt in common_keys:
            if sym not in latest_per_symbol or dt > latest_per_symbol[sym][1]:
                latest_per_symbol[sym] = (sym, dt)
        ordered_keys = sorted(latest_per_symbol.values(), key=lambda item: (item[0], item[1]))
        return {
            task: [by_task[task][key] for key in ordered_keys]
            for task in LONG_TERM_TASKS
        }

    def predict_latest_from_samples(
        self,
        samples: list[TrainingSample],
        *,
        as_of: datetime | None = None,
        output_path: Path | None = None,
        generated_at: datetime | None = None,
    ) -> Path:
        """Construct aligned latest windows, predict, and persist atomically."""
        examples = self.build_latest_examples(samples, as_of=as_of)
        return self.predict_all_and_persist(
            examples,
            output_path=output_path,
            generated_at=generated_at,
        )

    def predict_all_and_persist(
        self,
        examples_by_task: dict[str, list[SequenceExample]],
        *,
        output_path: Path | None = None,
        generated_at: datetime | None = None,
    ) -> Path:
        """Run all four tasks and atomically persist their grouped readings."""
        readings = self.predict_all(examples_by_task)
        return write_long_term_model_readings(
            self.project_root,
            readings,
            output_path=output_path,
            generated_at=generated_at,
        )
