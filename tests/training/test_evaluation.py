from datetime import datetime, timedelta, timezone

from investment_research.training.evaluation import evaluate_risk_bucket_usefulness
from investment_research.training.models import RiskBucketObservation


def test_risk_bucket_evaluation_reports_drawdown_lift_and_lead_time() -> None:
    now = datetime(2026, 7, 6, tzinfo=timezone.utc)
    evaluation = evaluate_risk_bucket_usefulness(
        [
            RiskBucketObservation(
                symbol="AAPL",
                score=0.95,
                future_max_drawdown_20d=-0.12,
                alerted_at=now,
                risk_event_at=now + timedelta(days=3),
            ),
            RiskBucketObservation(
                symbol="MSFT",
                score=0.8,
                future_max_drawdown_20d=-0.09,
                alerted_at=now,
                risk_event_at=now + timedelta(days=2),
            ),
            RiskBucketObservation(symbol="SPY", score=0.4, future_max_drawdown_20d=-0.03),
            RiskBucketObservation(symbol="XLE", score=0.2, future_max_drawdown_20d=-0.01),
            RiskBucketObservation(symbol="KWEB", score=0.1, future_max_drawdown_20d=-0.02),
        ],
        top_fraction=0.4,
    )

    assert evaluation.top_bucket_size == 2
    assert evaluation.top_bucket_mean_drawdown < evaluation.overall_mean_drawdown
    assert evaluation.alert_precision == 1.0
    assert evaluation.average_lead_days == 2.5
    assert evaluation.auc_roc is not None
    assert evaluation.pr_auc is not None
    assert evaluation.brier_score is not None
    assert evaluation.expected_calibration_error is not None
