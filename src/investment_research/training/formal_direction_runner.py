from __future__ import annotations

from dataclasses import dataclass

from investment_research.training.calibration import CalibrationMethod, TimeOutOfFoldCalibrator
from investment_research.training.formal_training import (
    DIRECTION_CANDIDATES,
    FinalHoldoutLedger,
    FormalScopeTrainingPlan,
    balanced_panel_fit_samples,
    require_candidate_dependencies,
)
from investment_research.training.models import TrainingSample
from investment_research.training.numeric_safety import guarded_model_math, require_finite
from investment_research.training.research_evaluation import REGIMES, classify_market_regime_groups, fit_regime_thresholds, regime_matches
from investment_research.training.tabular_preprocessing import estimator_pipeline, sample_matrix


CLASSES = ("up", "down", "flat")


@dataclass(frozen=True)
class DirectionCandidateResult:
    name: str
    raw_probabilities: list[dict[str, float]]
    probabilities: list[dict[str, float]]
    labels: list[str]
    macro_f1: float
    balanced_accuracy: float
    log_loss: float
    ece: float
    macro_auroc: float | None
    macro_pr_auc: float | None
    regime_metrics: dict[str, dict[str, float]]
    fold_hash: str


@dataclass(frozen=True)
class FormalDirectionTrainingResult:
    scope_id: str
    fold_hash: str
    horizon: int
    label_multiplier: float
    candidates: list[DirectionCandidateResult]
    selected_candidate: str
    holdout_probabilities: list[dict[str, float]]
    holdout_labels: list[str]
    stress_probabilities: list[dict[str, float]]
    stress_labels: list[str]


class FormalDirectionTrainingRunner:
    """Independent 1/5-day direction runner; never derives labels from risk."""

    def run(
        self,
        *,
        samples: list[TrainingSample],
        market: str,
        decision_context: str,
        horizon: int,
        dataset_hash: str,
        holdout_ledger: FinalHoldoutLedger,
    ) -> FormalDirectionTrainingResult:
        task = f"direction_{horizon}d"
        require_candidate_dependencies(task)
        plan = FormalScopeTrainingPlan(
            samples, market=market, decision_context=decision_context, task=task,
            prediction_horizon_sessions=horizon,
        )
        holdout, folds, fold_hash = plan.build()
        if not folds:
            raise ValueError("direction scope has no valid purged folds")
        label_multiplier = _select_label_multiplier(folds, horizon)
        features = sorted({name for sample in holdout.development for name in sample.features})
        results: list[DirectionCandidateResult] = []
        raw_by_candidate: dict[str, list[dict[str, float]]] = {}
        labels: list[str] | None = None
        oof_fold_ids: list[str] | None = None
        for name in DIRECTION_CANDIDATES[:-1]:
            probabilities, actual, candidate_fold_ids, regimes = self._oof(
                name, folds, features, horizon, label_multiplier
            )
            calibrated = _calibrate_multiclass(
                probabilities, actual, apply_probabilities=probabilities,
                prediction_fold_ids=candidate_fold_ids,
            )
            result = _metrics(name, probabilities, calibrated, actual, fold_hash, regimes=regimes)
            results.append(result)
            raw_by_candidate[name] = probabilities
            labels = actual
            oof_fold_ids = candidate_fold_ids
        assert labels is not None and oof_fold_ids is not None
        ensemble_raw = _ensemble(raw_by_candidate, labels)
        ensemble = _calibrate_multiclass(
            ensemble_raw, labels, apply_probabilities=ensemble_raw,
            prediction_fold_ids=oof_fold_ids,
        )
        results.append(_metrics("time-oof-weighted-ensemble", ensemble_raw, ensemble, labels, fold_hash, regimes=regimes))
        selected = min(
            (item for item in results if item.name != "time-oof-weighted-ensemble"),
            key=lambda item: item.log_loss,
        )
        holdout_ledger.claim(scope_id=plan.scope_id, dataset_hash=dataset_hash, fold_hash=fold_hash)
        raw_holdout = self._fit_predict(
            selected.name, holdout.development, holdout.holdout_12m, features, horizon,
            label_multiplier,
        )
        # Calibrators are fit only on time-OOF development predictions.
        selected_oof = next(item for item in results if item.name == selected.name)
        calibrated_holdout = _calibrate_multiclass(
            selected_oof.raw_probabilities,
            selected_oof.labels,
            apply_probabilities=raw_holdout,
            prediction_fold_ids=oof_fold_ids,
        )
        raw_stress = self._fit_predict(
            selected.name, holdout.development, holdout.stress_6m, features, horizon,
            label_multiplier,
        )
        calibrated_stress = _calibrate_multiclass(
            selected_oof.raw_probabilities,
            selected_oof.labels,
            apply_probabilities=raw_stress,
            prediction_fold_ids=oof_fold_ids,
        )
        return FormalDirectionTrainingResult(
            scope_id=plan.scope_id, fold_hash=fold_hash, horizon=horizon,
            label_multiplier=label_multiplier,
            candidates=results, selected_candidate=selected.name,
            holdout_probabilities=calibrated_holdout,
            holdout_labels=[_direction(item, horizon, label_multiplier) for item in holdout.holdout_12m],
            stress_probabilities=calibrated_stress,
            stress_labels=[_direction(item, horizon, label_multiplier) for item in holdout.stress_6m],
        )

    def _oof(self, name, folds, features, horizon, label_multiplier=0.5):
        probabilities: list[dict[str, float]] = []
        labels: list[str] = []
        fold_ids: list[str] = []
        regimes: list[str] = []
        for fold in folds:
            thresholds = fit_regime_thresholds(fold.train)
            probabilities.extend(self._fit_predict(
                name, fold.train, fold.validation, features, horizon, label_multiplier
            ))
            labels.extend(_direction(sample, horizon, label_multiplier) for sample in fold.validation)
            fold_ids.extend([fold.fold.fold_id] * len(fold.validation))
            regimes.extend(classify_market_regime_groups(sample, thresholds) for sample in fold.validation)
        return probabilities, labels, fold_ids, regimes

    def _fit_predict(self, name, train, evaluate, features, horizon, label_multiplier=0.5):
        fit_train = balanced_panel_fit_samples(train)
        labels = [_direction(item, horizon, label_multiplier) for item in fit_train]
        if name == "constant-class":
            return [_frequencies(labels)] * len(evaluate)
        if name == "random":
            return [{key: 1 / 3 for key in CLASSES}] * len(evaluate)
        if name in {"index-direction", "momentum"}:
            source = "benchmark_ret_20d" if name == "index-direction" else "ret_5d"
            return [_heuristic(sample.features.get(source, 0.0)) for sample in evaluate]
        estimator = _estimator(name)
        matrix = _matrix(fit_train, features)
        evaluation = _matrix(evaluate, features)
        if name.startswith("xgboost"):
            encoded = [_class_index(label) for label in labels]
            with guarded_model_math():
                estimator.fit(matrix, encoded)
                values = estimator.predict_proba(evaluation)
            require_finite(values, stage=f"direction:{name}")
            classes = [CLASSES[int(value)] for value in estimator.classes_]
            return [_map_probabilities(classes, row) for row in values]
        with guarded_model_math():
            estimator.fit(matrix, labels)
            values = estimator.predict_proba(evaluation)
        require_finite(values, stage=f"direction:{name}")
        return [_map_probabilities(estimator.classes_, row) for row in values]


def _estimator(name):
    if name.startswith("logistic-regression"):
        from sklearn.linear_model import LogisticRegression
        from sklearn.multiclass import OneVsRestClassifier
        return estimator_pipeline(
            OneVsRestClassifier(LogisticRegression(
                solver="liblinear", C=0.1 if name.endswith("regularized") else 0.01, max_iter=1000,
                class_weight="balanced", random_state=42,
            )),
            scale=True,
        )
    if name.startswith("random-forest"):
        from sklearn.ensemble import RandomForestClassifier
        regularized = name.endswith("regularized")
        return estimator_pipeline(RandomForestClassifier(n_estimators=350 if regularized else 200, max_depth=8 if regularized else 6, min_samples_leaf=10 if regularized else 2, max_features="sqrt" if regularized else 1.0, class_weight="balanced_subsample", random_state=42, n_jobs=4))
    if name.startswith("lightgbm"):
        import lightgbm as lgb
        regularized = name.endswith("regularized")
        return estimator_pipeline(lgb.LGBMClassifier(n_estimators=350 if regularized else 200, learning_rate=0.025 if regularized else 0.05, num_leaves=15 if regularized else 31, min_child_samples=80 if regularized else 20, subsample=0.8, colsample_bytree=0.8, reg_alpha=0.1 if regularized else 0.0, reg_lambda=1.0 if regularized else 0.0, class_weight="balanced", random_state=42, verbose=-1, n_jobs=4))
    if name.startswith("xgboost"):
        import xgboost as xgb
        regularized = name.endswith("regularized")
        return estimator_pipeline(xgb.XGBClassifier(
            objective="multi:softprob", num_class=len(CLASSES), n_estimators=350 if regularized else 200,
            max_depth=3 if regularized else 5, learning_rate=0.03 if regularized else 0.05,
            min_child_weight=5 if regularized else 1, reg_lambda=2.0 if regularized else 1.0,
            subsample=0.8, colsample_bytree=0.8,
            # ``hist`` preserves the same deterministic boosting objective
            # while avoiding expensive exact split search on the full panel.
            tree_method="hist", max_bin=255,
            random_state=42, verbosity=0, n_jobs=4,
        ))
    raise ValueError(f"unsupported direction candidate: {name}")


def _direction(sample: TrainingSample, horizon: int, multiplier: float = 0.5) -> str:
    """Apply a development-selected volatility boundary without touching holdout data."""
    raw = getattr(sample.labels, f"future_return_{horizon}d")
    standardized = getattr(sample.labels, f"volatility_standardized_return_{horizon}d")
    if raw is None or standardized is None:
        raise ValueError(f"direction_{horizon}d label unavailable")
    # z = return / volatility_scale.  Recover the scale stored by the PIT
    # label builder, then apply the candidate multiplier and the versioned
    # two-times-round-trip-cost floor.
    scale = abs(float(raw) / float(standardized)) if abs(float(standardized)) > 1e-12 else 0.0
    is_etf = getattr(sample.instrument_type, "value", sample.instrument_type) == "etf"
    cost_floor = 0.0024 if is_etf else 0.0042
    threshold = max(cost_floor, scale * multiplier)
    return "up" if raw > threshold else "down" if raw < -threshold else "flat"


def _select_label_multiplier(folds, horizon: int) -> float:
    """Select 0.25/0.50/0.75 only from development time-OOF folds."""
    from sklearn.metrics import f1_score

    scores: dict[float, list[float]] = {value: [] for value in (0.25, 0.50, 0.75)}
    for fold in folds:
        for multiplier in scores:
            actual = [_direction(sample, horizon, multiplier) for sample in fold.validation]
            source = "benchmark_ret_20d" if horizon == 5 else "ret_5d"
            predicted = [
                max(_heuristic(float(sample.features.get(source, 0.0))), key=_heuristic(float(sample.features.get(source, 0.0))).get)
                for sample in fold.validation
            ]
            scores[multiplier].append(float(f1_score(
                actual, predicted, labels=list(CLASSES), average="macro", zero_division=0,
            )))
    return max(scores, key=lambda value: (sum(scores[value]) / max(len(scores[value]), 1), -abs(value - 0.5)))


def _vector(sample, features):
    return [sample.features.get(name) for name in features]


def _matrix(samples, features):
    return sample_matrix(samples, features)


def _clip_scaled_values(values):
    import numpy as np

    return np.clip(np.nan_to_num(values, nan=0.0, posinf=20.0, neginf=-20.0), -20.0, 20.0)


def _frequencies(labels):
    total = len(labels) + len(CLASSES)
    return {key: (labels.count(key) + 1) / total for key in CLASSES}


def _heuristic(value):
    target = "up" if value > 0.002 else "down" if value < -0.002 else "flat"
    return {key: 0.8 if key == target else 0.1 for key in CLASSES}


def _map_probabilities(classes, values):
    result = {key: 0.0 for key in CLASSES}
    result.update({str(key): float(value) for key, value in zip(classes, values)})
    return _normalize(result)


def _calibrate_multiclass(
    fit_probabilities, labels, *, apply_probabilities, prediction_fold_ids: list[str] | None = None
):
    # Per-class Platt calibration uses only time-OOF development predictions.
    calibrated: dict[str, TimeOutOfFoldCalibrator] = {}
    fold_ids = prediction_fold_ids or ["time_oof"] * len(labels)
    if len(fold_ids) != len(labels):
        raise ValueError("direction calibration fold identifiers must align with OOF labels")
    for label in CLASSES:
        targets = [int(value == label) for value in labels]
        if len(set(targets)) < 2:
            continue
        calibrated[label] = TimeOutOfFoldCalibrator(CalibrationMethod.PLATT).fit(
            [row[label] for row in fit_probabilities], targets,
            prediction_fold_ids=fold_ids,
            training_fold_ids=[f"train:{fold_id}" for fold_id in sorted(set(fold_ids))],
        )
    output = []
    for row in apply_probabilities:
        adjusted = {
            key: calibrated[key].predict_many([row[key]])[0] if key in calibrated else row[key]
            for key in CLASSES
        }
        output.append(_normalize(adjusted))
    return output


def _normalize(values):
    total = sum(max(0.0, value) for value in values.values())
    return {key: max(0.0, value) / total for key, value in values.items()} if total else {key: 1 / 3 for key in CLASSES}


def _metrics(name, raw_probabilities, probabilities, labels, fold_hash, *, regimes=None):
    from sklearn.metrics import average_precision_score, balanced_accuracy_score, f1_score, log_loss, roc_auc_score
    from sklearn.preprocessing import label_binarize
    predicted = [max(row, key=row.get) for row in probabilities]
    ordered_labels = sorted(CLASSES)
    matrix = [[row[key] for key in ordered_labels] for row in probabilities]
    binary = label_binarize(labels, classes=ordered_labels)
    try:
        macro_auroc = float(roc_auc_score(binary, matrix, average="macro", multi_class="ovr"))
        macro_pr_auc = float(average_precision_score(binary, matrix, average="macro"))
    except ValueError:
        macro_auroc = None
        macro_pr_auc = None
    confidence = [max(row.values()) for row in probabilities]
    correctness = [int(prediction == actual) for prediction, actual in zip(predicted, labels)]
    regime_metrics = {}
    if regimes:
        for regime in REGIMES:
            indexes = [index for index, value in enumerate(regimes) if regime_matches(value, regime)]
            if not indexes:
                continue
            actual = [labels[index] for index in indexes]
            predicted_group = [predicted[index] for index in indexes]
            regime_metrics[regime] = {
                "sample_count": float(len(indexes)),
                "macro_f1": float(f1_score(actual, predicted_group, labels=list(CLASSES), average="macro", zero_division=0)),
                "balanced_accuracy": float(balanced_accuracy_score(actual, predicted_group)),
            }
    return DirectionCandidateResult(
        name=name, raw_probabilities=raw_probabilities, probabilities=probabilities, labels=labels,
        macro_f1=float(f1_score(labels, predicted, labels=list(CLASSES), average="macro", zero_division=0)),
        balanced_accuracy=float(balanced_accuracy_score(labels, predicted)),
        log_loss=float(log_loss(labels, matrix, labels=ordered_labels)),
        ece=_ece(confidence, correctness), macro_auroc=macro_auroc,
        macro_pr_auc=macro_pr_auc, fold_hash=fold_hash,
        regime_metrics=regime_metrics,
    )


def _ensemble(predictions, labels):
    # Candidate rows here are OOF probability distributions.  Score each
    # candidate against the same OOF labels before deriving time-OOF weights.
    weights = {
        name: 1 / max(_metrics(name, rows, rows, labels, "").log_loss, 1e-8)
        for name, rows in predictions.items()
    }
    total = sum(weights.values())
    return [{key: sum(weights[name] * rows[index][key] for name, rows in predictions.items()) / total for key in CLASSES} for index in range(len(labels))]


def _class_index(label: str) -> int:
    return CLASSES.index(label)


def _ece(confidence: list[float], correctness: list[int], bins: int = 10) -> float:
    total = len(confidence)
    value = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [i for i, score in enumerate(confidence) if low <= score < high or (index == bins - 1 and score == 1)]
        if members:
            accuracy = sum(correctness[i] for i in members) / len(members)
            average_confidence = sum(confidence[i] for i in members) / len(members)
            value += len(members) / total * abs(accuracy - average_confidence)
    return value
