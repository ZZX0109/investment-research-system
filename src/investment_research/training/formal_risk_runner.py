from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Callable

from investment_research.training.calibration import compare_calibrators
from investment_research.training.formal_training import (
    FinalHoldoutLedger,
    FormalScopeTrainingPlan,
    RISK_CANDIDATES,
    balanced_panel_fit_samples,
    require_candidate_dependencies,
)
from investment_research.training.models import TrainingSample
from investment_research.training.numeric_safety import guarded_model_math, require_finite
from investment_research.training.research_evaluation import REGIMES, classify_market_regime_groups, fit_regime_thresholds, regime_matches
from investment_research.training.tabular_preprocessing import estimator_pipeline, sample_matrix


@dataclass(frozen=True)
class RiskCandidateResult:
    name: str
    raw_oof_scores: list[float]
    oof_scores: list[float]
    oof_labels: list[int]
    oof_fold_ids: list[str]
    calibration_method: str | None
    brier: float
    auroc: float | None
    pr_auc: float | None
    ece: float
    alert_precision: float
    base_rate: float
    alert_coverage: float
    drawdown_lift: float
    regime_metrics: dict[str, dict[str, float | None]]
    fold_hash: str


@dataclass(frozen=True)
class FormalRiskTrainingResult:
    scope_id: str
    fold_hash: str
    candidates: list[RiskCandidateResult]
    selected_candidate: str
    holdout_scores: list[float]
    holdout_labels: list[int]
    stress_scores: list[float]
    stress_labels: list[int]


class FormalRiskTrainingRunner:
    """Risk-candidate runner using one PIT fold plan and time-OOF calibration."""

    def __init__(self, *, drawdown_threshold: float = -0.08) -> None:
        self.drawdown_threshold = drawdown_threshold

    def run(
        self,
        *,
        samples: list[TrainingSample],
        market: str,
        decision_context: str,
        dataset_hash: str,
        holdout_ledger: FinalHoldoutLedger,
    ) -> FormalRiskTrainingResult:
        require_candidate_dependencies("drawdown_20d")
        plan = FormalScopeTrainingPlan(
            samples, market=market, decision_context=decision_context,
            task="drawdown_20d", prediction_horizon_sessions=20,
        )
        holdout, folds, fold_hash = plan.build()
        if not folds:
            raise ValueError("formal risk scope has no valid purged walk-forward folds")
        feature_order = sorted({key for sample in holdout.development for key in sample.features})
        candidates: list[RiskCandidateResult] = []
        raw_predictions: dict[str, list[float]] = {}
        calibrators = {}
        labels: list[int] | None = None
        fold_ids: list[str] | None = None
        for name in RISK_CANDIDATES[:-1]:
            scores, candidate_labels, candidate_fold_ids, regimes = self._oof(
                name=name, folds=folds, feature_order=feature_order
            )
            calibrator, reports = compare_calibrators(
                calibration_scores=scores,
                calibration_labels=candidate_labels,
                prediction_fold_ids=candidate_fold_ids,
                training_fold_ids=["development_only"],
            )
            calibrated = calibrator.predict_many(scores)
            alert_coverage = _select_alert_coverage(calibrated, candidate_labels)
            result = RiskCandidateResult(
                name=name,
                raw_oof_scores=scores,
                oof_scores=calibrated,
                oof_labels=candidate_labels,
                oof_fold_ids=candidate_fold_ids,
                calibration_method=calibrator.method.value,
                brier=_brier(calibrated, candidate_labels),
                auroc=_auroc(candidate_labels, calibrated),
                pr_auc=_pr_auc(candidate_labels, calibrated),
                ece=_binary_ece(calibrated, candidate_labels),
                alert_precision=_alert_precision(calibrated, candidate_labels, alert_coverage),
                base_rate=sum(candidate_labels) / len(candidate_labels),
                alert_coverage=alert_coverage,
                drawdown_lift=_drawdown_lift(calibrated, candidate_labels, alert_coverage),
                regime_metrics=_risk_regime_metrics(calibrated, candidate_labels, regimes, alert_coverage),
                fold_hash=fold_hash,
            )
            candidates.append(result)
            raw_predictions[name] = calibrated
            calibrators[name] = calibrator
            labels = candidate_labels
            fold_ids = candidate_fold_ids
        assert labels is not None and fold_ids is not None
        ensemble = _ensemble(raw_predictions, labels)
        ensemble_alert_coverage = _select_alert_coverage(ensemble, labels)
        candidates.append(
            RiskCandidateResult(
                name="time-oof-weighted-ensemble", raw_oof_scores=ensemble,
                oof_scores=ensemble, oof_labels=labels, oof_fold_ids=fold_ids,
                calibration_method="time_oof_weighted",
                brier=_brier(ensemble, labels), auroc=_auroc(labels, ensemble), fold_hash=fold_hash,
                pr_auc=_pr_auc(labels, ensemble),
                ece=_binary_ece(ensemble, labels),
                alert_precision=_alert_precision(ensemble, labels, ensemble_alert_coverage),
                base_rate=sum(labels) / len(labels), alert_coverage=ensemble_alert_coverage,
                drawdown_lift=_drawdown_lift(ensemble, labels, ensemble_alert_coverage),
                regime_metrics=_risk_regime_metrics(ensemble, labels, regimes, ensemble_alert_coverage),
            )
        )
        # The ensemble remains a reported challenger until its constituent
        # artifacts and weights are frozen as a deployable bundle.
        selected = min(
            (item for item in candidates if item.name != "time-oof-weighted-ensemble"),
            key=lambda item: item.brier,
        )
        # This is the only final-holdout use. Claim before evaluating so a
        # process crash cannot lead to an untracked repeat evaluation.
        holdout_ledger.claim(scope_id=plan.scope_id, dataset_hash=dataset_hash, fold_hash=fold_hash)
        final_raw_scores = self._fit_predict(
            name=selected.name,
            train=holdout.development,
            evaluate=holdout.holdout_12m,
            feature_order=feature_order,
        )
        final_scores = calibrators[selected.name].predict_many(final_raw_scores)
        final_labels = [_label(item, self.drawdown_threshold) for item in holdout.holdout_12m]
        # The recent six-month slice is a subset of the one-shot final
        # holdout. It is evaluated with the already frozen selected model and
        # calibrator only; it is never used for selection or calibration.
        stress_raw_scores = self._fit_predict(
            name=selected.name,
            train=holdout.development,
            evaluate=holdout.stress_6m,
            feature_order=feature_order,
        )
        stress_scores = calibrators[selected.name].predict_many(stress_raw_scores)
        stress_labels = [_label(item, self.drawdown_threshold) for item in holdout.stress_6m]
        return FormalRiskTrainingResult(
            scope_id=plan.scope_id, fold_hash=fold_hash, candidates=candidates,
            selected_candidate=selected.name, holdout_scores=final_scores,
            holdout_labels=final_labels, stress_scores=stress_scores,
            stress_labels=stress_labels,
        )

    def _oof(self, *, name: str, folds, feature_order: list[str]) -> tuple[list[float], list[int], list[str], list[str]]:
        scores: list[float] = []
        labels: list[int] = []
        ids: list[str] = []
        regimes: list[str] = []
        for fold in folds:
            thresholds = fit_regime_thresholds(fold.train)
            fold_scores = self._fit_predict(
                name=name, train=fold.train, evaluate=fold.validation, feature_order=feature_order
            )
            scores.extend(fold_scores)
            labels.extend(_label(item, self.drawdown_threshold) for item in fold.validation)
            ids.extend([fold.fold.fold_id] * len(fold.validation))
            regimes.extend(classify_market_regime_groups(item, thresholds) for item in fold.validation)
        if len(set(labels)) < 2:
            raise ValueError(f"risk candidate {name} has one-class OOF labels")
        return scores, labels, ids, regimes

    def _fit_predict(self, *, name: str, train: list[TrainingSample], evaluate: list[TrainingSample], feature_order: list[str]) -> list[float]:
        fit_train = balanced_panel_fit_samples(train)
        labels = [_label(item, self.drawdown_threshold) for item in fit_train]
        if name == "historical-distribution":
            probability = sum(labels) / len(labels)
            return [probability] * len(evaluate)
        if name == "time-oof-weighted-ensemble":
            # The selected ensemble is rebuilt from OOF weights in the caller;
            # a final fitted ensemble needs frozen constituent artifacts.
            raise ValueError("ensemble cannot be final-evaluated without frozen component artifacts")
        matrix = _matrix(fit_train, feature_order)
        evaluation = _matrix(evaluate, feature_order)
        estimator = _estimator(name)
        with guarded_model_math():
            estimator.fit(matrix, labels)
            predictions = _predict_proba(estimator, evaluation)
        require_finite(predictions, stage=f"risk:{name}")
        return predictions


def _estimator(name: str):
    if name in {"linear-baseline", "logistic-regression"}:
        from sklearn.linear_model import LogisticRegression
        return estimator_pipeline(
            LogisticRegression(
                solver="liblinear", C=0.01, max_iter=1000,
                class_weight="balanced", random_state=42,
            ),
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
        return estimator_pipeline(xgb.XGBClassifier(n_estimators=350 if regularized else 200, max_depth=3 if regularized else 5, learning_rate=0.03 if regularized else 0.05, min_child_weight=5 if regularized else 1, reg_lambda=2.0 if regularized else 1.0, subsample=0.8, colsample_bytree=0.8, tree_method="hist", max_bin=255, random_state=42, verbosity=0, n_jobs=4))
    raise ValueError(f"unsupported formal risk candidate: {name}")


def _vector(sample: TrainingSample, feature_order: list[str]) -> list[float]:
    return [sample.features.get(name) for name in feature_order]


def _matrix(samples: list[TrainingSample], feature_order: list[str]):
    return sample_matrix(samples, feature_order)


def _clip_scaled_values(values):
    import numpy as np

    return np.clip(np.nan_to_num(values, nan=0.0, posinf=20.0, neginf=-20.0), -20.0, 20.0)


def _label(sample: TrainingSample, threshold: float) -> int:
    value = sample.labels.future_max_drawdown_20d
    if value is None:
        raise ValueError("risk task sample lacks future_max_drawdown_20d")
    return int(value <= threshold)


def _predict_proba(estimator, values: list[list[float]]) -> list[float]:
    probabilities = estimator.predict_proba(values)
    classes = list(estimator.classes_)
    index = classes.index(1) if 1 in classes else 0
    return [float(row[index]) for row in probabilities]


def _brier(scores: list[float], labels: list[int]) -> float:
    return sum((score - label) ** 2 for score, label in zip(scores, labels)) / len(labels)


def _auroc(labels: list[int], scores: list[float]) -> float | None:
    if len(set(labels)) < 2:
        return None
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(labels, scores))


def _pr_auc(labels: list[int], scores: list[float]) -> float | None:
    if len(set(labels)) < 2:
        return None
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(labels, scores))


def _ensemble(predictions: dict[str, list[float]], labels: list[int]) -> list[float]:
    weights = {name: 1.0 / max(_brier(values, labels), 1e-8) for name, values in predictions.items()}
    total = sum(weights.values())
    return [
        sum(weights[name] * values[index] for name, values in predictions.items()) / total
        for index in range(len(labels))
    ]


def _binary_ece(scores: list[float], labels: list[int], bins: int = 10) -> float:
    total = len(scores)
    value = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [i for i, score in enumerate(scores) if low <= score < high or (index == bins - 1 and score == 1)]
        if members:
            observed = sum(labels[i] for i in members) / len(members)
            confidence = sum(scores[i] for i in members) / len(members)
            value += len(members) / total * abs(observed - confidence)
    return value


def _alert_precision(scores: list[float], labels: list[int], fraction: float = 0.2) -> float:
    count = max(1, round(len(scores) * fraction))
    selected = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:count]
    return sum(labels[index] for index in selected) / len(selected)


def _select_alert_coverage(scores: list[float], labels: list[int]) -> float:
    """Freeze an alert budget from development OOF predictions only."""
    prevalence = sum(labels) / len(labels)
    candidates = (0.10, 0.15, 0.20, 0.25, 0.30)
    return max(
        candidates,
        key=lambda fraction: (
            _alert_precision(scores, labels, fraction) - prevalence,
            -fraction,
        ),
    )


def _drawdown_lift(scores: list[float], labels: list[int], fraction: float = 0.2) -> float:
    prevalence = sum(labels) / len(labels)
    return _alert_precision(scores, labels, fraction) / prevalence - 1 if prevalence else 0.0


def _risk_regime_metrics(scores: list[float], labels: list[int], regimes: list[str], alert_coverage: float = 0.2) -> dict[str, dict[str, float | None]]:
    output: dict[str, dict[str, float | None]] = {}
    for regime in REGIMES:
        indexes = [index for index, value in enumerate(regimes) if regime_matches(value, regime)]
        if not indexes:
            continue
        group_scores = [scores[index] for index in indexes]
        group_labels = [labels[index] for index in indexes]
        output[regime] = {
            "sample_count": float(len(indexes)),
            "auroc": _auroc(group_labels, group_scores),
            "pr_auc": _pr_auc(group_labels, group_scores),
            "brier": _brier(group_scores, group_labels),
            "alert_precision": _alert_precision(group_scores, group_labels, alert_coverage),
            "base_rate": sum(group_labels) / len(group_labels),
            "alert_coverage": alert_coverage,
            "drawdown_lift": _drawdown_lift(group_scores, group_labels, alert_coverage),
        }
    return output
