from __future__ import annotations

from collections import defaultdict
import hashlib
import json

from investment_research.training.evaluation import evaluate_risk_bucket_usefulness
from investment_research.training.models import (
    FoldMetric,
    ModelCard,
    PreparedPriceBar,
    RiskBucketObservation,
    TrainingSample,
    WalkForwardFold,
    WalkForwardFoldResult,
)
from investment_research.training.trainers import LinearBaselineTrainerSpec, TrainerSpec
from investment_research.training.validation import build_walk_forward_folds


class WalkForwardTrainingRunner:
    def __init__(
        self,
        *,
        target_name: str,
        drawdown_threshold: float = -0.08,
        trainer_spec: TrainerSpec | None = None,
    ) -> None:
        self.target_name = target_name
        self.drawdown_threshold = drawdown_threshold
        self.trainer_spec = trainer_spec or LinearBaselineTrainerSpec()

    def run(
        self,
        *,
        samples: list[TrainingSample],
        train_window_days: int,
        validation_window_days: int,
        step_days: int | None = None,
        regime_reference: list[PreparedPriceBar] | None = None,
        prediction_horizon_days: int = 0,
        embargo_days: int | None = None,
    ) -> tuple[ModelCard, list[WalkForwardFoldResult]]:
        if not samples:
            raise ValueError("samples must not be empty")
        ordered_samples = sorted(samples, key=lambda item: item.as_of_date)
        sample_dates = [sample.as_of_date for sample in ordered_samples]
        benchmark_ref = []
        horizon = prediction_horizon_days
        folds = build_walk_forward_folds(
            sample_dates,
            train_window_days=train_window_days,
            validation_window_days=validation_window_days,
            step_days=step_days,
            regime_reference=regime_reference or benchmark_ref,
            prediction_horizon_days=horizon,
            embargo_days=embargo_days,
        )
        if not folds:
            raise ValueError("not enough samples to build walk-forward folds")

        fold_results: list[WalkForwardFoldResult] = []
        all_metrics: list[FoldMetric] = []
        for fold in folds:
            train_samples = [sample for sample in ordered_samples if fold.train_start <= sample.as_of_date <= fold.train_end]
            validation_samples = [sample for sample in ordered_samples if fold.validation_start <= sample.as_of_date <= fold.validation_end]
            if not train_samples or not validation_samples:
                continue

            model = self.trainer_spec.build(
                target_name=self.target_name,
                drawdown_threshold=self.drawdown_threshold,
            ).fit(train_samples)
            predict_many = getattr(model, "predict_many", None)
            predictions = (
                predict_many(validation_samples)
                if callable(predict_many)
                else [model.predict(sample) for sample in validation_samples]
            )
            for sample, prediction in zip(validation_samples, predictions):
                actual_value = getattr(sample.labels, self.target_name, None)
                prediction.market = sample.market.value
                prediction.coverage_group = sample.coverage_group.value
                prediction.validation_end = fold.validation_end
                prediction.actual_value = actual_value
                prediction.actual_label = self._label_to_binary(actual_value)
            observations = [
                RiskBucketObservation(
                    symbol=sample.symbol,
                    score=prediction.calibrated_score,
                    future_max_drawdown_20d=_observation_target_value(sample=sample, target_name=self.target_name),
                )
                for sample, prediction in zip(validation_samples, predictions)
            ]
            evaluation = evaluate_risk_bucket_usefulness(
                observations,
                top_fraction=0.2,
                event_drawdown_threshold=self.drawdown_threshold,
                higher_is_risk=not self._is_drawdown_task(),
            )
            metrics = [
                FoldMetric(fold_id=fold.fold_id, regime=fold.regime, metric_name="top_bucket_drawdown_lift", metric_value=evaluation.drawdown_lift),
                FoldMetric(fold_id=fold.fold_id, regime=fold.regime, metric_name="top_bucket_alert_precision", metric_value=evaluation.alert_precision or 0.0),
                FoldMetric(fold_id=fold.fold_id, regime=fold.regime, metric_name="auc_roc", metric_value=evaluation.auc_roc or 0.0),
                FoldMetric(fold_id=fold.fold_id, regime=fold.regime, metric_name="pr_auc", metric_value=evaluation.pr_auc or 0.0),
                FoldMetric(fold_id=fold.fold_id, regime=fold.regime, metric_name="brier_score", metric_value=evaluation.brier_score or 0.0),
                FoldMetric(
                    fold_id=fold.fold_id,
                    regime=fold.regime,
                    metric_name="expected_calibration_error",
                    metric_value=evaluation.expected_calibration_error or 0.0,
                ),
            ]
            all_metrics.extend(metrics)
            fold_results.append(WalkForwardFoldResult(fold=fold, metrics=metrics, predictions=predictions))

        first_sample = ordered_samples[0]
        fold_hash = hashlib.sha256(
            json.dumps(
                [item.model_dump(mode="json") for item in folds],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        card = ModelCard(
            model_id=f"{self.trainer_spec.algorithm_family}-{self.target_name}-{first_sample.data_version}-{first_sample.feature_version}",
            task_name=self.target_name,
            algorithm_family=self.trainer_spec.algorithm_family,
            algorithm_name=self.trainer_spec.algorithm_name,
            data_version=first_sample.data_version,
            feature_version=first_sample.feature_version,
            label_version="multitask-v2",
            decision_context=first_sample.decision_context,
            prediction_horizon_days=horizon,
            fold_hash=fold_hash,
            market_snapshot_hashes=sorted(
                {
                    sample.market_snapshot_id
                    for sample in ordered_samples
                    if sample.market_snapshot_id
                }
            ),
            training_window_start=min(sample.as_of_date for sample in ordered_samples),
            training_window_end=max(sample.as_of_date for sample in ordered_samples),
            calibration_method="bucket_frequency",
            validation_metrics=all_metrics,
            notes=[
                *self._metric_notes(all_metrics),
                *self._regime_notes(fold_results),
            ],
        )
        return card, fold_results

    def _prediction_horizon_days(self) -> int:
        if "120d" in self.target_name:
            return 120
        if "60d" in self.target_name:
            return 60
        if "20d" in self.target_name:
            return 20
        if "10d" in self.target_name:
            return 10
        if "5d" in self.target_name:
            return 5
        if "3d" in self.target_name:
            return 3
        if "1d" in self.target_name:
            return 1
        return 20

    def _is_drawdown_task(self) -> bool:
        return "drawdown" in self.target_name

    def _label_to_binary(self, value: float | None) -> int | None:
        if value is None:
            return None
        if self._is_drawdown_task():
            return 1 if value <= self.drawdown_threshold else 0
        return 1 if value > 0 else 0

    def _metric_notes(self, metrics: list[FoldMetric]) -> list[str]:
        if not metrics:
            return ["No validation metrics produced."]
        grouped: dict[str, list[float]] = defaultdict(list)
        for metric in metrics:
            grouped[metric.metric_name].append(metric.metric_value)
        return [
            f"{metric_name}: mean={sum(values) / len(values):.4f} across {len(values)} folds"
            for metric_name, values in sorted(grouped.items())
        ]

    def _regime_notes(self, fold_results: list[WalkForwardFoldResult]) -> list[str]:
        if not fold_results:
            return []

        grouped_metrics: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for fold_result in fold_results:
            for metric in fold_result.metrics:
                grouped_metrics[fold_result.fold.regime][metric.metric_name].append(metric.metric_value)

        notes: list[str] = []
        for regime, metric_groups in sorted(grouped_metrics.items()):
            drawdown_values = metric_groups.get("top_bucket_drawdown_lift", [])
            auc_values = metric_groups.get("auc_roc", [])
            precision_values = metric_groups.get("top_bucket_alert_precision", [])
            fragments = [f"regime={regime}"]
            if drawdown_values:
                fragments.append(f"drawdown_lift_mean={sum(drawdown_values) / len(drawdown_values):.4f}")
            if auc_values:
                fragments.append(f"auc_mean={sum(auc_values) / len(auc_values):.4f}")
            if precision_values:
                fragments.append(f"alert_precision_mean={sum(precision_values) / len(precision_values):.4f}")
            fragments.append(f"folds={sum(1 for item in fold_results if item.fold.regime == regime)}")
            notes.append("regime_summary: " + " ".join(fragments))
        return notes


def _observation_target_value(*, sample: TrainingSample, target_name: str) -> float:
    if "drawdown" in target_name:
        return sample.labels.future_max_drawdown_20d or 0.0
    value = getattr(sample.labels, target_name, None)
    return 0.0 if value is None else float(value)
