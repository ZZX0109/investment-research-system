from __future__ import annotations

from collections import Counter

from investment_research.training.models import (
    LabelCoverageRecord,
    PointInTimeIntegritySummary,
    PromotionGatePolicy,
    PreparedPriceBar,
    RegimeCoverageRecord,
    ReferenceCoverageRecord,
    SkippedTrainerRecord,
    TargetLabelAuditSummary,
    TrainingExperimentAuditSummary,
    TrainingExperimentReport,
    TrainingExperimentResult,
    TrainingSampleCoverageSummary,
    TrainingSample,
)
from investment_research.training.promotion import evaluate_promotion_gate
from investment_research.training.trainers import TrainerSpec
from investment_research.training.workflow import WalkForwardTrainingRunner


def _prediction_horizon_days(target_name: str) -> int:
    for horizon in (120, 60, 20, 10, 5, 3, 1):
        if f"{horizon}d" in target_name:
            return horizon
    return 20


def _uses_pit_v2(samples: list[TrainingSample]) -> bool:
    return bool(samples) and all(
        "v2" in sample.feature_version.lower() for sample in samples
    )


class TrainingExperimentRunner:
    def __init__(
        self,
        *,
        target_name: str,
        trainer_specs: list[TrainerSpec],
        drawdown_threshold: float = -0.08,
        promotion_policy: PromotionGatePolicy | None = None,
    ) -> None:
        self.target_name = target_name
        self.trainer_specs = trainer_specs
        self.drawdown_threshold = drawdown_threshold
        self.promotion_policy = promotion_policy or PromotionGatePolicy()

    def run(
        self,
        *,
        samples: list[TrainingSample],
        train_window_days: int,
        validation_window_days: int,
        step_days: int | None = None,
        regime_reference: list[PreparedPriceBar] | None = None,
    ) -> TrainingExperimentReport:
        if not self.trainer_specs:
            raise ValueError("trainer_specs must not be empty")

        results: list[TrainingExperimentResult] = []
        skipped_trainers: list[SkippedTrainerRecord] = []
        baseline_card = None
        baseline_fold_results = None
        audit_summary = TrainingExperimentAuditSummary(
            sample_coverage=self._build_sample_coverage_summary(samples),
            label_coverage=self._build_label_coverage_summary(samples),
            target_label=self._build_target_label_summary(samples),
            reference_coverage=self._build_reference_coverage_summary(samples),
            point_in_time_integrity=self._build_point_in_time_integrity_summary(samples),
            skipped_trainers=skipped_trainers,
        )

        for index, spec in enumerate(self.trainer_specs):
            try:
                print(
                    f"    trainer {index + 1}/{len(self.trainer_specs)}: {spec.name} "
                    f"({spec.algorithm_family})",
                    flush=True,
                )
                card, fold_results = WalkForwardTrainingRunner(
                    target_name=self.target_name,
                    drawdown_threshold=self.drawdown_threshold,
                    trainer_spec=spec,
                ).run(
                    samples=samples,
                    train_window_days=train_window_days,
                    validation_window_days=validation_window_days,
                    step_days=step_days,
                    regime_reference=regime_reference,
                    prediction_horizon_days=(
                        _prediction_horizon_days(self.target_name)
                        if _uses_pit_v2(samples)
                        else 0
                    ),
                )
                print(
                    f"      completed {spec.name}: folds={len(fold_results)}",
                    flush=True,
                )
            except ImportError as exc:
                skipped_trainers.append(
                    SkippedTrainerRecord(
                        trainer_name=spec.name,
                        algorithm_family=spec.algorithm_family,
                        reason=f"missing optional dependency: {exc}",
                    )
                )
                continue

            promotion_result = None
            eligible = index == 0
            if index == 0:
                baseline_card = card
                baseline_fold_results = fold_results
            else:
                promotion_result = evaluate_promotion_gate(
                    candidate=card,
                    baseline=baseline_card,
                    policy=self.promotion_policy,
                    audit=audit_summary,
                    candidate_fold_results=fold_results,
                    baseline_fold_results=baseline_fold_results,
                )
                eligible = promotion_result.eligible

            results.append(
                TrainingExperimentResult(
                    trainer_name=spec.name,
                    algorithm_family=spec.algorithm_family,
                    model_card=card.model_copy(
                        update={
                            "notes": [
                                *card.notes,
                                *(["promotion: eligible"] if promotion_result and promotion_result.eligible else []),
                                *(["promotion: baseline"] if index == 0 else []),
                                *([] if promotion_result is None else [f"promotion_reason: {reason}" for reason in promotion_result.reasons]),
                            ]
                        }
                    ),
                    fold_results=fold_results,
                    promotion_result=promotion_result,
                    eligible_for_approval=eligible,
                    regime_coverage=self._build_regime_coverage_from_folds(fold_results),
                )
            )

        return TrainingExperimentReport(
            target_name=self.target_name,
            baseline_model_id=None if baseline_card is None else baseline_card.model_id,
            results=results,
            audit=audit_summary.model_copy(
                update={
                    "regime_coverage": self._build_report_regime_coverage(results),
                    "skipped_trainers": skipped_trainers,
                }
            ),
        )

    def _build_sample_coverage_summary(self, samples: list[TrainingSample]) -> TrainingSampleCoverageSummary:
        if not samples:
            return TrainingSampleCoverageSummary()

        sorted_dates = sorted(sample.as_of_date for sample in samples)
        symbols = sorted({sample.symbol for sample in samples})
        markets = sorted({sample.market.value for sample in samples})
        instrument_types = sorted({sample.instrument_type.value for sample in samples})
        coverage_groups = sorted({sample.coverage_group.value for sample in samples})
        feature_versions = sorted({sample.feature_version for sample in samples})
        data_versions = sorted({sample.data_version for sample in samples})
        total_point_in_time_events = sum(sample.point_in_time_event_count for sample in samples)
        max_point_in_time_events_in_sample = max(sample.point_in_time_event_count for sample in samples)
        samples_with_data_issues = sum(1 for sample in samples if sample.data_issues)
        total_data_issue_count = sum(len(sample.data_issues) for sample in samples)
        data_issue_code_counts = dict(sorted(Counter(issue for sample in samples for issue in sample.data_issues).items()))

        return TrainingSampleCoverageSummary(
            sample_count=len(samples),
            symbol_count=len(symbols),
            symbols=symbols,
            markets=markets,
            instrument_types=instrument_types,
            coverage_groups=coverage_groups,
            start_date=sorted_dates[0],
            end_date=sorted_dates[-1],
            feature_versions=feature_versions,
            data_versions=data_versions,
            total_point_in_time_events=total_point_in_time_events,
            max_point_in_time_events_in_sample=max_point_in_time_events_in_sample,
            samples_with_data_issues=samples_with_data_issues,
            total_data_issue_count=total_data_issue_count,
            data_issue_code_counts=data_issue_code_counts,
        )

    def _build_label_coverage_summary(self, samples: list[TrainingSample]) -> list[LabelCoverageRecord]:
        if not samples:
            return []

        label_names = list(type(samples[0].labels).model_fields.keys())
        coverage: list[LabelCoverageRecord] = []
        sample_count = len(samples)
        for label_name in label_names:
            if label_name in {"symbol", "as_of_date"}:
                continue
            available_count = sum(1 for sample in samples if getattr(sample.labels, label_name) is not None)
            missing_count = sample_count - available_count
            coverage.append(
                LabelCoverageRecord(
                    label_name=label_name,
                    available_count=available_count,
                    missing_count=missing_count,
                    availability_ratio=available_count / sample_count if sample_count else 0.0,
                )
            )
        return coverage

    def _build_point_in_time_integrity_summary(self, samples: list[TrainingSample]) -> PointInTimeIntegritySummary:
        if not samples:
            return PointInTimeIntegritySummary()

        leakage_codes = {
            "future_price_bar",
            "future_event",
        }
        issue_counter = Counter(issue for sample in samples for issue in sample.data_issues if issue in leakage_codes)
        return PointInTimeIntegritySummary(
            sample_count_with_events=sum(1 for sample in samples if sample.point_in_time_event_count > 0),
            sample_count_without_events=sum(1 for sample in samples if sample.point_in_time_event_count == 0),
            total_point_in_time_events=sum(sample.point_in_time_event_count for sample in samples),
            samples_with_data_issues=sum(1 for sample in samples if sample.data_issues),
            total_data_issue_count=sum(len(sample.data_issues) for sample in samples),
            potential_future_leakage_issue_count=sum(issue_counter.values()),
            potential_future_leakage_issue_codes=dict(sorted(issue_counter.items())),
        )

    def _build_target_label_summary(self, samples: list[TrainingSample]) -> TargetLabelAuditSummary:
        if not samples:
            return TargetLabelAuditSummary(target_name=self.target_name)

        available_count = sum(1 for sample in samples if getattr(sample.labels, self.target_name, None) is not None)
        sample_count = len(samples)
        return TargetLabelAuditSummary(
            target_name=self.target_name,
            available_count=available_count,
            missing_count=sample_count - available_count,
            availability_ratio=available_count / sample_count if sample_count else 0.0,
        )

    def _build_reference_coverage_summary(self, samples: list[TrainingSample]) -> list[ReferenceCoverageRecord]:
        if not samples:
            return []

        specs = [
            ("benchmark", "benchmark_symbol", "benchmark_ret_20d"),
            ("sector", "sector_reference_symbol", "sector_ret_20d"),
            ("style", "style_reference_symbol", "style_ret_20d"),
        ]
        total_samples = len(samples)
        records: list[ReferenceCoverageRecord] = []
        for reference_type, symbol_field, feature_name in specs:
            configured_samples = [sample for sample in samples if getattr(sample, symbol_field) is not None]
            configured_count = len(configured_samples)
            feature_backed_count = sum(
                1
                for sample in configured_samples
                if feature_name in sample.features and sample.features.get(feature_name) != 0.0
            )
            reference_symbols = sorted(
                {
                    getattr(sample, symbol_field)
                    for sample in configured_samples
                    if getattr(sample, symbol_field) is not None
                }
            )
            records.append(
                ReferenceCoverageRecord(
                    reference_type=reference_type,
                    configured_sample_count=configured_count,
                    missing_configuration_count=total_samples - configured_count,
                    feature_backed_sample_count=feature_backed_count,
                    feature_backed_ratio=feature_backed_count / configured_count if configured_count else 0.0,
                    reference_symbols=reference_symbols,
                )
            )
        return records

    def _build_regime_coverage_from_folds(self, fold_results) -> list[RegimeCoverageRecord]:
        grouped: dict[str, list] = {}
        for fold_result in fold_results:
            grouped.setdefault(fold_result.fold.regime, []).append(fold_result)

        coverage: list[RegimeCoverageRecord] = []
        for regime, items in sorted(grouped.items()):
            coverage.append(
                RegimeCoverageRecord(
                    regime=regime,
                    fold_count=len(items),
                    validation_prediction_count=sum(len(item.predictions) for item in items),
                    validation_start=min(item.fold.validation_start for item in items),
                    validation_end=max(item.fold.validation_end for item in items),
                )
            )
        return coverage

    def _build_report_regime_coverage(self, results: list[TrainingExperimentResult]) -> list[RegimeCoverageRecord]:
        grouped: dict[str, dict[str, object]] = {}
        for result in results:
            for record in result.regime_coverage:
                current = grouped.get(record.regime)
                if current is None:
                    grouped[record.regime] = {
                        "fold_count": record.fold_count,
                        "validation_prediction_count": record.validation_prediction_count,
                        "validation_start": record.validation_start,
                        "validation_end": record.validation_end,
                    }
                    continue
                current["fold_count"] = max(int(current["fold_count"]), record.fold_count)
                current["validation_prediction_count"] = max(
                    int(current["validation_prediction_count"]),
                    record.validation_prediction_count,
                )
                starts = [value for value in [current["validation_start"], record.validation_start] if value is not None]
                ends = [value for value in [current["validation_end"], record.validation_end] if value is not None]
                current["validation_start"] = min(starts) if starts else None
                current["validation_end"] = max(ends) if ends else None

        return [
            RegimeCoverageRecord(
                regime=regime,
                fold_count=int(values["fold_count"]),
                validation_prediction_count=int(values["validation_prediction_count"]),
                validation_start=values["validation_start"],
                validation_end=values["validation_end"],
            )
            for regime, values in sorted(grouped.items())
        ]
