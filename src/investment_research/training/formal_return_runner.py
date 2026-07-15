from __future__ import annotations

from dataclasses import dataclass

from investment_research.training.formal_training import (
    FinalHoldoutLedger,
    FormalScopeTrainingPlan,
    RETURN_CANDIDATES,
    require_candidate_dependencies,
)
from investment_research.training.models import TrainingSample
from investment_research.training.research_evaluation import REGIMES, classify_market_regime


QUANTILES = (0.1, 0.5, 0.9)


@dataclass(frozen=True)
class ReturnCandidateResult:
    name: str
    quantiles: list[tuple[float, float, float]]
    targets: list[float]
    mean_pinball_loss: float
    interval_coverage: float
    p50_mae: float
    direction_accuracy: float
    spearman_ic: float
    regime_metrics: dict[str, dict[str, float]]
    fold_hash: str


@dataclass(frozen=True)
class FormalReturnTrainingResult:
    scope_id: str
    fold_hash: str
    candidates: list[ReturnCandidateResult]
    selected_candidate: str
    holdout_quantiles: list[tuple[float, float, float]]
    holdout_targets: list[float]
    stress_quantiles: list[tuple[float, float, float]]
    stress_targets: list[float]


class FormalReturnTrainingRunner:
    """Independent 20-day P10/P50/P90 runner from PIT return labels."""

    def run(self, *, samples, market, decision_context, dataset_hash, holdout_ledger):
        require_candidate_dependencies("return_20d")
        plan = FormalScopeTrainingPlan(
            samples, market=market, decision_context=decision_context,
            task="return_20d", prediction_horizon_sessions=20,
        )
        holdout, folds, fold_hash = plan.build()
        if not folds:
            raise ValueError("return scope has no valid purged folds")
        features = sorted({key for sample in holdout.development for key in sample.features})
        results = []
        values = {}
        targets = None
        for name in RETURN_CANDIDATES[:-1]:
            quantiles, actual, regimes = self._oof(name, folds, features)
            result = _metrics(name, quantiles, actual, fold_hash, regimes=regimes)
            results.append(result)
            values[name] = quantiles
            targets = actual
        assert targets is not None
        ensemble = _ensemble(values)
        results.append(_metrics("time-oof-weighted-ensemble", ensemble, targets, fold_hash, regimes=regimes))
        selected = min(
            (item for item in results if item.name != "time-oof-weighted-ensemble"),
            key=lambda item: item.mean_pinball_loss,
        )
        holdout_ledger.claim(scope_id=plan.scope_id, dataset_hash=dataset_hash, fold_hash=fold_hash)
        final_quantiles = self._fit_predict(selected.name, holdout.development, holdout.holdout_12m, features)
        stress_quantiles = self._fit_predict(
            selected.name, holdout.development, holdout.stress_6m, features
        )
        return FormalReturnTrainingResult(
            scope_id=plan.scope_id, fold_hash=fold_hash, candidates=results,
            selected_candidate=selected.name, holdout_quantiles=final_quantiles,
            holdout_targets=[_target(item) for item in holdout.holdout_12m],
            stress_quantiles=stress_quantiles,
            stress_targets=[_target(item) for item in holdout.stress_6m],
        )

    def _oof(self, name, folds, features):
        quantiles, targets, regimes = [], [], []
        for fold in folds:
            quantiles.extend(self._fit_predict(name, fold.train, fold.validation, features))
            targets.extend(_target(item) for item in fold.validation)
            regimes.extend(classify_market_regime(item) for item in fold.validation)
        return quantiles, targets, regimes

    def _fit_predict(self, name, train, evaluate, features):
        targets = [_target(item) for item in train]
        if name == "historical-distribution":
            values = tuple(_quantile(targets, quantile) for quantile in QUANTILES)
            return [values] * len(evaluate)
        matrix = [_vector(item, features) for item in train]
        evaluation = [_vector(item, features) for item in evaluate]
        predictions = []
        for quantile in QUANTILES:
            estimator = _estimator(name, quantile)
            estimator.fit(matrix, targets)
            predictions.append([float(value) for value in estimator.predict(evaluation)])
        return [tuple(sorted(values)) for values in zip(*predictions)]


def _estimator(name, quantile):
    if name == "linear-quantile":
        from sklearn.linear_model import QuantileRegressor
        return QuantileRegressor(quantile=quantile, alpha=0.01, solver="highs")
    if name == "lightgbm-quantile":
        import lightgbm as lgb
        return lgb.LGBMRegressor(objective="quantile", alpha=quantile, n_estimators=200, learning_rate=0.05, random_state=42, verbose=-1)
    if name == "quantile-random-forest":
        return _QuantileRandomForest(quantile=quantile)
    if name == "xgboost-quantile":
        import xgboost as xgb
        return xgb.XGBRegressor(
            objective="reg:quantileerror", quantile_alpha=quantile,
            n_estimators=200, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=0, n_jobs=1,
        )
    raise ValueError(f"unsupported return candidate: {name}")


def _target(sample):
    value = sample.labels.future_return_20d
    if value is None:
        value = sample.labels.future_return_20d_from_open
    if value is None:
        raise ValueError("return task sample lacks future_return_20d")
    return float(value)


def _vector(sample, features):
    return [float(sample.features.get(name, 0.0)) for name in features]


def _quantile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _metrics(name, quantiles, targets, fold_hash, *, regimes=None):
    losses = [
        sum(_pinball(target, predicted[index], quantile) for target, predicted in zip(targets, quantiles)) / len(targets)
        for index, quantile in enumerate(QUANTILES)
    ]
    coverage = sum(predicted[0] <= target <= predicted[2] for target, predicted in zip(targets, quantiles)) / len(targets)
    p50 = [row[1] for row in quantiles]
    mae = sum(abs(actual - predicted) for actual, predicted in zip(targets, p50)) / len(targets)
    direction_accuracy = sum((actual >= 0) == (predicted >= 0) for actual, predicted in zip(targets, p50)) / len(targets)
    from scipy.stats import spearmanr
    correlation = spearmanr(targets, p50).statistic
    regime_metrics = {}
    if regimes:
        for regime in REGIMES:
            indexes = [index for index, value in enumerate(regimes) if value == regime]
            if not indexes:
                continue
            group_quantiles = [quantiles[index] for index in indexes]
            group_targets = [targets[index] for index in indexes]
            group_losses = [
                sum(_pinball(target, prediction[q], quantile) for target, prediction in zip(group_targets, group_quantiles)) / len(group_targets)
                for q, quantile in enumerate(QUANTILES)
            ]
            regime_metrics[regime] = {
                "sample_count": float(len(indexes)),
                "mean_pinball_loss": sum(group_losses) / len(group_losses),
                "interval_coverage": sum(row[0] <= target <= row[2] for target, row in zip(group_targets, group_quantiles)) / len(group_targets),
            }
    return ReturnCandidateResult(
        name, quantiles, targets, sum(losses) / len(losses), coverage,
        mae, direction_accuracy, 0.0 if correlation != correlation else float(correlation),
        regime_metrics, fold_hash,
    )


def _pinball(actual, prediction, quantile):
    residual = actual - prediction
    return max(quantile * residual, (quantile - 1) * residual)


def _ensemble(values):
    count = len(values)
    return [
        tuple(sum(rows[index][q] for rows in values.values()) / count for q in range(3))
        for index in range(len(next(iter(values.values()))))
    ]


class _QuantileRandomForest:
    def __init__(self, *, quantile: float) -> None:
        from sklearn.ensemble import RandomForestRegressor
        self.quantile = quantile
        self.model = RandomForestRegressor(
            n_estimators=200, max_depth=8, min_samples_leaf=3,
            random_state=42, n_jobs=1,
        )

    def fit(self, values, targets):
        self.model.fit(values, targets)
        return self

    def predict(self, values):
        import numpy as np
        tree_predictions = np.asarray([tree.predict(values) for tree in self.model.estimators_])
        return np.quantile(tree_predictions, self.quantile, axis=0)
