from datetime import date

from investment_research.training.models import (
    CalibratedPrediction,
    FoldMetric,
    ModelCard,
    PointInTimeIntegritySummary,
    PromotionGatePolicy,
    ReferenceCoverageRecord,
    RegimeCoverageRecord,
    TargetLabelAuditSummary,
    TrainingExperimentAuditSummary,
    TrainingSampleCoverageSummary,
    WalkForwardFold,
    WalkForwardFoldResult,
)
from investment_research.training.promotion import evaluate_promotion_gate, resolve_promotion_gate_policy


def _card(
    model_id: str,
    *,
    family: str,
    bull: float,
    bear: float,
    precision: float,
    range_value: float | None = None,
    high_vol: float | None = None,
    auc: float = 0.72,
    ece: float = 0.10,
    brier: float = 0.20,
) -> ModelCard:
    return ModelCard(
        model_id=model_id,
        task_name="future_max_drawdown_20d",
        algorithm_family=family,
        algorithm_name=family,
        data_version="d-v1",
        feature_version="f-v1",
        label_version="l-v1",
        training_window_start=date(2023, 1, 1),
        training_window_end=date(2025, 12, 31),
        validation_metrics=[
            FoldMetric(fold_id="wf-001", regime="bull", metric_name="top_bucket_drawdown_lift", metric_value=bull),
            FoldMetric(fold_id="wf-002", regime="bear", metric_name="top_bucket_drawdown_lift", metric_value=bear),
            FoldMetric(
                fold_id="wf-003",
                regime="range",
                metric_name="top_bucket_drawdown_lift",
                metric_value=bull if range_value is None else range_value,
            ),
            FoldMetric(
                fold_id="wf-004",
                regime="high_vol",
                metric_name="top_bucket_drawdown_lift",
                metric_value=bear if high_vol is None else high_vol,
            ),
            FoldMetric(fold_id="wf-003", regime="bull", metric_name="top_bucket_alert_precision", metric_value=precision),
            FoldMetric(fold_id="wf-001", regime="bull", metric_name="auc_roc", metric_value=auc),
            FoldMetric(fold_id="wf-002", regime="bear", metric_name="auc_roc", metric_value=auc),
            FoldMetric(fold_id="wf-001", regime="bull", metric_name="expected_calibration_error", metric_value=ece),
            FoldMetric(fold_id="wf-001", regime="bull", metric_name="brier_score", metric_value=brier),
        ],
    )


def test_deep_candidate_must_outperform_baseline_across_required_regimes() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    weak_deep = _card("deep", family="patchtst", bull=0.02, bear=0.08, precision=0.7)

    result = evaluate_promotion_gate(candidate=weak_deep, baseline=baseline, policy=PromotionGatePolicy())

    assert result.eligible is False
    assert result.reasons


def test_candidate_passing_gate_is_eligible() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    strong_deep = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75, range_value=0.07, high_vol=0.08, brier=0.19)

    result = evaluate_promotion_gate(candidate=strong_deep, baseline=baseline, policy=PromotionGatePolicy())

    assert result.eligible is True
    assert result.regime_deltas["bull"] > 0
    assert result.effective_policy is not None
    assert result.checks
    assert any(check.check_name == "minimum_alert_precision" for check in result.checks)


def test_candidate_fails_when_high_vol_is_absent_even_with_three_positive_regimes() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card(
        "random-forest",
        family="random_forest",
        bull=0.06,
        bear=0.07,
        range_value=0.08,
        high_vol=0.09,
        precision=0.75,
        auc=0.72,
        ece=0.10,
        brier=0.19,
    )
    candidate = candidate.model_copy(
        update={
            "validation_metrics": [
                metric for metric in candidate.validation_metrics if metric.regime != "high_vol"
            ]
        }
    )
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=120),
        regime_coverage=[
            RegimeCoverageRecord(regime="bull", fold_count=1, validation_prediction_count=60),
            RegimeCoverageRecord(regime="bear", fold_count=1, validation_prediction_count=60),
            RegimeCoverageRecord(regime="range", fold_count=1, validation_prediction_count=60),
        ],
    )

    result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any(
        check.check_name == "required_regime:high_vol" and check.status == "failed"
        for check in result.checks
    )
    assert any(
        check.check_name == "required_regime_validation_prediction_count:high_vol" and check.status == "failed"
        for check in result.checks
    )


def test_candidate_fails_when_coverage_group_auroc_regresses() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card(
        "random-forest",
        family="random_forest",
        bull=0.06,
        bear=0.07,
        range_value=0.08,
        high_vol=0.09,
        precision=0.75,
        auc=0.72,
        ece=0.10,
        brier=0.19,
    )
    fold = WalkForwardFold(
        fold_id="wf-001",
        train_start=date(2024, 1, 1),
        train_end=date(2024, 6, 30),
        validation_start=date(2024, 7, 1),
        validation_end=date(2024, 8, 31),
        regime="bull",
    )

    def _prediction(score: float, label: int) -> CalibratedPrediction:
        return CalibratedPrediction(
            symbol="AAPL",
            as_of_date=date(2024, 7, 1),
            raw_score=score,
            calibrated_score=score,
            target_name="future_max_drawdown_20d",
            predicted_label=label,
            market="us",
            coverage_group="china_adr",
            actual_label=label,
        )

    baseline_predictions = [_prediction(score, label) for score, label in [(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]]
    candidate_predictions = [_prediction(score, label) for score, label in [(0.1, 1), (0.2, 1), (0.8, 0), (0.9, 0)]]
    baseline_folds = [WalkForwardFoldResult(fold=fold, predictions=baseline_predictions)]
    candidate_folds = [WalkForwardFoldResult(fold=fold, predictions=candidate_predictions)]
    policy = PromotionGatePolicy(minimum_coverage_group_validation_prediction_count=1)

    result = evaluate_promotion_gate(
        candidate=candidate,
        baseline=baseline,
        policy=policy,
        candidate_fold_results=candidate_folds,
        baseline_fold_results=baseline_folds,
    )

    assert result.eligible is False
    assert any(
        check.check_name == "coverage_group_auroc_delta:china_adr" and check.status == "failed"
        for check in result.checks
    )


def test_candidate_fails_when_fewer_than_three_required_regimes_have_validation_coverage() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("random-forest", family="random_forest", bull=0.06, bear=0.07, precision=0.75, brier=0.19)
    candidate = candidate.model_copy(
        update={
            "validation_metrics": [
                metric for metric in candidate.validation_metrics if metric.regime in {"bull", "bear"}
            ]
        }
    )
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=120),
        regime_coverage=[
            RegimeCoverageRecord(regime="bull", fold_count=1, validation_prediction_count=60),
            RegimeCoverageRecord(regime="bear", fold_count=1, validation_prediction_count=60),
        ],
    )

    result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("covers only 2 required regimes" in reason for reason in result.reasons)


def test_candidate_fails_gate_when_target_label_is_too_sparse() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75)
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=12),
        target_label=TargetLabelAuditSummary(
            target_name="industry_excess_return_20d",
            available_count=4,
            missing_count=8,
            availability_ratio=0.333,
        ),
        reference_coverage=[
            ReferenceCoverageRecord(
                reference_type="sector",
                configured_sample_count=12,
                missing_configuration_count=0,
                feature_backed_sample_count=12,
                feature_backed_ratio=1.0,
                reference_symbols=["XLK"],
            )
        ],
    )

    result = evaluate_promotion_gate(candidate=candidate.model_copy(update={"task_name": "industry_excess_return_20d"}), baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("Target label availability" in reason for reason in result.reasons)


def test_candidate_fails_gate_when_required_reference_coverage_is_weak() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75)
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=12),
        target_label=TargetLabelAuditSummary(
            target_name="industry_excess_return_20d",
            available_count=12,
            missing_count=0,
            availability_ratio=1.0,
        ),
        reference_coverage=[
            ReferenceCoverageRecord(
                reference_type="sector",
                configured_sample_count=12,
                missing_configuration_count=0,
                feature_backed_sample_count=4,
                feature_backed_ratio=0.333,
                reference_symbols=["XLK"],
            )
        ],
    )

    result = evaluate_promotion_gate(candidate=candidate.model_copy(update={"task_name": "industry_excess_return_20d"}), baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("feature-backed ratio" in reason for reason in result.reasons)
    assert any(check.check_name == "required_reference_feature_backed_ratio:sector" and check.status == "failed" for check in result.checks)


def test_candidate_fails_gate_when_future_leakage_is_detected() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75)
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=12),
        point_in_time_integrity=PointInTimeIntegritySummary(
            sample_count_with_events=8,
            sample_count_without_events=4,
            total_point_in_time_events=10,
            samples_with_data_issues=1,
            total_data_issue_count=1,
            potential_future_leakage_issue_count=1,
            potential_future_leakage_issue_codes={"future_event": 1},
        ),
    )

    result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("Potential future leakage issue count" in reason for reason in result.reasons)


def test_candidate_fails_gate_when_data_issue_ratio_is_too_high() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75)
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=10),
        point_in_time_integrity=PointInTimeIntegritySummary(
            sample_count_with_events=8,
            sample_count_without_events=2,
            total_point_in_time_events=12,
            samples_with_data_issues=5,
            total_data_issue_count=8,
            potential_future_leakage_issue_count=0,
            potential_future_leakage_issue_codes={},
        ),
    )

    result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("Sample data-issue ratio" in reason for reason in result.reasons)


def test_candidate_fails_gate_when_event_sample_density_is_too_low() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75).model_copy(
        update={"task_name": "news_event_shock_3d"}
    )
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=10),
        point_in_time_integrity=PointInTimeIntegritySummary(
            sample_count_with_events=2,
            sample_count_without_events=8,
            total_point_in_time_events=2,
            samples_with_data_issues=0,
            total_data_issue_count=0,
            potential_future_leakage_issue_count=0,
            potential_future_leakage_issue_codes={},
        ),
    )

    result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("Samples-with-events ratio" in reason for reason in result.reasons)


def test_candidate_fails_gate_when_reference_configuration_ratio_is_too_low() -> None:
    baseline = _card("baseline", family="linear_baseline", bull=0.03, bear=0.05, precision=0.7)
    candidate = _card("deep", family="patchtst", bull=0.06, bear=0.09, precision=0.75).model_copy(
        update={"task_name": "industry_excess_return_20d"}
    )
    audit = TrainingExperimentAuditSummary(
        sample_coverage=TrainingSampleCoverageSummary(sample_count=10),
        target_label=TargetLabelAuditSummary(
            target_name="industry_excess_return_20d",
            available_count=10,
            missing_count=0,
            availability_ratio=1.0,
        ),
        reference_coverage=[
            ReferenceCoverageRecord(
                reference_type="sector",
                configured_sample_count=6,
                missing_configuration_count=4,
                feature_backed_sample_count=6,
                feature_backed_ratio=1.0,
                reference_symbols=["XLK"],
            )
        ],
    )

    result = evaluate_promotion_gate(candidate=candidate, baseline=baseline, policy=PromotionGatePolicy(), audit=audit)

    assert result.eligible is False
    assert any("configured ratio" in reason for reason in result.reasons)


def test_task_specific_promotion_gate_policy_resolution() -> None:
    base = PromotionGatePolicy(
        minimum_target_label_availability_ratio=0.6,
        minimum_reference_feature_backed_ratio=0.6,
        minimum_reference_configured_ratio=0.6,
        minimum_samples_with_events_ratio=0.1,
        maximum_samples_with_data_issues_ratio=0.4,
        required_regimes=["bull"],
    )

    drawdown = resolve_promotion_gate_policy(task_name="future_max_drawdown_20d", policy=base)
    industry = resolve_promotion_gate_policy(task_name="industry_excess_return_20d", policy=base)
    event = resolve_promotion_gate_policy(task_name="news_event_shock_3d", policy=base)

    assert drawdown.minimum_target_label_availability_ratio == 0.75
    assert drawdown.maximum_samples_with_data_issues_ratio == 0.30
    assert drawdown.minimum_required_regime_validation_prediction_count == 1
    assert drawdown.required_regimes == ["bull", "bear", "range", "high_vol"]
    assert industry.minimum_reference_configured_ratio == 0.90
    assert industry.minimum_reference_feature_backed_ratio == 0.80
    assert event.minimum_samples_with_events_ratio == 0.30
    assert event.maximum_samples_with_data_issues_ratio == 0.25
