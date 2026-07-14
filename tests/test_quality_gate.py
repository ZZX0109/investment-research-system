from datetime import datetime, timezone

from investment_research.domain.enums import JudgeVerdict
from investment_research.pipeline.quality_gate import QualityGateInput, QualityGateService


def gate_input(**overrides) -> QualityGateInput:
    values = {
        "data_modes": ["real"],
        "fallback_reasons": [],
        "evidence_count": 2,
        "synthetic_share": 0.1,
        "real_share": 0.9,
        "latest_price_timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc),
        "price_freshness_status": "fresh",
        "evidence_freshness_status": "fresh",
        "prediction_confidence": 0.8,
    }
    values.update(overrides)
    return QualityGateInput(**values)


def test_quality_gate_passes_when_inputs_clear_policy() -> None:
    result = QualityGateService().evaluate_input(gate_input())

    assert result.verdict == JudgeVerdict.PASS
    assert result.gating_reasons == []
    assert result.score == 0.95


def test_quality_gate_warns_for_non_blocking_policy_gates() -> None:
    result = QualityGateService().evaluate_input(
        gate_input(
            data_modes=["sandbox"],
            fallback_reasons=["No real-time evidence feed available; analysis fell back to curated persisted evidence."],
            synthetic_share=0.4,
            real_share=0.6,
        )
    )

    assert result.verdict == JudgeVerdict.WARN
    assert "Sandbox mode is intended for testing and training" in result.gating_reasons[0]
    assert result.gating_reasons[-1] == "No real-time evidence feed available; analysis fell back to curated persisted evidence."


def test_quality_gate_holds_for_stale_inputs() -> None:
    result = QualityGateService().evaluate_input(
        gate_input(
            price_freshness_status="stale",
            evidence_freshness_status="stale",
        )
    )

    assert result.verdict == JudgeVerdict.HOLD
    assert "Latest price data is older than 7 days" in result.gating_reasons
    assert "Latest evidence data is older than freshness policy allows" in result.gating_reasons


def test_quality_gate_blocks_when_required_inputs_are_missing_or_too_weak() -> None:
    result = QualityGateService().evaluate_input(
        gate_input(
            evidence_count=0,
            latest_price_timestamp=None,
            prediction_confidence=0.4,
        )
    )

    assert result.verdict == JudgeVerdict.BLOCK
    assert "Evidence set is empty" in result.gating_reasons
    assert "No persisted price series available" in result.gating_reasons
    assert "Prediction confidence below block threshold" in result.gating_reasons


def test_quality_gate_blocks_unapproved_or_undercovered_model_outputs() -> None:
    result = QualityGateService().evaluate_input(
        gate_input(
            deployment_approved=False,
            model_status="fallback",
            feature_coverage=0.4,
            inference_warnings=["Deployment model unavailable: manifest missing"],
        )
    )

    assert result.verdict == JudgeVerdict.BLOCK
    assert "Prediction model is not approved for deployment" in result.gating_reasons
    assert "Prediction model status is fallback" in result.gating_reasons
    assert "Model feature coverage below minimum threshold" in result.gating_reasons
    assert "Deployment model unavailable: manifest missing" in result.gating_reasons
