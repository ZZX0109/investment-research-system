from datetime import date, datetime, timedelta, timezone

from investment_research.training.models import InstrumentType, LabelSet, Market, TrainingSample
from investment_research.training.sequence_dataset import build_sequence_examples
from investment_research.training.sequence_models import SequenceModelConfig, SequenceTaskRunner, sequence_input_width
from investment_research.training.sequence_calibration import decide_with_disagreement, fit_direction_calibrators, weighted_direction_ensemble
from investment_research.training.sequence_experiment import evaluate_predictions, split_sequence_examples


def _rows(n=28):
    rows = []
    for i in range(n):
        d = date(2020, 1, 1) + timedelta(days=i)
        rows.append(TrainingSample(
            symbol="600000", market=Market.CN, instrument_type=InstrumentType.EQUITY,
            as_of_date=d, as_of_time=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc),
            feature_cutoff=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc),
            feature_version="investment-risk-features-v3-sequence", data_version="fixture",
            market_snapshot_id="snapshot-1", market_snapshot_hash="a" * 64,
            data_tier="research_pit", data_quality_status="passed",
            features={"ret_5d": i / 100.0, "vol_20d": 0.1 + i / 1000.0},
            data_quality_mask={"quality_passed": 1.0}, event_missing_mask={"event_source_unavailable": 0.0},
            provider_id="akshare", revision_id=f"rev-{i}", source_delay_seconds=2.0,
            event_coverage_status="confirmed_none", labels=LabelSet(
                symbol="600000", as_of_date=d, future_return_20d=(i / 100.0),
                future_max_drawdown_20d=-0.03 if i % 2 else -0.12,
                direction_1d="up" if i % 3 == 0 else "flat",
                direction_5d="down" if i % 4 == 0 else "up",
                label_start=d, label_end=d + timedelta(days=20),
            ),
        ))
    return rows


def test_sequence_builder_preserves_quality_channels_and_snapshot():
    examples = build_sequence_examples(_rows(), target_name="direction_1d", window_sessions=20)
    assert examples
    row = examples[0]
    assert len(row.values) == 20
    assert len(row.data_quality_mask) == 20
    assert len(row.event_missing_mask[0]) == 2
    assert row.market_snapshot_hash == "a" * 64
    assert row.data_tier == "research_pit"
    assert row.market_regime == "range"
    assert sequence_input_width(row) == 2 * len(row.feature_order) + 9


def test_sequence_builder_masks_non_finite_features():
    rows = _rows()
    rows[3].features["ret_5d"] = float("nan")
    rows[4].features["vol_20d"] = float("inf")
    examples = build_sequence_examples(rows, target_name="direction_1d", window_sessions=20)
    assert examples
    first = examples[0]
    ret_index = first.feature_order.index("ret_5d")
    vol_index = first.feature_order.index("vol_20d")
    assert first.values[3][ret_index] == 0.0
    assert first.missing_mask[3][ret_index]
    assert first.values[4][vol_index] == 0.0
    assert first.missing_mask[4][vol_index]


def test_sequence_builder_uses_decision_availability_not_source_timestamp():
    rows = _rows(25)
    for row in rows:
        row.as_of = row.feature_cutoff
        # A public provider can timestamp the bar at midnight while the
        # close-confirmed feature cutoff is later on the same local date.
        row.as_of_time = row.feature_cutoff - timedelta(hours=8)
    examples = build_sequence_examples(rows, target_name="direction_1d", window_sessions=20)
    assert examples


def test_sequence_walk_forward_fold_hash_uses_pydantic_fold_contract():
    examples = build_sequence_examples(_rows(1000), target_name="direction_1d", window_sessions=20)
    development, folds, holdout, stress, fold_hash = split_sequence_examples(
        examples, horizon=1
    )
    assert development
    assert folds
    assert holdout
    assert stress
    assert len(fold_hash) == 64
    assert folds[0][0].fold_id.startswith("wf-")


def test_sequence_runner_fits_true_window_and_is_reproducible(tmp_path):
    examples = build_sequence_examples(_rows(30), target_name="direction_1d", window_sessions=20)
    config = SequenceModelConfig(architecture="tcn", task="direction_1d", window_sessions=20, max_epochs=2, patience=1, hidden_size=8, tcn_blocks=1, attention_heads=1)
    first = SequenceTaskRunner(config, seed=42).fit(examples[:6], examples[6:])
    second = SequenceTaskRunner(config, seed=42).fit(examples[:6], examples[6:])
    assert first.predict_raw(examples[6:]) == second.predict_raw(examples[6:])
    assert first.artifact_hash() == second.artifact_hash()
    path = tmp_path / "sequence-test-model.pt"
    first.save(path)
    loaded = SequenceTaskRunner.load(path)
    assert loaded.predict_raw(examples[6:]) == first.predict_raw(examples[6:])


def test_all_sequence_architectures_consume_time_by_variable_windows():
    examples = build_sequence_examples(_rows(30), target_name="direction_1d", window_sessions=20)
    for architecture in ("patchtst", "tcn", "itransformer", "deep_mlp"):
        config = SequenceModelConfig(architecture=architecture, task="direction_1d", window_sessions=20, max_epochs=1, patience=1, hidden_size=8, attention_heads=1, tcn_blocks=1)
        runner = SequenceTaskRunner(config, seed=42).fit(examples[:6], examples[6:])
        assert len(runner.predict_raw(examples[6:])) == len(examples[6:])


def test_sequence_ensemble_abstains_on_model_disagreement():
    prediction, disagreement = weighted_direction_ensemble(
        {"patchtst": {"up": 0.9, "down": 0.05, "flat": 0.05}, "lightgbm": {"up": 0.1, "down": 0.8, "flat": 0.1}},
        {"patchtst": 0.5, "lightgbm": 0.5},
    )
    decision = decide_with_disagreement(prediction, {"patchtst": 0.5, "lightgbm": 0.5}, disagreement, threshold=0.30)
    assert decision.abstain
    assert "model_disagreement_above_threshold" in decision.reasons


def test_sequence_calibration_requires_time_oof_provenance():
    calibrators = fit_direction_calibrators(
        [{"up": 0.8, "down": 0.1, "flat": 0.1}, {"up": 0.1, "down": 0.8, "flat": 0.1}, {"up": 0.1, "down": 0.1, "flat": 0.8}],
        ["up", "down", "flat"], ["validation-1", "validation-2", "validation-3"],
        training_fold_ids=["train-1"],
    )
    assert set(calibrators) == {"up", "down", "flat"}


def test_sequence_metrics_are_grouped_by_market_regime():
    metrics = evaluate_predictions(
        "direction_1d",
        [[0.8, 0.1, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8], [0.7, 0.2, 0.1]],
        ["up", "down", "flat", "up"],
        regimes=["bull", "bear", "range", "bull"],
    )

    assert set(metrics["regime_metrics"]) == {"bull", "bear", "range"}
    assert metrics["regime_metrics"]["bull"]["sample_count"] == 2.0
