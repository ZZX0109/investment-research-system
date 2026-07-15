from investment_research.training.task_gates import (
    DeepClassificationPromotionEvidence,
    DeepRegimeGateResult,
    DeepReturnPromotionEvidence,
    DirectionGateEvidence,
    RegimeAurocObservation,
    ReturnGateEvidence,
    evaluate_deep_classification_promotion,
    evaluate_deep_regime_gate,
    evaluate_deep_return_promotion,
    evaluate_direction_gate,
    evaluate_return_gate,
)


def test_deep_gate_aggregates_folds_and_requires_only_two_regimes() -> None:
    observations = []
    for regime, table, deep in (
        ("bull", 0.70, 0.73),
        ("bear", 0.69, 0.72),
        ("range", 0.71, 0.70),
    ):
        for fold in ("a", "b"):
            observations.extend(
                [
                    RegimeAurocObservation(
                        regime=regime,
                        fold_id=fold,
                        model_name="table",
                        algorithm_family="lightgbm",
                        auroc=table,
                    ),
                    RegimeAurocObservation(
                        regime=regime,
                        fold_id=fold,
                        model_name="tcn",
                        algorithm_family="tcn",
                        auroc=deep,
                    ),
                ]
            )
    result = evaluate_deep_regime_gate(
        observations,
        deep_model_name="tcn",
        deep_families={"tcn"},
    )
    assert result.passed
    assert result.qualifying_regimes == ["bear", "bull"]
    assert result.regime_deltas["range"] < 0


def test_direction_and_return_gates_are_task_specific() -> None:
    direction = evaluate_direction_gate(
        DirectionGateEvidence(
            macro_f1=0.46,
            balanced_accuracy=0.46,
            log_loss=1.0,
            ece=0.1,
            best_simple_baseline_macro_f1=0.44,
            regime_macro_f1={"bull": 0.40, "bear": 0.36},
            recent_window_macro_f1=[0.41, 0.42],
        )
    )
    assert direction.passed
    returns = evaluate_return_gate(
        ReturnGateEvidence(
            mean_pinball_loss=0.09,
            best_baseline_pinball_loss=0.10,
            p50_mae=0.08,
            best_baseline_p50_mae=0.09,
            direction_accuracy=0.55,
            best_baseline_direction_accuracy=0.52,
            spearman_ic=0.08,
            interval_coverage=0.80,
            group_pinball_loss={"bull": 0.10},
            group_baseline_pinball_loss={"bull": 0.10},
            holdout_12m_passed=True,
            stress_6m_passed=True,
        )
    )
    assert returns.passed


def test_deep_promotion_requires_two_regimes_and_three_stable_seeds() -> None:
    observations = []
    for regime in ("bull", "bear", "range"):
        observations.extend([
            RegimeAurocObservation(
                regime=regime, fold_id="f1", model_name="tcn",
                algorithm_family="tcn", auroc=0.75 if regime != "range" else 0.70,
            ),
            RegimeAurocObservation(
                regime=regime, fold_id="f1", model_name="lgbm",
                algorithm_family="tabular", auroc=0.70,
            ),
        ])
    decision = evaluate_deep_classification_promotion(DeepClassificationPromotionEvidence(
        observations=observations, deep_model_name="tcn", best_tabular_brier=0.20,
        deep_brier=0.19, best_tabular_ece=0.10, deep_ece=0.09,
        best_tabular_coverage=0.90, deep_coverage=0.89,
        seed_aurocs={42: 0.74, 2026: 0.75, 3407: 0.73},
    ))
    assert decision.passed


def test_deep_return_requires_five_percent_improvement_in_two_regimes() -> None:
    decision = evaluate_deep_return_promotion(DeepReturnPromotionEvidence(
        best_tabular_pinball_loss=0.10, deep_pinball_loss=0.094,
        regime_improvement_ratios={"bull": 0.06, "bear": 0.05, "range": 0.01},
        seed_pinball_losses={42: 0.094, 2026: 0.095, 3407: 0.093},
    ))
    assert decision.passed
