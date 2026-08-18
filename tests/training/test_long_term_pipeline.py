from datetime import date, timedelta

import pytest

from investment_research.training.long_term_pipeline import (
    LongTermObservation,
    _IndustryMeanRegressor,
    _load_fold_checkpoint,
    _observations_context_hash,
    _write_fold_checkpoint,
    evaluate_cross_sectional,
)


def test_cross_sectional_metrics_use_date_groups_and_costs() -> None:
    day = date(2026, 1, 1)
    observations = [
        LongTermObservation("A", day, "industry-a", {"quality": 1.0}, 0.10),
        LongTermObservation("B", day, "industry-a", {"quality": 0.8}, 0.05),
        LongTermObservation("C", day, "industry-b", {"quality": 0.6}, 0.02),
        LongTermObservation("D", day, "industry-b", {"quality": 0.4}, -0.01),
        LongTermObservation("E", day, "industry-c", {"quality": 0.2}, -0.03),
    ]
    observations += [
        LongTermObservation(item.symbol, day + timedelta(days=1), item.industry_key, item.features, item.target)
        for item in observations
    ]
    report = evaluate_cross_sectional(observations, [item.features["quality"] for item in observations], top_k=2, transaction_cost_bps=20)
    assert report["decision_date_count"] == 2
    assert report["rank_ic"] == pytest.approx(1.0)
    assert report["top_k_excess_return_after_cost"] < report["top_k_excess_return"]
    assert report["capacity_estimate"] is None
    assert report["mae"] is not None
    assert report["pinball_loss"] is not None
    assert report["interval_coverage"] is None


def test_prediction_rows_are_separate_from_summary() -> None:
    observations = [
        LongTermObservation("A", date(2026, 1, 1), "industry-a", {"quality": 1.0}, 0.1),
        LongTermObservation("B", date(2026, 1, 1), "industry-a", {"quality": 0.5}, 0.0),
    ]
    rows = []
    from investment_research.training.long_term_pipeline import _prediction_rows

    rows.extend(_prediction_rows("ridge-baseline", "oof", observations, [0.8, 0.2]))
    assert rows[0]["symbol"] == "A"
    assert "prediction_rows" not in {"status": "research_only"}


def test_industry_baseline_uses_training_industry_means_with_global_fallback() -> None:
    train_day = date(2026, 1, 1)
    train = [
        LongTermObservation("A", train_day, "bank", {}, 0.10),
        LongTermObservation("B", train_day, "bank", {}, 0.20),
        LongTermObservation("C", train_day, "tech", {}, -0.10),
    ]
    model = _IndustryMeanRegressor().fit(train)
    scored = [
        LongTermObservation("D", date(2026, 4, 1), "bank", {}, 0.0),
        LongTermObservation("E", date(2026, 4, 1), "unknown-industry", {}, 0.0),
    ]
    assert model.predict(scored) == pytest.approx([0.15, 0.0666666667])


def test_cross_sectional_metrics_report_pit_market_regimes() -> None:
    day = date(2026, 2, 1)
    observations = [
        LongTermObservation(
            symbol,
            day,
            "industry-a",
            {"quality": score},
            target,
            regime="bull",
        )
        for symbol, score, target in (
            ("A", 1.0, 0.10),
            ("B", 0.8, 0.05),
            ("C", 0.6, 0.02),
            ("D", 0.4, -0.01),
            ("E", 0.2, -0.03),
        )
    ]
    report = evaluate_cross_sectional(observations, [item.features["quality"] for item in observations])
    assert report["regime_sample_counts"] == {"bull": 5}
    assert report["regime_rank_ic"] == {"bull": pytest.approx(1.0)}


def test_cross_sectional_metrics_include_industry_stability() -> None:
    day = date(2026, 3, 1)
    observations = [
        LongTermObservation(f"B{index}", day, "bank", {"quality": float(index)}, float(index))
        for index in range(5)
    ] + [
        LongTermObservation(f"T{index}", day, "tech", {"quality": float(index)}, float(index) * -1)
        for index in range(5)
    ]
    report = evaluate_cross_sectional(observations, [item.features["quality"] for item in observations])
    assert set(report["industry_rank_ic"]) == {"bank", "tech"}


def test_cross_sectional_metrics_include_data_completeness_stability() -> None:
    day = date(2026, 3, 2)
    observations = [
        LongTermObservation(
            f"H{index}", day, "bank", {"quality": float(index)}, float(index),
            feature_coverage=0.99,
        )
        for index in range(5)
    ] + [
        LongTermObservation(
            f"L{index}", day, "tech", {"quality": float(index)}, float(index) * -1,
            feature_coverage=0.96,
        )
        for index in range(5)
    ]
    report = evaluate_cross_sectional(observations, [item.features["quality"] for item in observations])
    assert set(report["data_completeness_rank_ic"]) == {"coverage_at_least_98%", "coverage_95_to_98%"}
    assert report["data_completeness_sample_counts"]["coverage_at_least_98%"] == 5


def test_scorecard_keeps_missing_long_term_dimensions_explicit() -> None:
    from investment_research.training.long_term_pipeline import score_long_term_snapshot

    score = score_long_term_snapshot(
        {
            "fundamental_net_income_yoy": 0.12,
            "fundamental_roe_avg": 0.15,
        },
        feature_coverage=0.96,
    )
    assert score["growth_stability"] is not None
    assert score["shareholder_return"] is not None
    assert "valuation_features_missing" in score["evidence"]


def test_fold_checkpoint_round_trip_is_context_bound(tmp_path) -> None:
    observations = [
        LongTermObservation("A", date(2026, 1, 1), "bank", {"quality": 1.0}, 0.2),
        LongTermObservation("B", date(2026, 1, 1), "tech", {"quality": 0.5}, -0.1),
    ]
    feature_names = ["quality"]
    context_hash = _observations_context_hash(observations, feature_names)
    path = tmp_path / "ridge-baseline" / "wf-001.json"
    _write_fold_checkpoint(
        path,
        model_name="ridge-baseline",
        fold_id="wf-001",
        context_hash=context_hash,
        feature_names=feature_names,
        observations=observations,
        scores=[0.1, -0.2],
    )
    loaded = _load_fold_checkpoint(
        path,
        model_name="ridge-baseline",
        fold_id="wf-001",
        context_hash=context_hash,
        feature_names=feature_names,
    )
    assert loaded is not None
    restored, scores = loaded
    assert [item.symbol for item in restored] == ["A", "B"]
    assert scores == [0.1, -0.2]
    assert _load_fold_checkpoint(
        path,
        model_name="ridge-baseline",
        fold_id="wf-001",
        context_hash="stale",
        feature_names=feature_names,
    ) is None
