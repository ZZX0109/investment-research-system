"""Walk-forward orchestration for true sequence challengers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
from typing import Any

from investment_research.training.sequence_dataset import SequenceExample, SequenceShapeError, validate_sequence_examples
from investment_research.training.sequence_models import QUANTILE_TASKS, SEEDS, SequenceModelConfig, SequenceTaskRunner
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
    horizon = _task_horizon(task)
    invalid = validate_sequence_examples(examples)
    if invalid:
        ratio = len(invalid) / max(1, len(examples))
        raise SequenceShapeError(
            f"sequence_shape_mismatch: {len(invalid)}/{len(examples)} examples invalid "
            f"(ratio={ratio:.3f}): first={invalid[0]}"
        )
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
        oof_dates = [item.decision_time[:10] for fold, _train, validation in folds for item in validation]
        oof_completeness = [_sequence_completeness(item) for fold, _train, validation in folds for item in validation]
        seed_metrics[str(seed)] = evaluate_predictions(
            task, oof_predictions, oof_targets, regimes=oof_regimes, decision_dates=oof_dates,
            industry_keys=[item.industry_key for fold, _train, validation in folds for item in validation],
            data_completeness=oof_completeness,
            symbols=[item.symbol for fold, _train, validation in folds for item in validation],
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
        decision_dates=[item.decision_time[:10] for item in holdout],
        industry_keys=[item.industry_key for item in holdout],
        data_completeness=[_sequence_completeness(item) for item in holdout],
        symbols=[item.symbol for item in holdout],
    )
    stress_metrics = evaluate_predictions(
        task, final_runner.predict_raw(stress), [item.target for item in stress],
        regimes=[item.market_regime for item in stress],
        decision_dates=[item.decision_time[:10] for item in stress],
        industry_keys=[item.industry_key for item in stress],
        data_completeness=[_sequence_completeness(item) for item in stress],
        symbols=[item.symbol for item in stress],
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
    decision_dates: list[str] | None = None,
    industry_keys: list[str | None] | None = None,
    data_completeness: list[float] | None = None,
    symbols: list[str] | None = None,
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
    if task in QUANTILE_TASKS:
        values = np.asarray(targets, dtype=float)
        median = np.asarray([row[1] for row in predictions])
        result = {"sample_count": float(len(values)), "p50_mae": float(mean_absolute_error(values, median)), "pinball_loss": float(np.mean(np.maximum((values[:, None] - np.asarray(predictions)) * np.array([0.1, 0.5, 0.9]), (np.asarray(predictions) - values[:, None]) * np.array([0.9, 0.5, 0.1])))), "interval_coverage": float(np.mean((values >= np.asarray(predictions)[:, 0]) & (values <= np.asarray(predictions)[:, 2])))}
        if task.startswith("excess_return_"):
            result.update(_cross_sectional_metrics(median, values, decision_dates, industry_keys=industry_keys, data_completeness=data_completeness, symbols=symbols))
        elif task.startswith("future_max_drawdown_"):
            risk = _cross_sectional_metrics(-median, -values, decision_dates, industry_keys=industry_keys, data_completeness=data_completeness, symbols=symbols)
            result.update({f"risk_{key}": value for key, value in risk.items()})
        return _with_regime_metrics(result, task, predictions, targets, regimes, symbols=symbols)
    actual = np.asarray(targets, dtype=float)
    probabilities = np.asarray(predictions).reshape(-1)
    labels = (actual <= -0.08).astype(int)
    result = {"sample_count": float(len(actual)), "brier": float(np.mean((probabilities - labels) ** 2)), "mean_probability": float(np.mean(probabilities))}
    return _with_regime_metrics(result, task, predictions, targets, regimes)


def _task_horizon(task: str) -> int:
    if task == "direction_1d":
        return 1
    if task in {"direction_5d", "excess_return_5d"}:
        return 5
    if task.endswith("120d"):
        return 120
    if task.endswith("240d"):
        return 240
    return 20


def _cross_sectional_metrics(
    scores: Any, targets: Any, decision_dates: list[str] | None,
    *, industry_keys: list[str | None] | None = None,
    data_completeness: list[float] | None = None,
    symbols: list[str] | None = None,
    top_fraction: float = 0.10, round_trip_cost: float = 0.0021,
) -> dict[str, float]:
    """Evaluate ranking quality by decision date, never across time."""
    import numpy as np

    if decision_dates is None or len(decision_dates) != len(targets):
        return {
            "rank_ic": 0.0,
            "rank_icir": 0.0,
            "rank_ic_observations": 0.0,
            "turnover": None,
            "max_drawdown_after_cost": None,
            "capacity_estimate": None,
            "year_rank_ic": {},
            "industry_rank_ic": {},
            "data_completeness_rank_ic": {},
            "data_completeness_sample_counts": {},
        }
    scores = np.asarray(scores, dtype=float)
    targets = np.asarray(targets, dtype=float)
    grouped: dict[str, list[int]] = {}
    for index, day in enumerate(decision_dates):
        grouped.setdefault(day, []).append(index)
    ics: list[float] = []
    day_ics: dict[str, float] = {}
    top_returns: list[float] = []
    spreads: list[float] = []
    turnovers: list[float] = []
    previous_symbols: set[str] | None = None
    industry_ics: dict[str, list[float]] = {}
    completeness_ics: dict[str, list[float]] = {}
    completeness_counts: dict[str, int] = {}
    for day, indexes in grouped.items():
        if len(indexes) < 5:
            continue
        predicted = scores[indexes]
        actual = targets[indexes]
        pred_rank = np.argsort(np.argsort(predicted)).astype(float)
        actual_rank = np.argsort(np.argsort(actual)).astype(float)
        pred_rank -= pred_rank.mean()
        actual_rank -= actual_rank.mean()
        denominator = float(np.sqrt(np.dot(pred_rank, pred_rank) * np.dot(actual_rank, actual_rank)))
        if denominator > 0:
            day_ic = float(np.dot(pred_rank, actual_rank) / denominator)
            ics.append(day_ic)
            day_ics[str(day)] = day_ic
        if industry_keys is not None and len(industry_keys) == len(targets):
            by_industry: dict[str, list[int]] = {}
            for index in indexes:
                by_industry.setdefault(industry_keys[index] or "unknown", []).append(index)
            for industry, industry_indexes in by_industry.items():
                if len(industry_indexes) < 5:
                    continue
                industry_scores = scores[industry_indexes]
                industry_targets = targets[industry_indexes]
                score_rank = np.argsort(np.argsort(industry_scores)).astype(float)
                target_rank = np.argsort(np.argsort(industry_targets)).astype(float)
                score_rank -= score_rank.mean()
                target_rank -= target_rank.mean()
                industry_denominator = float(np.sqrt(np.dot(score_rank, score_rank) * np.dot(target_rank, target_rank)))
                if industry_denominator > 0:
                    industry_ics.setdefault(industry, []).append(
                        float(np.dot(score_rank, target_rank) / industry_denominator)
                    )
        if data_completeness is not None and len(data_completeness) == len(targets):
            by_completeness: dict[str, list[int]] = {}
            for index in indexes:
                bucket = _completeness_bucket(float(data_completeness[index]))
                by_completeness.setdefault(bucket, []).append(index)
                completeness_counts[bucket] = completeness_counts.get(bucket, 0) + 1
            for bucket, bucket_indexes in by_completeness.items():
                if len(bucket_indexes) < 5:
                    continue
                bucket_scores = scores[bucket_indexes]
                bucket_targets = targets[bucket_indexes]
                score_rank = np.argsort(np.argsort(bucket_scores)).astype(float)
                target_rank = np.argsort(np.argsort(bucket_targets)).astype(float)
                score_rank -= score_rank.mean()
                target_rank -= target_rank.mean()
                denominator = float(np.sqrt(np.dot(score_rank, score_rank) * np.dot(target_rank, target_rank)))
                if denominator > 0:
                    completeness_ics.setdefault(bucket, []).append(
                        float(np.dot(score_rank, target_rank) / denominator)
                    )
        k = max(1, int(np.ceil(len(indexes) * top_fraction)))
        order = np.argsort(predicted)
        top_indexes = [indexes[position] for position in order[-k:]]
        top_returns.append(float(np.mean(actual[order[-k:]])))
        spreads.append(float(np.mean(actual[order[-k:]]) - np.mean(actual[order[:k]])))
        if symbols is not None and len(symbols) == len(targets):
            current_symbols = {str(symbols[index]) for index in top_indexes}
            turnovers.append(
                1.0 if previous_symbols is None
                else 1.0 - len(current_symbols & previous_symbols) / max(1, k)
            )
            previous_symbols = current_symbols
    if not ics:
        return {
            "rank_ic": 0.0,
            "rank_icir": 0.0,
            "rank_ic_observations": 0.0,
            "turnover": float(np.mean(turnovers)) if turnovers else None,
            "max_drawdown_after_cost": None,
            "capacity_estimate": None,
            "year_rank_ic": {},
            "industry_rank_ic": {},
            "data_completeness_rank_ic": {},
            "data_completeness_sample_counts": {},
        }
    top_mean = float(np.mean(top_returns))
    rank_ic_mean = float(np.mean(ics))
    rank_ic_std = float(np.std(ics))
    rank_icir = rank_ic_mean / rank_ic_std if rank_ic_std > 1e-12 else 0.0
    net_top_returns = [value - round_trip_cost for value in top_returns]
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in net_top_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    by_year: dict[str, list[float]] = {}
    for day, value in day_ics.items():
        by_year.setdefault(day[:4], []).append(value)
    return {
        "rank_ic": rank_ic_mean,
        "rank_ic_std": rank_ic_std,
        "rank_icir": rank_icir,
        "rank_ic_observations": float(len(ics)),
        "top_k_fraction": top_fraction,
        "top_k_mean_excess_return": top_mean,
        "top_k_mean_excess_return_after_cost": top_mean - round_trip_cost,
        "top_bottom_spread": float(np.mean(spreads)),
        "top_bottom_spread_after_cost": float(np.mean(spreads) - round_trip_cost),
        "round_trip_cost_assumption": round_trip_cost,
        "turnover": float(np.mean(turnovers)) if turnovers else None,
        "max_drawdown_after_cost": float(max_drawdown),
        "capacity_estimate": None,
        "year_rank_ic": {year: float(np.mean(values)) for year, values in sorted(by_year.items())},
        "industry_rank_ic": {industry: float(np.mean(values)) for industry, values in sorted(industry_ics.items())},
        "data_completeness_rank_ic": {
            bucket: float(np.mean(values)) for bucket, values in sorted(completeness_ics.items())
        },
        "data_completeness_sample_counts": dict(sorted(completeness_counts.items())),
    }


def _completeness_bucket(value: float) -> str:
    value = max(0.0, min(1.0, value))
    if value < 0.95:
        return "coverage_below_95%"
    if value < 0.98:
        return "coverage_95_to_98%"
    return "coverage_at_least_98%"


def _sequence_completeness(example: SequenceExample) -> float:
    try:
        return float(example.data_quality_mask[-1][1])
    except (IndexError, TypeError, ValueError):
        return 0.0


def _with_regime_metrics(
    result: dict[str, Any], task: str, predictions: list[list[float]],
    targets: list[Any], regimes: list[str] | None,
    *, symbols: list[str] | None = None,
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
            symbols=([symbols[index] for index in indexes] if symbols is not None else None),
        )
    # Risk tasks use a namespaced contract so the evaluation manifest cannot
    # accidentally treat drawdown-state metrics as return-task metrics.
    key = "risk_regime_metrics" if task.startswith("future_max_drawdown_") else "regime_metrics"
    return {**result, key: grouped}
