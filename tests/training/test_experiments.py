from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass

from investment_research.training.experiments import TrainingExperimentRunner
from investment_research.training.models import InstrumentType, LabelSet, Market, PreparedPriceBar, PromotionGatePolicy, TrainingSample
from investment_research.training.trainers import LinearBaselineTrainerSpec, OptionalDependencyTrainerSpec


@dataclass(frozen=True)
class CandidateTrainerSpec(LinearBaselineTrainerSpec):
    name: str = "candidate-baseline"
    algorithm_family: str = "patchtst"
    algorithm_name: str = "patchtst_candidate"


def _sample(
    index: int,
    *,
    drawdown: float,
    point_in_time_event_count: int = 0,
    data_issues: list[str] | None = None,
    benchmark_symbol: str | None = None,
    sector_reference_symbol: str | None = None,
    style_reference_symbol: str | None = None,
    benchmark_ret_20d: float | None = None,
    sector_ret_20d: float | None = None,
    style_ret_20d: float | None = None,
    industry_excess_return_20d: float | None = None,
) -> TrainingSample:
    sample_date = date(2026, 1, 1) + timedelta(days=index)
    features = {
        "ret_20d": -0.01 * index,
        "vol_20d": 0.01 + 0.002 * index,
        "relative_strength_20d": -0.015 * index,
        "news_count_7d": float(index % 3),
    }
    if benchmark_ret_20d is not None:
        features["benchmark_ret_20d"] = benchmark_ret_20d
    if sector_ret_20d is not None:
        features["sector_ret_20d"] = sector_ret_20d
    if style_ret_20d is not None:
        features["style_ret_20d"] = style_ret_20d
    return TrainingSample(
        symbol=f"EQ{index % 3}",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        benchmark_symbol=benchmark_symbol,
        sector_reference_symbol=sector_reference_symbol,
        style_reference_symbol=style_reference_symbol,
        as_of_date=sample_date,
        as_of_time=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc),
        feature_cutoff=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=23),
        feature_version="f-v1",
        data_version="d-v1",
        features=features,
        labels=LabelSet(
            symbol=f"EQ{index % 3}",
            as_of_date=sample_date,
            future_max_drawdown_20d=drawdown,
            industry_excess_return_20d=industry_excess_return_20d,
        ),
        point_in_time_event_count=point_in_time_event_count,
        data_issues=data_issues or [],
    )


def _reference_bar(index: int, *, close_value: float) -> PreparedPriceBar:
    sample_date = date(2026, 1, 1) + timedelta(days=index)
    return PreparedPriceBar(
        symbol="SPY",
        trade_date=sample_date,
        close_native=close_value,
        close_normalized=close_value,
        volume=1000.0,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc),
    )


def test_training_experiment_runner_returns_baseline_and_candidate_results() -> None:
    samples = [_sample(index, drawdown=(-0.12 if index % 4 == 0 else -0.03)) for index in range(36)]
    report = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=[LinearBaselineTrainerSpec(), CandidateTrainerSpec()],
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert report.baseline_model_id is not None
    assert len(report.results) == 2
    assert report.results[0].eligible_for_approval is True
    assert report.results[1].promotion_result is not None
    assert any("promotion: baseline" == note for note in report.results[0].model_card.notes)
    assert report.audit is not None
    assert report.audit.sample_coverage.sample_count == 36
    assert report.audit.sample_coverage.symbol_count == 3
    assert report.audit.sample_coverage.start_date == date(2026, 1, 1)
    assert report.audit.sample_coverage.end_date == date(2026, 2, 5)
    assert report.results[0].regime_coverage
    assert report.audit.regime_coverage
    assert report.audit.regime_coverage[0].regime == "unknown"


def test_training_experiment_runner_records_skipped_optional_trainer() -> None:
    samples = [_sample(index, drawdown=(-0.12 if index % 4 == 0 else -0.03)) for index in range(24)]
    report = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=[
            LinearBaselineTrainerSpec(),
            OptionalDependencyTrainerSpec(
                name="missing-candidate",
                algorithm_family="patchtst",
                algorithm_name="patchtst_candidate",
                dependency_name="definitely_missing_training_dep",
            ),
        ],
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert len(report.results) == 1
    assert report.audit is not None
    assert len(report.audit.skipped_trainers) == 1
    skipped = report.audit.skipped_trainers[0]
    assert skipped.trainer_name == "missing-candidate"
    assert skipped.algorithm_family == "patchtst"
    assert "missing optional dependency" in skipped.reason


def test_training_experiment_runner_records_label_and_pit_audit_summary() -> None:
    samples = [
        _sample(0, drawdown=-0.12, point_in_time_event_count=2, data_issues=["future_event", "missing_volume"]),
        _sample(1, drawdown=-0.03, point_in_time_event_count=0),
        _sample(2, drawdown=-0.10, point_in_time_event_count=1, data_issues=["future_price_bar"]),
        _sample(3, drawdown=-0.02, point_in_time_event_count=0),
        _sample(4, drawdown=-0.09, point_in_time_event_count=3),
        _sample(5, drawdown=-0.01, point_in_time_event_count=1),
        _sample(6, drawdown=-0.11, point_in_time_event_count=0),
        _sample(7, drawdown=-0.04, point_in_time_event_count=2),
        _sample(8, drawdown=-0.08, point_in_time_event_count=0),
        _sample(9, drawdown=-0.02, point_in_time_event_count=1),
        _sample(10, drawdown=-0.07, point_in_time_event_count=0),
        _sample(11, drawdown=-0.03, point_in_time_event_count=1),
        _sample(12, drawdown=-0.12, point_in_time_event_count=2),
        _sample(13, drawdown=-0.03, point_in_time_event_count=0),
        _sample(14, drawdown=-0.10, point_in_time_event_count=1),
        _sample(15, drawdown=-0.02, point_in_time_event_count=0),
        _sample(16, drawdown=-0.09, point_in_time_event_count=3),
        _sample(17, drawdown=-0.01, point_in_time_event_count=1),
        _sample(18, drawdown=-0.11, point_in_time_event_count=0),
        _sample(19, drawdown=-0.04, point_in_time_event_count=2),
        _sample(20, drawdown=-0.08, point_in_time_event_count=0),
        _sample(21, drawdown=-0.02, point_in_time_event_count=1),
        _sample(22, drawdown=-0.07, point_in_time_event_count=0),
        _sample(23, drawdown=-0.03, point_in_time_event_count=1),
    ]
    report = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=[LinearBaselineTrainerSpec()],
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert report.audit is not None
    assert report.audit.sample_coverage.total_point_in_time_events == 22
    assert report.audit.sample_coverage.max_point_in_time_events_in_sample == 3
    assert report.audit.sample_coverage.samples_with_data_issues == 2
    assert report.audit.sample_coverage.total_data_issue_count == 3
    assert report.audit.sample_coverage.data_issue_code_counts == {
        "future_event": 1,
        "future_price_bar": 1,
        "missing_volume": 1,
    }

    label_coverage = {entry.label_name: entry for entry in report.audit.label_coverage}
    assert label_coverage["future_max_drawdown_20d"].available_count == 24
    assert label_coverage["future_max_drawdown_20d"].availability_ratio == 1.0
    assert label_coverage["future_volatility_20d"].available_count == 0
    assert label_coverage["future_volatility_20d"].missing_count == 24
    assert report.audit.target_label is not None
    assert report.audit.target_label.target_name == "future_max_drawdown_20d"
    assert report.audit.target_label.available_count == 24

    assert report.audit.point_in_time_integrity is not None
    assert report.audit.point_in_time_integrity.sample_count_with_events == 14
    assert report.audit.point_in_time_integrity.sample_count_without_events == 10
    assert report.audit.point_in_time_integrity.potential_future_leakage_issue_count == 2
    assert report.audit.point_in_time_integrity.potential_future_leakage_issue_codes == {
        "future_event": 1,
        "future_price_bar": 1,
    }


def test_training_experiment_runner_records_reference_coverage_and_target_specific_label_summary() -> None:
    samples = [
        _sample(
            0,
            drawdown=-0.12,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.03,
            sector_ret_20d=0.04,
            style_ret_20d=0.05,
            industry_excess_return_20d=0.01,
        ),
        _sample(
            1,
            drawdown=-0.03,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.02,
            sector_ret_20d=0.03,
            style_ret_20d=0.04,
            industry_excess_return_20d=0.02,
        ),
        _sample(
            2,
            drawdown=-0.05,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol=None,
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=None,
            industry_excess_return_20d=None,
        ),
        _sample(
            3,
            drawdown=-0.02,
            benchmark_symbol=None,
            sector_reference_symbol=None,
            style_reference_symbol=None,
            benchmark_ret_20d=None,
            sector_ret_20d=None,
            style_ret_20d=None,
            industry_excess_return_20d=None,
        ),
        _sample(
            4,
            drawdown=-0.08,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.00,
            sector_ret_20d=0.00,
            style_ret_20d=0.00,
            industry_excess_return_20d=None,
        ),
        _sample(
            5,
            drawdown=-0.07,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.02,
            sector_ret_20d=0.01,
            style_ret_20d=0.03,
            industry_excess_return_20d=0.03,
        ),
        _sample(
            6,
            drawdown=-0.06,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=0.02,
            industry_excess_return_20d=0.01,
        ),
        _sample(
            7,
            drawdown=-0.04,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=0.02,
            industry_excess_return_20d=0.00,
        ),
        _sample(
            8,
            drawdown=-0.03,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=0.02,
            industry_excess_return_20d=0.00,
        ),
        _sample(
            9,
            drawdown=-0.02,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=0.02,
            industry_excess_return_20d=0.00,
        ),
        _sample(
            10,
            drawdown=-0.01,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=0.02,
            industry_excess_return_20d=0.00,
        ),
        _sample(
            11,
            drawdown=-0.05,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK",
            style_reference_symbol="QQQ",
            benchmark_ret_20d=0.01,
            sector_ret_20d=0.02,
            style_ret_20d=0.02,
            industry_excess_return_20d=0.00,
        ),
    ]
    report = TrainingExperimentRunner(
        target_name="industry_excess_return_20d",
        trainer_specs=[LinearBaselineTrainerSpec()],
    ).run(
        samples=samples,
        train_window_days=6,
        validation_window_days=3,
        step_days=3,
    )

    assert report.audit is not None
    assert report.audit.target_label is not None
    assert report.audit.target_label.target_name == "industry_excess_return_20d"
    assert report.audit.target_label.available_count == 9
    assert report.audit.target_label.missing_count == 3

    reference_coverage = {entry.reference_type: entry for entry in report.audit.reference_coverage}
    assert reference_coverage["benchmark"].configured_sample_count == 11
    assert reference_coverage["benchmark"].feature_backed_sample_count == 10
    assert reference_coverage["benchmark"].reference_symbols == ["^GSPC"]
    assert reference_coverage["sector"].configured_sample_count == 11
    assert reference_coverage["sector"].feature_backed_sample_count == 10
    assert reference_coverage["style"].configured_sample_count == 10
    assert reference_coverage["style"].feature_backed_sample_count == 9


def test_training_experiment_runner_records_non_unknown_regime_when_reference_available() -> None:
    samples = [_sample(index, drawdown=(-0.12 if index % 4 == 0 else -0.03)) for index in range(36)]
    regime_reference = [_reference_bar(index, close_value=100.0 + (index * 5.0)) for index in range(36)]
    report = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=[LinearBaselineTrainerSpec(), CandidateTrainerSpec()],
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
        regime_reference=regime_reference,
    )

    assert report.audit is not None
    assert any(record.regime == "bull" for record in report.audit.regime_coverage)
    assert all(record.regime != "unknown" for record in report.results[0].regime_coverage)


def test_training_experiment_runner_blocks_candidate_when_target_audit_fails_gate() -> None:
    samples = [
        _sample(index, drawdown=(-0.12 if index % 4 == 0 else -0.03), industry_excess_return_20d=(0.01 if index < 4 else None))
        for index in range(24)
    ]
    report = TrainingExperimentRunner(
        target_name="industry_excess_return_20d",
        trainer_specs=[LinearBaselineTrainerSpec(), CandidateTrainerSpec()],
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert report.audit is not None
    assert report.audit.target_label is not None
    assert report.audit.target_label.availability_ratio < 0.6
    assert report.results[1].eligible_for_approval is False
    assert report.results[1].promotion_result is not None
    assert any("Target label availability" in reason for reason in report.results[1].promotion_result.reasons)
    assert report.results[1].promotion_result.effective_policy is not None
    assert any(check.check_name == "target_label_availability" and check.status == "failed" for check in report.results[1].promotion_result.checks)


def test_training_experiment_runner_blocks_candidate_when_pit_leakage_or_data_issue_ratio_fails_gate() -> None:
    samples = [
        _sample(index, drawdown=(-0.12 if index % 4 == 0 else -0.03), data_issues=(["future_event"] if index == 0 else ["missing_volume"] if index < 11 else []))
        for index in range(24)
    ]
    report = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=[LinearBaselineTrainerSpec(), CandidateTrainerSpec()],
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert report.audit is not None
    assert report.audit.point_in_time_integrity is not None
    assert report.audit.point_in_time_integrity.potential_future_leakage_issue_count == 1
    assert report.audit.point_in_time_integrity.samples_with_data_issues == 11
    assert report.results[1].eligible_for_approval is False
    assert report.results[1].promotion_result is not None
    reasons = report.results[1].promotion_result.reasons
    assert any("Potential future leakage issue count" in reason for reason in reasons)
    assert any("Sample data-issue ratio" in reason for reason in reasons)


def test_training_experiment_runner_uses_task_specific_gate_profile_for_drawdown_tasks() -> None:
    samples = [
        _sample(index, drawdown=(-0.12 if index < 16 else None))
        for index in range(24)
    ]
    report = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=[LinearBaselineTrainerSpec(), CandidateTrainerSpec()],
        promotion_policy=PromotionGatePolicy(minimum_target_label_availability_ratio=0.6),
    ).run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert report.audit is not None
    assert report.audit.target_label is not None
    assert 0.6 < report.audit.target_label.availability_ratio < 0.75
    assert report.results[1].eligible_for_approval is False
    assert report.results[1].promotion_result is not None
    assert any("below minimum 0.750" in reason for reason in report.results[1].promotion_result.reasons)
