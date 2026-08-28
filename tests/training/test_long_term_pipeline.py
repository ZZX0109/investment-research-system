from datetime import date, timedelta

import pytest

from investment_research.training.models import CoverageGroup, InstrumentType, LabelSet, Market, TrainingSample
from investment_research.training.long_term_pipeline import (
    LongTermObservation,
    build_long_term_observations,
    _IndustryMeanRegressor,
    _load_fold_checkpoint,
    _observations_context_hash,
    _persist_final_model_artifact,
    _write_fold_checkpoint,
    evaluate_cross_sectional,
)


def test_target_specific_long_term_label_survives_other_horizon_missing() -> None:
    sample = TrainingSample(
        symbol="000001",
        market=Market.CN,
        instrument_type=InstrumentType.EQUITY,
        coverage_group=CoverageGroup.CN_A_SHARE,
        as_of_date=date(2024, 6, 30),
        as_of_time="2024-06-30T08:00:00Z",
        feature_cutoff="2024-06-30T08:00:00Z",
        feature_version="test-feature-v1",
        data_version="test-data-v1",
        features={"quality": 1.0},
        labels=LabelSet(
            symbol="000001",
            as_of_date=date(2024, 6, 30),
            excess_return_120d=0.12,
            long_term_label_available=False,
            long_term_label_unavailable_reason="benchmark_missing_240d",
        ),
    )

    observations = build_long_term_observations(
        [sample], target="excess_return_120d", minimum_feature_coverage=0.98,
    )

    assert len(observations) == 1
    assert observations[0].target == 0.12


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


def test_cross_sectional_capacity_is_explicit_when_amount_is_available() -> None:
    day = date(2026, 3, 3)
    observations = [
        LongTermObservation(symbol, day, "bank", {"quality": float(index), "amount_1d": 100.0 + index}, float(index))
        for index, symbol in enumerate(("A", "B", "C", "D", "E"))
    ]
    report = evaluate_cross_sectional(observations, [item.features["quality"] for item in observations], top_k=2)
    assert report["capacity_estimate"]["status"] == "research_estimate"
    assert report["capacity_estimate"]["participation_rate"] == 0.10
    assert report["capacity_estimate"]["observation_days"] == 1


def test_cross_sectional_records_oof_calibrated_interval_coverage() -> None:
    observations = []
    for day in (date(2024, 1, 2), date(2024, 1, 3)):
        for index in range(5):
            observations.append(
                LongTermObservation(
                    f"{day.day}{index:04d}", day, "industry",
                    {"quality": float(index)}, float(index) / 10,
                )
            )
    report = evaluate_cross_sectional(
        observations,
        [item.features["quality"] / 10 for item in observations],
        interval_half_width=0.0,
    )
    assert report["interval_method"] == "oof_abs_residual_q90"
    assert report["interval_coverage"] == 1.0


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


def test_final_model_artifact_is_context_bound_and_hashed(tmp_path) -> None:
    path, digest = _persist_final_model_artifact(
        tmp_path, "constant-baseline", {"kind": "fixture"},
        context_hash="a" * 64, feature_names=["quality"],
    )
    assert path is not None and path.is_file()
    assert digest is not None and len(digest) == 64
