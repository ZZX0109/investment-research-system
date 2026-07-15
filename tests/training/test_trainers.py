from datetime import date, datetime, timedelta, timezone

import pytest

from investment_research.training.models import InstrumentType, LabelSet, Market, TrainingSample
from investment_research.training.trainers import (
    DeepMLPTrainerSpec,
    LightGBMTrainerSpec,
    SklearnLogisticRegressionTrainerSpec,
    SklearnRandomForestTrainerSpec,
    XGBoostTrainerSpec,
    default_trainer_specs,
)


def _sample(index: int, *, drawdown: float) -> TrainingSample:
    sample_date = date(2026, 1, 1) + timedelta(days=index)
    return TrainingSample(
        symbol=f"EQ{index % 2}",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        as_of_date=sample_date,
        as_of_time=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc),
        feature_cutoff=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=23),
        feature_version="f-v1",
        data_version="d-v1",
        features={
            "ret_20d": -0.02 * index,
            "vol_20d": 0.01 + 0.002 * index,
            "relative_strength_20d": -0.015 * index,
            "news_count_7d": float(index % 3),
        },
        labels=LabelSet(
            symbol=f"EQ{index % 2}",
            as_of_date=sample_date,
            future_max_drawdown_20d=drawdown,
        ),
    )


def test_sklearn_logistic_trainer_emits_prediction_and_explanation() -> None:
    trainer = SklearnLogisticRegressionTrainerSpec().build(
        target_name="future_max_drawdown_20d",
        drawdown_threshold=-0.08,
    )
    samples = [_sample(index, drawdown=(-0.12 if index % 3 == 0 else -0.03)) for index in range(24)]
    trainer.fit(samples)

    prediction = trainer.predict(samples[-1])
    explanation = trainer.explain(samples[-1])

    assert 0.0 <= prediction.calibrated_score <= 1.0
    assert explanation.top_contributors


def test_sklearn_random_forest_trainer_emits_prediction_and_explanation() -> None:
    trainer = SklearnRandomForestTrainerSpec().build(
        target_name="future_max_drawdown_20d",
        drawdown_threshold=-0.08,
    )
    samples = [_sample(index, drawdown=(-0.11 if index % 4 == 0 else -0.02)) for index in range(24)]
    trainer.fit(samples)

    prediction = trainer.predict(samples[-1])
    explanation = trainer.explain(samples[-1])

    assert 0.0 <= prediction.raw_score <= 1.0
    assert explanation.summary


def test_sklearn_random_forest_batch_prediction_matches_single_prediction() -> None:
    trainer = SklearnRandomForestTrainerSpec().build(
        target_name="future_max_drawdown_20d",
        drawdown_threshold=-0.08,
    )
    samples = [_sample(index, drawdown=(-0.11 if index % 4 == 0 else -0.02)) for index in range(24)]
    trainer.fit(samples)

    batch_predictions = trainer.predict_many(samples[-5:])
    single_predictions = [trainer.predict(sample) for sample in samples[-5:]]

    assert [item.raw_score for item in batch_predictions] == pytest.approx(
        [item.raw_score for item in single_predictions]
    )
    assert [item.calibrated_score for item in batch_predictions] == pytest.approx(
        [item.calibrated_score for item in single_predictions]
    )


def test_lightgbm_trainer_emits_prediction_and_explanation() -> None:
    trainer = LightGBMTrainerSpec().build(
        target_name="future_max_drawdown_20d",
        drawdown_threshold=-0.08,
    )
    samples = [_sample(index, drawdown=(-0.10 if index % 5 == 0 else -0.04)) for index in range(24)]
    trainer.fit(samples)

    prediction = trainer.predict(samples[-1])
    explanation = trainer.explain(samples[-1])

    assert 0.0 <= prediction.calibrated_score <= 1.0
    assert explanation.top_contributors is not None


def test_xgboost_trainer_emits_prediction_and_explanation() -> None:
    trainer = XGBoostTrainerSpec().build(
        target_name="future_max_drawdown_20d",
        drawdown_threshold=-0.08,
    )
    samples = [_sample(index, drawdown=(-0.11 if index % 3 == 0 else -0.05)) for index in range(24)]
    trainer.fit(samples)

    prediction = trainer.predict(samples[-1])
    explanation = trainer.explain(samples[-1])

    assert 0.0 <= prediction.raw_score <= 1.0
    assert explanation.summary


def test_deep_mlp_trainer_emits_prediction_and_explanation() -> None:
    trainer = DeepMLPTrainerSpec().build(
        target_name="future_max_drawdown_20d",
        drawdown_threshold=-0.08,
    )
    samples = [_sample(index, drawdown=(-0.09 if index % 4 == 0 else -0.03)) for index in range(24)]
    trainer.fit(samples)

    prediction = trainer.predict(samples[-1])
    explanation = trainer.explain(samples[-1])

    assert 0.0 <= prediction.calibrated_score <= 1.0
    assert explanation.top_contributors is not None


def test_default_trainer_specs_includes_all_models() -> None:
    specs = default_trainer_specs()
    names = {s.name for s in specs}
    expected = {
        "linear-baseline",
        "logistic-regression",
        "random-forest",
        "lightgbm",
        "xgboost",
        "deep-mlp",
    }
    assert names == expected
