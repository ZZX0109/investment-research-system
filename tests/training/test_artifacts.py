from datetime import date

from investment_research.training.artifacts import TrainingArtifactStore
from investment_research.training.models import (
    FoldMetric,
    ModelCard,
    PromotionGateCheck,
    PromotionGatePolicy,
    PromotionGateResult,
    RegimeCoverageRecord,
    SkippedTrainerRecord,
    TrainingExperimentAuditSummary,
    TrainingExperimentReport,
    TrainingExperimentResult,
    TrainingSampleCoverageSummary,
)


def _card() -> ModelCard:
    return ModelCard(
        model_id="baseline-risk-d-v1-f-v1",
        task_name="future_max_drawdown_20d",
        algorithm_family="linear_baseline",
        algorithm_name="correlation_logit",
        data_version="d-v1",
        feature_version="f-v1",
        label_version="l-v1",
        training_window_start=date(2023, 1, 1),
        training_window_end=date(2025, 12, 31),
        validation_metrics=[FoldMetric(fold_id="wf-001", regime="bull", metric_name="top_bucket_drawdown_lift", metric_value=0.1)],
    )


def test_training_artifact_store_writes_report_and_model_card(tmp_path) -> None:
    store = TrainingArtifactStore(tmp_path)
    card = _card()
    report = TrainingExperimentReport(
        target_name="future_max_drawdown_20d",
        baseline_model_id=card.model_id,
        audit=TrainingExperimentAuditSummary(
            sample_coverage=TrainingSampleCoverageSummary(
                sample_count=32,
                symbol_count=2,
                symbols=["AAPL", "NVDA"],
                data_issue_code_counts={"future_event": 1},
            ),
            regime_coverage=[
                RegimeCoverageRecord(
                    regime="unknown",
                    fold_count=3,
                    validation_prediction_count=18,
                    validation_start=date(2025, 10, 1),
                    validation_end=date(2025, 12, 31),
                )
            ],
            skipped_trainers=[
                SkippedTrainerRecord(
                    trainer_name="patchtst",
                    algorithm_family="patchtst",
                    reason="missing optional dependency: No module named 'patchtst'",
                )
            ],
        ),
        results=[
            TrainingExperimentResult(
                trainer_name="linear-baseline",
                algorithm_family="linear_baseline",
                model_card=card,
                promotion_result=PromotionGateResult(
                    candidate_model_id=card.model_id,
                    eligible=True,
                    effective_policy=PromotionGatePolicy(),
                    checks=[
                        PromotionGateCheck(
                            check_name="minimum_alert_precision",
                            status="passed",
                            actual_value=0.7,
                            threshold_value=0.5,
                            detail="Candidate alert precision meets minimum.",
                        )
                    ],
                ),
                eligible_for_approval=True,
            )
        ],
    )

    report_path = store.write_experiment_report(report, name="demo")
    card_path = store.write_model_card(card, name=card.model_id)

    assert report_path.exists()
    assert card_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert '"sample_count": 32' in report_text
    assert '"regime": "unknown"' in report_text
    assert '"trainer_name": "patchtst"' in report_text
    assert '"check_name": "minimum_alert_precision"' in report_text
    assert '"minimum_alert_precision": 0.5' in report_text
