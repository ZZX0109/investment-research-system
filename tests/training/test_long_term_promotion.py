from investment_research.training.long_term_config import LongTermTrainingConfig
from investment_research.training.long_term_promotion import evaluate_long_term_promotion


def test_long_term_promotion_requires_shadow_and_cost_adjusted_holdout() -> None:
    config = LongTermTrainingConfig(minimum_shadow_sessions=60)
    report = {
        "status": "research_only",
        "deployment_ready": False,
        "models": {
            "ridge": {
                "status": "research_only",
                "holdout_metrics": {"rank_ic": 0.03, "top_k_excess_return_after_cost": 0.01},
            }
        },
    }
    blocked = evaluate_long_term_promotion(report, valid_shadow_sessions=59, config=config)
    assert blocked["status"] == "blocked"
    assert "shadow_sessions_below_60" in blocked["blocking_reasons"]
    eligible = evaluate_long_term_promotion(report, valid_shadow_sessions=60, config=config)
    assert eligible["status"] == "candidate_for_review"
    assert eligible["deployment_ready"] is False


def test_long_term_promotion_accepts_prefixed_drawdown_metrics() -> None:
    config = LongTermTrainingConfig(minimum_shadow_sessions=60)
    report = {
        "status": "research_only",
        "deployment_ready": False,
        "models": {
            "patchtst": {
                "status": "research_only",
                "holdout_metrics": {
                    "risk_rank_ic": 0.04,
                    "risk_top_k_excess_return_after_cost": 0.01,
                },
            }
        },
    }
    result = evaluate_long_term_promotion(report, valid_shadow_sessions=60, config=config)
    assert result["status"] == "candidate_for_review"
    assert result["eligible_models"] == ["patchtst"]
