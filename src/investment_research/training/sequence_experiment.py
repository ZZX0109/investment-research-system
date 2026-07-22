"""Walk-forward orchestration for true sequence challengers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from typing import Any

from investment_research.training.sequence_dataset import SequenceExample
from investment_research.training.sequence_models import SEEDS, SequenceModelConfig, SequenceTaskRunner
from investment_research.training.sequence_calibration import fit_direction_calibrators, fit_risk_calibrator
from investment_research.training.validation import build_walk_forward_folds


@dataclass(frozen=True)
class SequenceExperimentResult:
    task: str
    architecture: str
    window_sessions: int
    fold_hash: str
    seeds: list[int]
    seed_metrics: dict[str, dict[str, float]]
    holdout_metrics: dict[str, float]
    stress_metrics: dict[str, float]
    calibration: dict[str, Any]
    artifact_hashes: dict[str, str]
    status: str = "research_only"
    deployment_ready: bool = False
    final_runner: SequenceTaskRunner | None = field(default=None, repr=False, compare=False)


def split_sequence_examples(examples: list[SequenceExample], *, horizon: int) -> tuple[list[SequenceExample], list, list[SequenceExample], list[SequenceExample], str]:
    if not examples:
        raise ValueError("sequence experiment requires examples")
    dates = sorted({date.fromisoformat(item.decision_time[:10]) for item in examples})
    if len(dates) <= 252:
        raise ValueError("sequence experiment requires more than 252 decision dates")
    holdout_start = dates[-252]
    stress_start = dates[-126]
    development = [item for item in examples if date.fromisoformat(item.decision_time[:10]) < holdout_start and (item.label_end is None or date.fromisoformat(item.label_end[:10]) < holdout_start)]
    holdout = [item for item in examples if date.fromisoformat(item.decision_time[:10]) >= holdout_start]
    stress = [item for item in holdout if date.fromisoformat(item.decision_time[:10]) >= stress_start]
    folds = build_walk_forward_folds(dates=[date.fromisoformat(item.decision_time[:10]) for item in development], train_window_days=504, validation_window_days=126, prediction_horizon_days=horizon, embargo_days=horizon)
    materialized = []
    for fold in folds:
        train = [item for item in development if fold.train_start <= date.fromisoformat(item.decision_time[:10]) <= fold.train_end and (item.label_end is None or date.fromisoformat(item.label_end[:10]) < fold.validation_start)]
        validation = [item for item in development if fold.validation_start <= date.fromisoformat(item.decision_time[:10]) <= fold.validation_end]
        if train and validation:
            materialized.append((fold, train, validation))
    fold_payload = [
        fold.model_dump(mode="json") if hasattr(fold, "model_dump") else fold
        for fold, _train, _validation in materialized
    ]
    fold_hash = sha256(
        json.dumps(fold_payload, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return development, materialized, holdout, stress, fold_hash


def run_sequence_experiment(
    examples: list[SequenceExample],
    *,
    task: str,
    architecture: str,
    window_sessions: int,
    config_overrides: dict[str, Any] | None = None,
    seeds: tuple[int, ...] = SEEDS,
) -> SequenceExperimentResult:
    horizon = 1 if task == "direction_1d" else 5 if task == "direction_5d" else 20
    development, folds, holdout, stress, fold_hash = split_sequence_examples(examples, horizon=horizon)
    if not folds:
        raise ValueError("sequence experiment has no valid purged folds")
    seed_metrics: dict[str, dict[str, float]] = {}
    artifact_hashes: dict[str, str] = {}
    for seed in seeds:
        oof_predictions: list[list[float]] = []
        oof_targets: list[Any] = []
        oof_fold_ids: list[str] = []
        for fold, train, validation in folds:
            config = SequenceModelConfig(architecture=architecture, task=task, window_sessions=window_sessions, **(config_overrides or {}))
            runner = SequenceTaskRunner(config, seed=seed).fit(train, validation)
            oof_predictions.extend(runner.predict_raw(validation))
            oof_targets.extend([item.target for item in validation])
            oof_fold_ids.extend([fold.fold_id] * len(validation))
        oof_regimes = [item.market_regime for fold, _train, validation in folds for item in validation]
        seed_metrics[str(seed)] = evaluate_predictions(
            task, oof_predictions, oof_targets, regimes=oof_regimes
        )
        artifact_hashes[str(seed)] = sha256(json.dumps(seed_metrics[str(seed)], sort_keys=True).encode()).hexdigest()
    # Final model is trained only on development and evaluated once on the
    # immutable holdout; no holdout values affect selection or calibration.
    final_config = SequenceModelConfig(architecture=architecture, task=task, window_sessions=window_sessions, **(config_overrides or {}))
    # Early stopping is allowed to use only a development tail.  The final
    # 252-session holdout (including its 126-session stress slice) is never
    # passed to ``fit`` and is evaluated exactly once below.
    development_dates = sorted({date.fromisoformat(item.decision_time[:10]) for item in development})
    dev_validation_start = development_dates[-min(126, len(development_dates))]
    final_validation = [item for item in development if date.fromisoformat(item.decision_time[:10]) >= dev_validation_start]
    final_train = [
        item for item in development
        if date.fromisoformat(item.decision_time[:10]) < dev_validation_start
        and (item.label_end is None or date.fromisoformat(item.label_end[:10]) < dev_validation_start)
    ]
    final_runner = SequenceTaskRunner(final_config, seed=seeds[0]).fit(final_train or development, final_validation or None)
    holdout_metrics = evaluate_predictions(
        task, final_runner.predict_raw(holdout), [item.target for item in holdout],
        regimes=[item.market_regime for item in holdout],
    )
    stress_metrics = evaluate_predictions(
        task, final_runner.predict_raw(stress), [item.target for item in stress],
        regimes=[item.market_regime for item in stress],
    )
    artifact_hashes["final"] = final_runner.artifact_hash()
    calibration: dict[str, Any] = {"source": "time_oof_only", "status": "unavailable"}
    try:
        if task.startswith("direction_"):
            calibrators = fit_direction_calibrators([{label: float(value) for label, value in zip(("up", "down", "flat"), row)} for row in oof_predictions], [str(value) for value in oof_targets], oof_fold_ids, training_fold_ids=["training_window"])
            calibration = {"source": "time_oof_only", "status": "fitted", "methods": {key: value.method.value for key, value in calibrators.items()}}
        elif task == "drawdown_20d":
            calibrator = fit_risk_calibrator([float(row[0]) for row in oof_predictions], [int(float(value) <= -0.08) for value in oof_targets], oof_fold_ids, training_fold_ids=["training_window"])
            calibration = {"source": "time_oof_only", "status": "fitted", "method": calibrator.method.value}
    except ValueError as exc:
        calibration = {"source": "time_oof_only", "status": "blocked", "reason": str(exc)}
    return SequenceExperimentResult(task=task, architecture=architecture, window_sessions=window_sessions, fold_hash=fold_hash, seeds=list(seeds), seed_metrics=seed_metrics, holdout_metrics=holdout_metrics, stress_metrics=stress_metrics, calibration=calibration, artifact_hashes=artifact_hashes, final_runner=final_runner)


def evaluate_predictions(
    task: str, predictions: list[list[float]], targets: list[Any],
    *, regimes: list[str] | None = None,
) -> dict[str, Any]:
    if not predictions or not targets:
        return {"sample_count": 0.0}
    import numpy as np
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, log_loss, mean_absolute_error, roc_auc_score
    if task.startswith("direction_"):
        # Torch softmax is numerically normalized, but sklearn's strict
        # probability validation can still reject tiny floating-point drift.
        # Normalize only for evaluation; the saved model and raw predictions
        # remain untouched.
        normalized = []
        for row in predictions:
            values = np.asarray(row, dtype=float)
            total = float(values.sum())
            normalized.append((values / total if total > 0 else np.full(3, 1.0 / 3.0)).tolist())
        predictions = normalized
        actual = [("up", "down", "flat").index(str(value)) for value in targets]
        predicted = [int(np.argmax(row)) for row in predictions]
        balanced = (
            float(balanced_accuracy_score(actual, predicted))
            if len(set(actual)) > 1
            else float(accuracy_score(actual, predicted))
        )
        result = {"sample_count": float(len(actual)), "macro_f1": float(f1_score(actual, predicted, labels=[0, 1, 2], average="macro", zero_division=0)), "balanced_accuracy": balanced, "accuracy": float(accuracy_score(actual, predicted)), "log_loss": float(log_loss(actual, predictions, labels=[0, 1, 2]))}
        try:
            result["macro_auroc"] = float(roc_auc_score(actual, predictions, multi_class="ovr", average="macro"))
        except ValueError:
            result["macro_auroc"] = 0.0
        return _with_regime_metrics(result, task, predictions, targets, regimes)
    if task == "return_20d":
        values = np.asarray(targets, dtype=float)
        median = np.asarray([row[1] for row in predictions])
        result = {"sample_count": float(len(values)), "p50_mae": float(mean_absolute_error(values, median)), "pinball_loss": float(np.mean(np.maximum((values[:, None] - np.asarray(predictions)) * np.array([0.1, 0.5, 0.9]), (np.asarray(predictions) - values[:, None]) * np.array([0.9, 0.5, 0.1])))), "interval_coverage": float(np.mean((values >= np.asarray(predictions)[:, 0]) & (values <= np.asarray(predictions)[:, 2])))}
        return _with_regime_metrics(result, task, predictions, targets, regimes)
    actual = np.asarray(targets, dtype=float)
    probabilities = np.asarray(predictions).reshape(-1)
    labels = (actual <= -0.08).astype(int)
    result = {"sample_count": float(len(actual)), "brier": float(np.mean((probabilities - labels) ** 2)), "mean_probability": float(np.mean(probabilities))}
    return _with_regime_metrics(result, task, predictions, targets, regimes)


def _with_regime_metrics(
    result: dict[str, Any], task: str, predictions: list[list[float]],
    targets: list[Any], regimes: list[str] | None,
) -> dict[str, Any]:
    if not regimes or len(regimes) != len(targets):
        return result
    grouped: dict[str, dict[str, Any]] = {}
    for regime in sorted(set(regimes)):
        indexes = [index for index, value in enumerate(regimes) if value == regime]
        if not indexes:
            continue
        grouped[regime] = evaluate_predictions(
            task,
            [predictions[index] for index in indexes],
            [targets[index] for index in indexes],
        )
    return {**result, "regime_metrics": grouped}
