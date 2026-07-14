from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from investment_research.training.models import (
    FoldMetric,
    ModelCard,
    PromotionGateCheck,
    PromotionGatePolicy,
    PromotionGateResult,
    RegimeCoverageRecord,
    TrainingExperimentAuditSummary,
    TrainingExperimentResult,
)


def evaluate_promotion_gate(
    *,
    candidate: ModelCard,
    baseline: ModelCard | None = None,
    policy: PromotionGatePolicy | None = None,
    audit: TrainingExperimentAuditSummary | None = None,
    candidate_fold_results: list | None = None,
    baseline_fold_results: list | None = None,
) -> PromotionGateResult:
    gate = resolve_promotion_gate_policy(task_name=candidate.task_name, policy=policy)
    reasons: list[str] = []
    regime_deltas: dict[str, float] = {}
    checks: list[PromotionGateCheck] = []

    candidate_metrics = _group_metrics(candidate.validation_metrics, gate.primary_metric)
    if not candidate_metrics:
        detail = f"Candidate is missing primary metric '{gate.primary_metric}'."
        reasons.append(detail)
        checks.append(
            PromotionGateCheck(
                check_name="primary_metric_presence",
                status="failed",
                actual_value="missing",
                threshold_value=gate.primary_metric,
                detail=detail,
            )
        )
    else:
        checks.append(
            PromotionGateCheck(
                check_name="primary_metric_presence",
                status="passed",
                actual_value=gate.primary_metric,
                threshold_value=gate.primary_metric,
                detail=f"Candidate contains primary metric '{gate.primary_metric}'.",
            )
        )
    for regime in gate.required_regimes:
        if regime not in candidate_metrics:
            detail = (
                f"Candidate has no validation fold for regime '{regime}'. "
                "All required regimes must be represented before approval."
            )
            reasons.append(detail)
            checks.append(
                PromotionGateCheck(
                    check_name=f"required_regime:{regime}",
                    status="failed",
                    actual_value="missing",
                    threshold_value="present",
                    detail=detail,
                )
            )
        else:
            checks.append(
                PromotionGateCheck(
                    check_name=f"required_regime:{regime}",
                    status="passed",
                    actual_value="present",
                    threshold_value="present",
                    detail=f"Candidate covers required regime '{regime}'.",
                )
            )

    if baseline is not None:
        baseline_metrics = _group_metrics(baseline.validation_metrics, gate.primary_metric)
        shared_regimes = sorted(set(candidate_metrics) & set(baseline_metrics))
        for regime in shared_regimes:
            regime_deltas[regime] = candidate_metrics[regime] - baseline_metrics[regime]

        if candidate.algorithm_family.lower() in {item.lower() for item in gate.deep_model_families}:
            if not shared_regimes:
                detail = "Deep candidate has no shared regime metrics against baseline."
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name="deep_shared_regimes",
                        status="failed",
                        actual_value=0,
                        threshold_value=1,
                        detail=detail,
                    )
                )
            for regime in shared_regimes:
                if regime_deltas[regime] <= gate.minimum_primary_metric_delta:
                    detail = f"Deep candidate does not exceed baseline in regime '{regime}' by required margin."
                    reasons.append(detail)
                    checks.append(
                        PromotionGateCheck(
                            check_name=f"deep_regime_delta:{regime}",
                            status="failed",
                            actual_value=regime_deltas[regime],
                            threshold_value=gate.minimum_primary_metric_delta,
                            detail=detail,
                        )
                    )
                else:
                    checks.append(
                        PromotionGateCheck(
                            check_name=f"deep_regime_delta:{regime}",
                            status="passed",
                            actual_value=regime_deltas[regime],
                            threshold_value=gate.minimum_primary_metric_delta,
                            detail=f"Deep candidate exceeds baseline in regime '{regime}'.",
                        )
                    )

    candidate_precision = _mean_metric(candidate.validation_metrics, "top_bucket_alert_precision")
    baseline_precision = None if baseline is None else _mean_metric(baseline.validation_metrics, "top_bucket_alert_precision")
    if candidate_precision is not None and candidate_precision < gate.minimum_alert_precision:
        detail = f"Candidate alert precision {candidate_precision:.3f} is below minimum {gate.minimum_alert_precision:.3f}."
        reasons.append(detail)
        checks.append(
            PromotionGateCheck(
                check_name="minimum_alert_precision",
                status="failed",
                actual_value=round(candidate_precision, 6),
                threshold_value=gate.minimum_alert_precision,
                detail=detail,
            )
        )
    elif candidate_precision is not None:
        checks.append(
            PromotionGateCheck(
                check_name="minimum_alert_precision",
                status="passed",
                actual_value=round(candidate_precision, 6),
                threshold_value=gate.minimum_alert_precision,
                detail="Candidate alert precision meets minimum.",
            )
        )
    if (
        candidate_precision is not None
        and baseline_precision is not None
        and candidate_precision < baseline_precision
    ):
        detail = (
            f"Candidate alert precision {candidate_precision:.3f} is below champion "
            f"{baseline_precision:.3f}."
        )
        reasons.append(detail)
        checks.append(
            PromotionGateCheck(
                check_name="baseline_alert_precision_guardrail",
                status="failed",
                actual_value=round(candidate_precision, 6),
                threshold_value=round(baseline_precision, 6),
                detail=detail,
            )
        )
    elif candidate_precision is not None and baseline_precision is not None:
        checks.append(
            PromotionGateCheck(
                check_name="baseline_alert_precision_guardrail",
                status="passed",
                actual_value=round(candidate_precision, 6),
                threshold_value=round(baseline_precision, 6),
                detail="Candidate alert precision is not below champion.",
            )
        )

    candidate_auroc = _mean_metric(candidate.validation_metrics, "auc_roc")
    if candidate_auroc is not None and candidate_auroc < gate.min_auroc:
        detail = f"Candidate AUROC {candidate_auroc:.3f} is below minimum {gate.min_auroc:.3f}."
        reasons.append(detail)
        checks.append(
            PromotionGateCheck(
                check_name="minimum_auroc",
                status="failed",
                actual_value=round(candidate_auroc, 6),
                threshold_value=gate.min_auroc,
                detail=detail,
            )
        )
    elif candidate_auroc is not None:
        checks.append(
            PromotionGateCheck(
                check_name="minimum_auroc",
                status="passed",
                actual_value=round(candidate_auroc, 6),
                threshold_value=gate.min_auroc,
                detail="Candidate AUROC meets minimum.",
            )
        )

    candidate_ece = _mean_metric(candidate.validation_metrics, "expected_calibration_error")
    if candidate_ece is not None and candidate_ece > gate.max_ece:
        detail = f"Candidate ECE {candidate_ece:.3f} exceeds maximum {gate.max_ece:.3f}."
        reasons.append(detail)
        checks.append(
            PromotionGateCheck(
                check_name="maximum_ece",
                status="failed",
                actual_value=round(candidate_ece, 6),
                threshold_value=gate.max_ece,
                detail=detail,
            )
        )
    elif candidate_ece is not None:
        checks.append(
            PromotionGateCheck(
                check_name="maximum_ece",
                status="passed",
                actual_value=round(candidate_ece, 6),
                threshold_value=gate.max_ece,
                detail="Candidate ECE is within limit.",
            )
        )

    candidate_brier = _mean_metric(candidate.validation_metrics, "brier_score")
    baseline_brier = None if baseline is None else _mean_metric(baseline.validation_metrics, "brier_score")
    if candidate_brier is not None and baseline_brier is not None:
        brier_delta = candidate_brier - baseline_brier
        if brier_delta > gate.max_brier_delta_vs_baseline:
            detail = (
                f"Candidate Brier score {candidate_brier:.3f} is worse than champion by {brier_delta:.3f}, "
                f"above allowed delta {gate.max_brier_delta_vs_baseline:.3f}."
            )
            reasons.append(detail)
            checks.append(
                PromotionGateCheck(
                    check_name="brier_delta_vs_baseline",
                    status="failed",
                    actual_value=round(brier_delta, 6),
                    threshold_value=gate.max_brier_delta_vs_baseline,
                    detail=detail,
                )
            )
        else:
            checks.append(
                PromotionGateCheck(
                    check_name="brier_delta_vs_baseline",
                    status="passed",
                    actual_value=round(brier_delta, 6),
                    threshold_value=gate.max_brier_delta_vs_baseline,
                    detail="Candidate Brier score is within allowed delta vs champion.",
                )
            )

    candidate_drawdown_lift = _mean_metric(candidate.validation_metrics, "top_bucket_drawdown_lift")
    if candidate_drawdown_lift is not None and candidate_drawdown_lift <= gate.min_drawdown_lift:
        detail = (
            f"Candidate drawdown lift {candidate_drawdown_lift:.3f} does not exceed "
            f"minimum {gate.min_drawdown_lift:.3f}."
        )
        reasons.append(detail)
        checks.append(
            PromotionGateCheck(
                check_name="minimum_drawdown_lift",
                status="failed",
                actual_value=round(candidate_drawdown_lift, 6),
                threshold_value=gate.min_drawdown_lift,
                detail=detail,
            )
        )
    elif candidate_drawdown_lift is not None:
        checks.append(
            PromotionGateCheck(
                check_name="minimum_drawdown_lift",
                status="passed",
                actual_value=round(candidate_drawdown_lift, 6),
                threshold_value=gate.min_drawdown_lift,
                detail="Candidate drawdown lift meets minimum.",
            )
        )

    if candidate_fold_results and baseline_fold_results:
        market_deltas = _market_auroc_deltas(candidate_fold_results, baseline_fold_results)
        for market, delta in sorted(market_deltas.items()):
            if delta < -gate.max_market_auroc_drop_vs_baseline:
                detail = (
                    f"Candidate AUROC in market '{market}' trails champion by {abs(delta):.3f}, "
                    f"beyond allowed drop {gate.max_market_auroc_drop_vs_baseline:.3f}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name=f"market_auroc_delta:{market}",
                        status="failed",
                        actual_value=round(delta, 6),
                        threshold_value=-gate.max_market_auroc_drop_vs_baseline,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    PromotionGateCheck(
                        check_name=f"market_auroc_delta:{market}",
                        status="passed",
                        actual_value=round(delta, 6),
                        threshold_value=-gate.max_market_auroc_drop_vs_baseline,
                    detail=f"Candidate AUROC in market '{market}' is within the allowed drop vs champion.",
                )
            )

        coverage_group_deltas = _coverage_group_auroc_deltas(
            candidate_fold_results,
            baseline_fold_results,
            minimum_count=gate.minimum_coverage_group_validation_prediction_count,
        )
        for coverage_group, delta in sorted(coverage_group_deltas.items()):
            if delta < -gate.max_coverage_group_auroc_drop_vs_baseline:
                detail = (
                    f"Candidate AUROC in coverage group '{coverage_group}' trails champion by {abs(delta):.3f}, "
                    f"beyond allowed drop {gate.max_coverage_group_auroc_drop_vs_baseline:.3f}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name=f"coverage_group_auroc_delta:{coverage_group}",
                        status="failed",
                        actual_value=round(delta, 6),
                        threshold_value=-gate.max_coverage_group_auroc_drop_vs_baseline,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    PromotionGateCheck(
                        check_name=f"coverage_group_auroc_delta:{coverage_group}",
                        status="passed",
                        actual_value=round(delta, 6),
                        threshold_value=-gate.max_coverage_group_auroc_drop_vs_baseline,
                        detail=(
                            f"Candidate AUROC in coverage group '{coverage_group}' is within "
                            "the allowed drop vs champion."
                        ),
                    )
                )

        positive_regime_count = _count_positive_regimes(candidate.validation_metrics, gate.required_regimes)
        if positive_regime_count < gate.minimum_positive_regime_count:
            detail = (
                f"Candidate has non-negative drawdown lift in only {positive_regime_count} required regimes; "
                f"minimum is {gate.minimum_positive_regime_count}."
            )
            reasons.append(detail)
            checks.append(
                PromotionGateCheck(
                    check_name="positive_regime_count",
                    status="failed",
                    actual_value=positive_regime_count,
                    threshold_value=gate.minimum_positive_regime_count,
                    detail=detail,
                )
            )
        else:
            checks.append(
                PromotionGateCheck(
                    check_name="positive_regime_count",
                    status="passed",
                    actual_value=positive_regime_count,
                    threshold_value=gate.minimum_positive_regime_count,
                    detail="Candidate clears the required number of positive regimes.",
                )
            )

        recent_delta = _recent_window_delta(
            candidate_fold_results,
            baseline_fold_results,
            metric_name=gate.primary_metric,
            window_count=gate.recent_window_count,
        )
        if recent_delta["all_worse"]:
            detail = (
                f"Candidate underperformed champion on the last {gate.recent_window_count} validation windows "
                f"for metric '{gate.primary_metric}'."
            )
            reasons.append(detail)
            checks.append(
                PromotionGateCheck(
                    check_name="recent_window_guardrail",
                    status="failed",
                    actual_value=json.dumps(recent_delta["candidate_values"]),
                    threshold_value=json.dumps(recent_delta["baseline_values"]),
                    detail=detail,
                )
            )
        else:
            checks.append(
                PromotionGateCheck(
                    check_name="recent_window_guardrail",
                    status="passed",
                    actual_value=json.dumps(recent_delta["candidate_values"]),
                    threshold_value=json.dumps(recent_delta["baseline_values"]),
                    detail="Candidate does not underperform champion across all recent validation windows.",
                )
            )

    if audit is not None:
        if audit.target_label is not None and audit.target_label.availability_ratio < gate.minimum_target_label_availability_ratio:
            detail = (
                "Target label availability "
                f"{audit.target_label.availability_ratio:.3f} is below minimum "
                f"{gate.minimum_target_label_availability_ratio:.3f} for task '{audit.target_label.target_name}'."
            )
            reasons.append(detail)
            checks.append(
                PromotionGateCheck(
                    check_name="target_label_availability",
                    status="failed",
                    actual_value=round(audit.target_label.availability_ratio, 6),
                    threshold_value=gate.minimum_target_label_availability_ratio,
                    detail=detail,
                )
            )
        elif audit.target_label is not None:
            checks.append(
                PromotionGateCheck(
                    check_name="target_label_availability",
                    status="passed",
                    actual_value=round(audit.target_label.availability_ratio, 6),
                    threshold_value=gate.minimum_target_label_availability_ratio,
                    detail="Target label availability meets minimum.",
                )
            )
        if audit.point_in_time_integrity is not None:
            leakage_count = audit.point_in_time_integrity.potential_future_leakage_issue_count
            if leakage_count > gate.maximum_potential_future_leakage_issue_count:
                detail = (
                    f"Potential future leakage issue count {leakage_count} exceeds maximum "
                    f"{gate.maximum_potential_future_leakage_issue_count}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name="potential_future_leakage_issue_count",
                        status="failed",
                        actual_value=leakage_count,
                        threshold_value=gate.maximum_potential_future_leakage_issue_count,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    PromotionGateCheck(
                        check_name="potential_future_leakage_issue_count",
                        status="passed",
                        actual_value=leakage_count,
                        threshold_value=gate.maximum_potential_future_leakage_issue_count,
                        detail="Potential future leakage issue count is within limit.",
                    )
                )
            sample_count = audit.sample_coverage.sample_count
            issue_ratio = (
                audit.point_in_time_integrity.samples_with_data_issues / sample_count
                if sample_count > 0
                else 0.0
            )
            if issue_ratio > gate.maximum_samples_with_data_issues_ratio:
                detail = (
                    f"Sample data-issue ratio {issue_ratio:.3f} exceeds maximum "
                    f"{gate.maximum_samples_with_data_issues_ratio:.3f}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name="sample_data_issue_ratio",
                        status="failed",
                        actual_value=round(issue_ratio, 6),
                        threshold_value=gate.maximum_samples_with_data_issues_ratio,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    PromotionGateCheck(
                        check_name="sample_data_issue_ratio",
                        status="passed",
                        actual_value=round(issue_ratio, 6),
                        threshold_value=gate.maximum_samples_with_data_issues_ratio,
                        detail="Sample data-issue ratio is within limit.",
                    )
                )
            samples_with_events_ratio = (
                audit.point_in_time_integrity.sample_count_with_events / sample_count
                if sample_count > 0
                else 0.0
            )
            if samples_with_events_ratio < gate.minimum_samples_with_events_ratio:
                detail = (
                    f"Samples-with-events ratio {samples_with_events_ratio:.3f} is below minimum "
                    f"{gate.minimum_samples_with_events_ratio:.3f}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name="samples_with_events_ratio",
                        status="failed",
                        actual_value=round(samples_with_events_ratio, 6),
                        threshold_value=gate.minimum_samples_with_events_ratio,
                        detail=detail,
                    )
                )
            elif gate.minimum_samples_with_events_ratio > 0:
                checks.append(
                    PromotionGateCheck(
                        check_name="samples_with_events_ratio",
                        status="passed",
                        actual_value=round(samples_with_events_ratio, 6),
                        threshold_value=gate.minimum_samples_with_events_ratio,
                        detail="Samples-with-events ratio meets minimum.",
                    )
                )
        if gate.minimum_required_regime_validation_prediction_count > 0:
            regime_coverage = (
                audit.regime_coverage
                if audit.regime_coverage
                else _regime_coverage_from_fold_results(candidate_fold_results or [])
            )
            covered_required_regimes = {
                item.regime for item in regime_coverage if item.regime in gate.required_regimes
            }
            if len(covered_required_regimes) < gate.minimum_positive_regime_count:
                detail = (
                    f"Candidate covers only {len(covered_required_regimes)} required regimes with validation predictions; "
                    f"minimum is {gate.minimum_positive_regime_count}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name="required_regime_coverage_count",
                        status="failed",
                        actual_value=len(covered_required_regimes),
                        threshold_value=gate.minimum_positive_regime_count,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    PromotionGateCheck(
                        check_name="required_regime_coverage_count",
                        status="passed",
                        actual_value=len(covered_required_regimes),
                        threshold_value=gate.minimum_positive_regime_count,
                        detail="Candidate covers enough required regimes with validation predictions.",
                    )
                )
            for regime in gate.required_regimes:
                regime_record = next((item for item in regime_coverage if item.regime == regime), None)
                if regime_record is None:
                    detail = f"Required regime coverage '{regime}' is absent in this validation run."
                    reasons.append(detail)
                    checks.append(
                        PromotionGateCheck(
                            check_name=f"required_regime_validation_prediction_count:{regime}",
                            status="failed",
                            actual_value="missing",
                            threshold_value=gate.minimum_required_regime_validation_prediction_count,
                            detail=detail,
                        )
                    )
                    continue
                if regime_record.validation_prediction_count < gate.minimum_required_regime_validation_prediction_count:
                    detail = (
                        f"Required regime '{regime}' validation prediction count "
                        f"{regime_record.validation_prediction_count} is below minimum "
                        f"{gate.minimum_required_regime_validation_prediction_count}."
                    )
                    reasons.append(detail)
                    checks.append(
                        PromotionGateCheck(
                            check_name=f"required_regime_validation_prediction_count:{regime}",
                            status="failed",
                            actual_value=regime_record.validation_prediction_count,
                            threshold_value=gate.minimum_required_regime_validation_prediction_count,
                            detail=detail,
                        )
                    )
                else:
                    checks.append(
                        PromotionGateCheck(
                            check_name=f"required_regime_validation_prediction_count:{regime}",
                            status="passed",
                            actual_value=regime_record.validation_prediction_count,
                            threshold_value=gate.minimum_required_regime_validation_prediction_count,
                            detail=f"Required regime '{regime}' has enough validation predictions.",
                        )
                    )
        for reference_type in _required_reference_types(candidate.task_name):
            reference_record = next((item for item in audit.reference_coverage if item.reference_type == reference_type), None)
            if reference_record is None:
                detail = f"Required reference coverage '{reference_type}' is missing from audit summary."
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name=f"required_reference_presence:{reference_type}",
                        status="failed",
                        actual_value="missing",
                        threshold_value="present",
                        detail=detail,
                    )
                )
                continue
            if reference_record.configured_sample_count == 0:
                detail = f"Required reference '{reference_type}' is not configured for any training samples."
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name=f"required_reference_presence:{reference_type}",
                        status="failed",
                        actual_value=0,
                        threshold_value=1,
                        detail=detail,
                    )
                )
                continue
            checks.append(
                PromotionGateCheck(
                    check_name=f"required_reference_presence:{reference_type}",
                    status="passed",
                    actual_value=reference_record.configured_sample_count,
                    threshold_value=1,
                    detail=f"Required reference '{reference_type}' is configured.",
                )
            )
            configured_ratio = (
                reference_record.configured_sample_count / audit.sample_coverage.sample_count
                if audit.sample_coverage.sample_count > 0
                else 0.0
            )
            if configured_ratio < gate.minimum_reference_configured_ratio:
                detail = (
                    f"Required reference '{reference_type}' configured ratio "
                    f"{configured_ratio:.3f} is below minimum "
                    f"{gate.minimum_reference_configured_ratio:.3f}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name=f"required_reference_configured_ratio:{reference_type}",
                        status="failed",
                        actual_value=round(configured_ratio, 6),
                        threshold_value=gate.minimum_reference_configured_ratio,
                        detail=detail,
                    )
                )
            elif gate.minimum_reference_configured_ratio > 0:
                checks.append(
                    PromotionGateCheck(
                        check_name=f"required_reference_configured_ratio:{reference_type}",
                        status="passed",
                        actual_value=round(configured_ratio, 6),
                        threshold_value=gate.minimum_reference_configured_ratio,
                        detail=f"Required reference '{reference_type}' configured ratio meets minimum.",
                    )
                )
            if reference_record.feature_backed_ratio < gate.minimum_reference_feature_backed_ratio:
                detail = (
                    f"Required reference '{reference_type}' feature-backed ratio "
                    f"{reference_record.feature_backed_ratio:.3f} is below minimum "
                    f"{gate.minimum_reference_feature_backed_ratio:.3f}."
                )
                reasons.append(detail)
                checks.append(
                    PromotionGateCheck(
                        check_name=f"required_reference_feature_backed_ratio:{reference_type}",
                        status="failed",
                        actual_value=round(reference_record.feature_backed_ratio, 6),
                        threshold_value=gate.minimum_reference_feature_backed_ratio,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    PromotionGateCheck(
                        check_name=f"required_reference_feature_backed_ratio:{reference_type}",
                        status="passed",
                        actual_value=round(reference_record.feature_backed_ratio, 6),
                        threshold_value=gate.minimum_reference_feature_backed_ratio,
                        detail=f"Required reference '{reference_type}' feature-backed ratio meets minimum.",
                    )
                )

    return PromotionGateResult(
        candidate_model_id=candidate.model_id,
        baseline_model_id=None if baseline is None else baseline.model_id,
        eligible=not reasons,
        reasons=reasons,
        regime_deltas=regime_deltas,
        effective_policy=gate,
        checks=checks,
    )


def _group_metrics(metrics: list[FoldMetric], metric_name: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for metric in metrics:
        if metric.metric_name == metric_name:
            grouped[metric.regime].append(metric.metric_value)
    return {regime: sum(values) / len(values) for regime, values in grouped.items()}


def _mean_metric(metrics: list[FoldMetric], metric_name: str) -> float | None:
    values = [metric.metric_value for metric in metrics if metric.metric_name == metric_name]
    if not values:
        return None
    return sum(values) / len(values)


def _required_reference_types(task_name: str) -> list[str]:
    if task_name.startswith("industry_excess_return_"):
        return ["sector"]
    if task_name.startswith("excess_return_"):
        return ["benchmark"]
    return []


def resolve_promotion_gate_policy(*, task_name: str, policy: PromotionGatePolicy | None = None) -> PromotionGatePolicy:
    base = (policy or PromotionGatePolicy()).model_copy(deep=True)

    if task_name.startswith("future_max_drawdown_"):
        return base.model_copy(
            update={
                "min_auroc": max(base.min_auroc, 0.68),
                "minimum_target_label_availability_ratio": max(base.minimum_target_label_availability_ratio, 0.75),
                "maximum_samples_with_data_issues_ratio": min(base.maximum_samples_with_data_issues_ratio, 0.30),
                "minimum_positive_regime_count": max(base.minimum_positive_regime_count, 3),
                "recent_window_count": max(base.recent_window_count, 2),
                "minimum_required_regime_validation_prediction_count": max(
                    base.minimum_required_regime_validation_prediction_count,
                    1,
                ),
                "required_regimes": ["bull", "bear", "range", "high_vol"],
            }
        )

    if task_name.startswith("industry_excess_return_"):
        return base.model_copy(
            update={
                "minimum_target_label_availability_ratio": max(base.minimum_target_label_availability_ratio, 0.70),
                "minimum_reference_configured_ratio": max(base.minimum_reference_configured_ratio, 0.90),
                "minimum_reference_feature_backed_ratio": max(base.minimum_reference_feature_backed_ratio, 0.80),
            }
        )

    if task_name.startswith("excess_return_"):
        return base.model_copy(
            update={
                "minimum_target_label_availability_ratio": max(base.minimum_target_label_availability_ratio, 0.70),
                "minimum_reference_configured_ratio": max(base.minimum_reference_configured_ratio, 0.85),
                "minimum_reference_feature_backed_ratio": max(base.minimum_reference_feature_backed_ratio, 0.75),
            }
        )

    if task_name.startswith("news_event_shock_") or task_name.startswith("post_earnings_abnormal_move_"):
        return base.model_copy(
            update={
                "minimum_target_label_availability_ratio": max(base.minimum_target_label_availability_ratio, 0.50),
                "minimum_samples_with_events_ratio": max(base.minimum_samples_with_events_ratio, 0.30),
                "maximum_samples_with_data_issues_ratio": min(base.maximum_samples_with_data_issues_ratio, 0.25),
            }
        )

    return base


def _market_auroc_deltas(candidate_fold_results: list, baseline_fold_results: list) -> dict[str, float]:
    candidate_predictions = _flatten_predictions(candidate_fold_results)
    baseline_predictions = _flatten_predictions(baseline_fold_results)
    candidate_scores = _market_auroc(candidate_predictions)
    baseline_scores = _market_auroc(baseline_predictions)
    shared_markets = sorted(set(candidate_scores) & set(baseline_scores))
    return {market: candidate_scores[market] - baseline_scores[market] for market in shared_markets}


def _market_auroc(predictions: list) -> dict[str, float]:
    return _group_auroc(predictions, attribute="market", minimum_count=1)


def _coverage_group_auroc_deltas(
    candidate_fold_results: list,
    baseline_fold_results: list,
    *,
    minimum_count: int,
) -> dict[str, float]:
    candidate_predictions = _flatten_predictions(candidate_fold_results)
    baseline_predictions = _flatten_predictions(baseline_fold_results)
    candidate_scores = _group_auroc(candidate_predictions, attribute="coverage_group", minimum_count=minimum_count)
    baseline_scores = _group_auroc(baseline_predictions, attribute="coverage_group", minimum_count=minimum_count)
    shared_groups = sorted(set(candidate_scores) & set(baseline_scores))
    return {group: candidate_scores[group] - baseline_scores[group] for group in shared_groups}


def _group_auroc(predictions: list, *, attribute: str, minimum_count: int) -> dict[str, float]:
    from investment_research.training.evaluation import compute_auc_roc

    grouped: dict[str, list] = defaultdict(list)
    for prediction in predictions:
        key = getattr(prediction, attribute, None)
        if key is None or prediction.actual_label is None:
            continue
        grouped[str(key)].append(prediction)
    scores: dict[str, float] = {}
    for key, items in grouped.items():
        if len(items) < minimum_count:
            continue
        labels = [int(item.actual_label) for item in items]
        values = [float(item.calibrated_score) for item in items]
        auc = compute_auc_roc(labels, values)
        if auc is not None:
            scores[key] = auc
    return scores


def _count_positive_regimes(metrics: list[FoldMetric], required_regimes: list[str]) -> int:
    grouped = _group_metrics(metrics, "top_bucket_drawdown_lift")
    return sum(1 for regime in required_regimes if grouped.get(regime, float("-inf")) >= 0)


def _regime_coverage_from_fold_results(fold_results: list) -> list[RegimeCoverageRecord]:
    grouped: dict[str, list] = defaultdict(list)
    for fold_result in fold_results:
        grouped[fold_result.fold.regime].append(fold_result)
    records: list[RegimeCoverageRecord] = []
    for regime, items in sorted(grouped.items()):
        records.append(
            RegimeCoverageRecord(
                regime=regime,
                fold_count=len(items),
                validation_prediction_count=sum(len(item.predictions) for item in items),
                validation_start=min(item.fold.validation_start for item in items),
                validation_end=max(item.fold.validation_end for item in items),
            )
        )
    return records


def _recent_window_delta(candidate_fold_results: list, baseline_fold_results: list, *, metric_name: str, window_count: int) -> dict[str, object]:
    candidate_by_fold = {fold_result.fold.fold_id: fold_result for fold_result in candidate_fold_results}
    baseline_by_fold = {fold_result.fold.fold_id: fold_result for fold_result in baseline_fold_results}
    shared_fold_ids = sorted(
        set(candidate_by_fold) & set(baseline_by_fold),
        key=lambda fold_id: candidate_by_fold[fold_id].fold.validation_end,
    )
    recent_fold_ids = shared_fold_ids[-window_count:]
    candidate_values: list[float] = []
    baseline_values: list[float] = []
    for fold_id in recent_fold_ids:
        candidate_metric = _fold_metric_value(candidate_by_fold[fold_id].metrics, metric_name)
        baseline_metric = _fold_metric_value(baseline_by_fold[fold_id].metrics, metric_name)
        if candidate_metric is None or baseline_metric is None:
            continue
        candidate_values.append(candidate_metric)
        baseline_values.append(baseline_metric)
    return {
        "candidate_values": [round(value, 6) for value in candidate_values],
        "baseline_values": [round(value, 6) for value in baseline_values],
        "all_worse": bool(candidate_values) and len(candidate_values) == len(baseline_values) and all(
            candidate_value < baseline_value
            for candidate_value, baseline_value in zip(candidate_values, baseline_values)
        ),
    }


def _fold_metric_value(metrics: list[FoldMetric], metric_name: str) -> float | None:
    for metric in metrics:
        if metric.metric_name == metric_name:
            return metric.metric_value
    return None


def _flatten_predictions(fold_results: list) -> list:
    return [prediction for fold_result in fold_results for prediction in fold_result.predictions]


def load_gate_rules_from_yaml(path: Path | None = None) -> PromotionGatePolicy | None:
    try:
        import yaml
    except Exception:
        return None

    config_path = path or Path(__file__).resolve().parents[3] / "config" / "gate_rules.yaml"
    if not config_path.exists():
        return None
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    gate_payload = payload.get("promotion_gate", {})
    if not isinstance(gate_payload, dict):
        return None
    mapped = {
        "primary_metric": gate_payload.get("primary_metric"),
        "minimum_primary_metric_delta": gate_payload.get("minimum_primary_metric_delta"),
        "min_drawdown_lift": gate_payload.get("min_drawdown_lift"),
        "min_auroc": gate_payload.get("minimum_auroc"),
        "max_ece": gate_payload.get("max_ece"),
        "max_brier_delta_vs_baseline": gate_payload.get("max_brier_delta_vs_baseline"),
        "max_market_auroc_drop_vs_baseline": gate_payload.get("max_market_auroc_drop_vs_baseline"),
        "max_coverage_group_auroc_drop_vs_baseline": gate_payload.get(
            "max_coverage_group_auroc_drop_vs_baseline"
        ),
        "minimum_coverage_group_validation_prediction_count": gate_payload.get(
            "minimum_coverage_group_validation_prediction_count"
        ),
        "minimum_positive_regime_count": gate_payload.get("minimum_positive_regime_count"),
        "recent_window_count": gate_payload.get("recent_window_count"),
        "require_models": gate_payload.get("require_models"),
        "minimum_alert_precision": gate_payload.get("minimum_alert_precision"),
        "minimum_target_label_availability_ratio": gate_payload.get("minimum_target_label_availability_ratio"),
        "minimum_reference_feature_backed_ratio": gate_payload.get("minimum_reference_feature_backed_ratio"),
        "minimum_reference_configured_ratio": gate_payload.get("minimum_reference_configured_ratio"),
        "minimum_samples_with_events_ratio": gate_payload.get("minimum_samples_with_events_ratio"),
        "minimum_required_regime_validation_prediction_count": gate_payload.get(
            "minimum_required_regime_validation_prediction_count"
        ),
        "maximum_potential_future_leakage_issue_count": gate_payload.get(
            "maximum_potential_future_leakage_issue_count"
        ),
        "maximum_samples_with_data_issues_ratio": gate_payload.get("maximum_samples_with_data_issues_ratio"),
        "required_regimes": gate_payload.get("required_regimes"),
    }
    clean = {key: value for key, value in mapped.items() if value is not None}
    deep_payload = payload.get("deep_model_gate", {})
    if isinstance(deep_payload, dict) and deep_payload.get("deep_model_families") is not None:
        clean["deep_model_families"] = deep_payload.get("deep_model_families")
    return PromotionGatePolicy(**clean)


def build_gate_scorecard(
    result: PromotionGateResult,
    model_card: ModelCard,
) -> ModelCard:
    """Append a structured promotion gate scorecard to a model card."""
    policy_name = result.effective_policy.primary_metric if result.effective_policy else "N/A"
    scorecard_lines = [
        "=" * 60,
        "          PROMOTION GATE SCORECARD",
        "=" * 60,
        f"Candidate:   {result.candidate_model_id}",
        f"Baseline:    {result.baseline_model_id or 'N/A'}",
        f"Eligible:    {result.eligible}",
        f"Policy:      {policy_name}",
        "",
        "-- OVERALL RESULT --",
        f"Eligible for approval: {'YES' if result.eligible else 'NO'}",
    ]

    if not result.eligible and result.reasons:
        scorecard_lines.extend(["", "-- REJECTION REASONS --"])
        for index, reason in enumerate(result.reasons, 1):
            scorecard_lines.append(f"  {index}. {reason}")

    if result.regime_deltas:
        scorecard_lines.extend(["", "-- REGIME DELTAS (Candidate - Baseline) --"])
        for regime, delta in sorted(result.regime_deltas.items()):
            sign = "+" if delta > 0 else ""
            scorecard_lines.append(f"  {regime}: {sign}{delta:.6f}")

    checks_by_status: dict[str, list[PromotionGateCheck]] = {"passed": [], "failed": [], "skipped": []}
    for check in result.checks:
        checks_by_status.setdefault(check.status, []).append(check)

    if checks_by_status["failed"]:
        scorecard_lines.extend(["", f"-- FAILED CHECKS ({len(checks_by_status['failed'])}) --"])
        for check in checks_by_status["failed"]:
            scorecard_lines.append(f"  [FAIL] {check.check_name}")
            scorecard_lines.append(f"         {check.detail}")

    if checks_by_status["passed"]:
        scorecard_lines.extend(["", f"-- PASSED CHECKS ({len(checks_by_status['passed'])}) --"])
        for check in checks_by_status["passed"]:
            scorecard_lines.append(f"  [PASS] {check.check_name}")

    if checks_by_status.get("skipped"):
        scorecard_lines.extend(["", f"-- SKIPPED CHECKS ({len(checks_by_status['skipped'])}) --"])
        for check in checks_by_status["skipped"]:
            scorecard_lines.append(f"  [SKIP] {check.check_name}")

    scorecard_lines.extend(
        [
            "",
            "-- PASS/FAIL SUMMARY --",
            f"  Passed:   {len(checks_by_status['passed'])}",
            f"  Failed:   {len(checks_by_status['failed'])}",
            f"  Skipped:  {len(checks_by_status.get('skipped', []))}",
            "=" * 60,
        ]
    )

    model_card.notes.append("\n".join(scorecard_lines))
    return model_card


def summarize_gate_scorecard(result: PromotionGateResult) -> dict[str, object]:
    """Return a lightweight scorecard summary for dashboards and reports."""
    checks_by_status: dict[str, list[PromotionGateCheck]] = {"passed": [], "failed": [], "skipped": []}
    for check in result.checks:
        checks_by_status.setdefault(check.status, []).append(check)

    return {
        "eligible": result.eligible,
        "failure_count": len(checks_by_status["failed"]),
        "pass_count": len(checks_by_status["passed"]),
        "skip_count": len(checks_by_status.get("skipped", [])),
        "reasons": result.reasons,
        "regime_deltas": result.regime_deltas,
        "failed_checks": [check.check_name for check in checks_by_status["failed"]],
    }


def enrich_experiment_with_scorecard(result: TrainingExperimentResult) -> TrainingExperimentResult:
    """Attach the promotion gate scorecard without changing eligibility."""
    if result.promotion_result is not None:
        build_gate_scorecard(result.promotion_result, result.model_card)
    return result
