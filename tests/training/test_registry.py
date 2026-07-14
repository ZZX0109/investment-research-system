from datetime import date

from investment_research.training.models import (
    FoldMetric,
    ModelCard,
    ModelStatus,
    PointInTimeIntegritySummary,
    PromotionGatePolicy,
    TrainingExperimentAuditSummary,
    TrainingSampleCoverageSummary,
)
from investment_research.training.registry import TrainingRegistryService


def _card(model_id: str) -> ModelCard:
    return ModelCard(
        model_id=model_id,
        task_name="risk_multitask_v1",
        algorithm_family="tree",
        algorithm_name="lightgbm",
        data_version="prices-2026-07-06",
        feature_version="f-1",
        label_version="l-1",
        training_window_start=date(2023, 1, 1),
        training_window_end=date(2025, 12, 31),
        validation_metrics=[FoldMetric(fold_id="wf-001", regime="bull", metric_name="top_bucket_lift", metric_value=0.12)],
    )


def test_registry_requires_explicit_approval_and_supports_rollback(tmp_path) -> None:
    service = TrainingRegistryService(tmp_path / "registry.json")

    candidate_a = service.register_candidate(_card("model-a"))
    candidate_b = service.register_candidate(_card("model-b"))
    assert service.get_active_model("risk_multitask_v1") is None

    approved_a = service.approve_model("model-a")
    active = service.get_active_model("risk_multitask_v1")
    assert approved_a.status == ModelStatus.APPROVED
    assert active is not None
    assert active.model_id == "model-a"

    service.approve_model("model-b")
    rolled_back = next(item for item in service.list_models(task_name="risk_multitask_v1") if item.model_id == "model-a")
    assert rolled_back.status == ModelStatus.ROLLED_BACK

    restored = service.rollback_model("model-b")
    assert restored.model_id == "model-a"
    assert service.get_active_model("risk_multitask_v1") is not None
    assert service.get_active_model("risk_multitask_v1").model_id == "model-a"


def test_registry_does_not_promote_ineligible_candidate(tmp_path) -> None:
    service = TrainingRegistryService(tmp_path / "registry.json")
    baseline = _card("baseline")
    candidate = _card("candidate").model_copy(
        update={
            "algorithm_family": "patchtst",
            "validation_metrics": [
                FoldMetric(fold_id="wf-001", regime="bull", metric_name="top_bucket_drawdown_lift", metric_value=0.01),
                FoldMetric(fold_id="wf-002", regime="bear", metric_name="top_bucket_drawdown_lift", metric_value=0.05),
                FoldMetric(fold_id="wf-003", regime="bull", metric_name="top_bucket_alert_precision", metric_value=0.7),
            ],
        }
    )

    service.register_candidate(baseline)
    service.register_candidate(candidate)
    service.approve_model("baseline")
    result = service.approve_model_if_eligible(
        "candidate",
        baseline_model_id="baseline",
        policy=PromotionGatePolicy(),
    )

    assert result.eligible is False
    assert service.get_active_model("risk_multitask_v1").model_id == "baseline"


def test_registry_does_not_promote_candidate_when_audit_reports_future_leakage(tmp_path) -> None:
    service = TrainingRegistryService(tmp_path / "registry.json")
    baseline = _card("baseline").model_copy(
        update={
            "validation_metrics": [
                FoldMetric(fold_id="wf-001", regime="bull", metric_name="top_bucket_drawdown_lift", metric_value=0.03),
                FoldMetric(fold_id="wf-002", regime="bear", metric_name="top_bucket_drawdown_lift", metric_value=0.05),
                FoldMetric(fold_id="wf-003", regime="bull", metric_name="top_bucket_alert_precision", metric_value=0.7),
            ]
        }
    )
    candidate = _card("candidate").model_copy(
        update={
            "algorithm_family": "patchtst",
            "validation_metrics": [
                FoldMetric(fold_id="wf-001", regime="bull", metric_name="top_bucket_drawdown_lift", metric_value=0.06),
                FoldMetric(fold_id="wf-002", regime="bear", metric_name="top_bucket_drawdown_lift", metric_value=0.09),
                FoldMetric(fold_id="wf-003", regime="bull", metric_name="top_bucket_alert_precision", metric_value=0.7),
            ],
        }
    )

    service.register_candidate(baseline)
    service.register_candidate(candidate)
    service.approve_model("baseline")
    result = service.approve_model_if_eligible(
        "candidate",
        baseline_model_id="baseline",
        policy=PromotionGatePolicy(),
        audit=TrainingExperimentAuditSummary(
            sample_coverage=TrainingSampleCoverageSummary(sample_count=12),
            point_in_time_integrity=PointInTimeIntegritySummary(
                sample_count_with_events=6,
                sample_count_without_events=6,
                total_point_in_time_events=8,
                samples_with_data_issues=1,
                total_data_issue_count=1,
                potential_future_leakage_issue_count=1,
                potential_future_leakage_issue_codes={"future_event": 1},
            ),
        ),
    )

    assert result.eligible is False
    assert any("Potential future leakage issue count" in reason for reason in result.reasons)
    assert service.get_active_model("risk_multitask_v1").model_id == "baseline"
