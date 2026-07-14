from investment_research.training.directional import (
    DirectionEvaluation,
    DirectionLabelPolicy,
    DirectionalModelManifest,
)


def test_direction_label_boundaries_are_versioned_and_include_flat_band() -> None:
    policy = DirectionLabelPolicy()
    assert policy.classify(0.02) == "up"
    assert policy.classify(-0.02) == "down"
    assert policy.classify(0.0199) == "flat"
    assert policy.classify(-0.0199) == "flat"


def test_direction_model_stays_research_only_when_any_gate_fails() -> None:
    evaluation = DirectionEvaluation(
        macro_f1=0.60,
        balanced_accuracy=0.60,
        log_loss=0.80,
        ece=0.10,
        market_macro_f1={"US": 0.55, "CN": 0.20},
        regime_macro_f1={"bull": 0.50, "bear": 0.50, "range": 0.50, "high_vol": 0.50},
        recent_window_macro_f1=[0.50, 0.50],
        shared_sample_hash="sample-hash",
        shared_fold_hash="fold-hash",
    )
    manifest = DirectionalModelManifest.from_evaluation(model_name="direction-rf", model_version="v1", evaluation=evaluation)
    assert manifest.status == "research_only"
    assert "market_gate_failed" in manifest.gating_reasons


def test_direction_model_requires_all_independent_gates_for_approval() -> None:
    evaluation = DirectionEvaluation(
        macro_f1=0.60,
        balanced_accuracy=0.60,
        log_loss=0.80,
        ece=0.10,
        market_macro_f1={"US": 0.55, "CN": 0.55},
        regime_macro_f1={"bull": 0.50, "bear": 0.50, "range": 0.50, "high_vol": 0.50},
        recent_window_macro_f1=[0.50, 0.50],
        shared_sample_hash="sample-hash",
        shared_fold_hash="fold-hash",
    )
    manifest = DirectionalModelManifest.from_evaluation(model_name="direction-rf", model_version="v1", evaluation=evaluation)
    assert manifest.status == "approved"
    assert manifest.gating_reasons == []
