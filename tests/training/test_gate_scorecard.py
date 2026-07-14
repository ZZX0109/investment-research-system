"""Tests for gate scorecard integration."""

from datetime import date

from investment_research.training.models import (
    ModelCard,
    ModelStatus,
    PromotionGateCheck,
    PromotionGatePolicy,
    PromotionGateResult,
    TrainingExperimentResult,
)
from investment_research.training.promotion import (
    build_gate_scorecard,
    enrich_experiment_with_scorecard,
    summarize_gate_scorecard,
)


def _make_card(model_id: str = "mod-001") -> ModelCard:
    return ModelCard(
        model_id=model_id,
        task_name="future_max_drawdown_20d",
        algorithm_family="lightgbm",
        algorithm_name="lightgbm_classifier",
        data_version="d1",
        feature_version="f1",
        label_version="l1",
        training_window_start=date(2025, 1, 1),
        training_window_end=date(2025, 12, 31),
        status=ModelStatus.CANDIDATE,
        notes=[],
    )


def _make_passing_gate_result(card: ModelCard) -> PromotionGateResult:
    return PromotionGateResult(
        candidate_model_id=card.model_id,
        eligible=True,
        reasons=[],
        regime_deltas={"bull": 0.05, "bear": 0.03},
        effective_policy=PromotionGatePolicy(minimum_alert_precision=0.5),
        checks=[
            PromotionGateCheck(
                check_name="primary_metric_presence",
                status="passed",
                actual_value="top_bucket_drawdown_lift",
                threshold_value="top_bucket_drawdown_lift",
                detail="Primary metric present.",
            ),
            PromotionGateCheck(
                check_name="minimum_alert_precision",
                status="passed",
                actual_value=0.65,
                threshold_value=0.5,
                detail="Alert precision meets minimum.",
            ),
        ],
    )


def _make_failing_gate_result(card: ModelCard) -> PromotionGateResult:
    return PromotionGateResult(
        candidate_model_id=card.model_id,
        eligible=False,
        reasons=["Alert precision too low."],
        regime_deltas={"bull": -0.02, "bear": -0.01},
        effective_policy=PromotionGatePolicy(minimum_alert_precision=0.5),
        checks=[
            PromotionGateCheck(
                check_name="primary_metric_presence",
                status="passed",
                actual_value="top_bucket_drawdown_lift",
                threshold_value="top_bucket_drawdown_lift",
                detail="Primary metric present.",
            ),
            PromotionGateCheck(
                check_name="minimum_alert_precision",
                status="failed",
                actual_value=0.35,
                threshold_value=0.5,
                detail="Alert precision 0.35 is below minimum 0.50.",
            ),
        ],
    )


class TestBuildGateScorecard:
    def test_appends_scorecard_to_notes(self):
        card = _make_card()
        result = _make_passing_gate_result(card)
        before = len(card.notes)
        result_card = build_gate_scorecard(result, card)
        assert len(result_card.notes) == before + 1
        assert "PROMOTION GATE SCORECARD" in result_card.notes[-1]

    def test_passing_result_shows_yes(self):
        card = _make_card()
        result = _make_passing_gate_result(card)
        result_card = build_gate_scorecard(result, card)
        assert "YES" in result_card.notes[-1]
        assert "FAILED" not in result_card.notes[-1]

    def test_failing_result_shows_reasons(self):
        card = _make_card()
        result = _make_failing_gate_result(card)
        result_card = build_gate_scorecard(result, card)
        scorecard = result_card.notes[-1]
        assert "NO" in scorecard
        assert "Alert precision too low." in scorecard
        assert "FAILED" in scorecard

    def test_passing_result_contains_summary(self):
        card = _make_card()
        result = _make_passing_gate_result(card)
        result_card = build_gate_scorecard(result, card)
        assert "PASS/FAIL SUMMARY" in result_card.notes[-1]
        assert "Passed:   2" in result_card.notes[-1]
        assert "Failed:   0" in result_card.notes[-1]

    def test_failing_result_contains_summary(self):
        card = _make_card()
        result = _make_failing_gate_result(card)
        result_card = build_gate_scorecard(result, card)
        scorecard = result_card.notes[-1]
        assert "Passed:   1" in scorecard
        assert "Failed:   1" in scorecard


class TestSummarizeGateScorecard:
    def test_passing_result(self):
        card = _make_card()
        result = _make_passing_gate_result(card)
        summary = summarize_gate_scorecard(result)
        assert summary["eligible"] is True
        assert summary["failure_count"] == 0
        assert summary["pass_count"] == 2
        assert summary["failed_checks"] == []

    def test_failing_result(self):
        card = _make_card()
        result = _make_failing_gate_result(card)
        summary = summarize_gate_scorecard(result)
        assert summary["eligible"] is False
        assert summary["failure_count"] == 1
        assert summary["pass_count"] == 1
        assert summary["failed_checks"] == ["minimum_alert_precision"]


class TestEnrichExperimentWithScorecard:
    def test_enriches_model_card_when_promotion_result_present(self):
        card = _make_card()
        gate_result = _make_passing_gate_result(card)
        exp = TrainingExperimentResult(
            trainer_name="lightgbm",
            algorithm_family="lightgbm",
            model_card=card,
            promotion_result=gate_result,
            eligible_for_approval=True,
        )
        result = enrich_experiment_with_scorecard(exp)
        assert "PROMOTION GATE SCORECARD" in result.model_card.notes[-1]

    def test_noop_when_no_promotion_result(self):
        card = _make_card()
        before = len(card.notes)
        exp = TrainingExperimentResult(
            trainer_name="lightgbm",
            algorithm_family="lightgbm",
            model_card=card,
            promotion_result=None,
        )
        result = enrich_experiment_with_scorecard(exp)
        assert len(result.model_card.notes) == before
