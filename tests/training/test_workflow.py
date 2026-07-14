from datetime import date, datetime, timezone

from investment_research.training.models import (
    CalibratedPrediction,
    InstrumentType,
    LabelSet,
    Market,
    PreparedPriceBar,
    TrainingSample,
)
from investment_research.training.workflow import WalkForwardTrainingRunner


class BatchOnlyModel:
    target_name = "future_max_drawdown_20d"
    batch_calls = 0

    def fit(self, samples: list[TrainingSample]) -> "BatchOnlyModel":
        return self

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        raise AssertionError("workflow should use predict_many when available")

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        self.batch_calls += 1
        return [
            CalibratedPrediction(
                symbol=sample.symbol,
                as_of_date=sample.as_of_date,
                raw_score=0.4,
                calibrated_score=0.4,
                target_name=self.target_name,
                predicted_label=0,
            )
            for sample in samples
        ]

    def explain(self, sample: TrainingSample, *, top_k: int = 4):
        raise NotImplementedError


class BatchOnlyTrainerSpec:
    name = "batch-only"
    algorithm_family = "batch_only"
    algorithm_name = "batch_only"

    def __init__(self) -> None:
        self.model = BatchOnlyModel()

    def build(self, *, target_name: str, drawdown_threshold: float) -> BatchOnlyModel:
        self.model.target_name = target_name
        return self.model


def _sample(index: int, *, drawdown: float) -> TrainingSample:
    day = index + 1
    return TrainingSample(
        symbol=f"ETF{index % 2}",
        market=Market.US,
        instrument_type=InstrumentType.ETF,
        as_of_date=date(2026, 1, day),
        as_of_time=datetime(2026, 1, day, tzinfo=timezone.utc),
        feature_cutoff=datetime(2026, 1, day, 23, tzinfo=timezone.utc),
        feature_version="f-v1",
        data_version="d-v1",
        features={
            "ret_20d": -0.01 * index,
            "vol_20d": 0.01 + 0.003 * index,
            "relative_strength_20d": -0.02 * index,
            "news_count_7d": float(index % 4),
        },
        labels=LabelSet(
            symbol=f"ETF{index % 2}",
            as_of_date=date(2026, 1, day),
            future_max_drawdown_20d=drawdown,
        ),
    )


def _reference_bar(index: int, *, close_value: float) -> PreparedPriceBar:
    day = index + 1
    return PreparedPriceBar(
        symbol="SPY",
        trade_date=date(2026, 1, day),
        close_native=close_value,
        close_normalized=close_value,
        volume=1000.0,
        currency="USD",
        target_currency="USD",
        is_halted=False,
        is_suspended=False,
        published_at=datetime(2026, 1, day, tzinfo=timezone.utc),
    )


def test_walk_forward_training_runner_emits_model_card_and_fold_results() -> None:
    samples = [_sample(index, drawdown=(-0.12 if index % 3 == 0 else -0.03)) for index in range(30)]

    runner = WalkForwardTrainingRunner(target_name="future_max_drawdown_20d")
    card, fold_results = runner.run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert card.algorithm_name == "correlation_logit"
    assert card.calibration_method == "bucket_frequency"
    assert card.validation_metrics
    assert fold_results
    assert fold_results[0].predictions


def test_walk_forward_training_runner_uses_regime_reference_when_provided() -> None:
    samples = [_sample(index, drawdown=(-0.12 if index % 3 == 0 else -0.03)) for index in range(30)]
    regime_reference = [_reference_bar(index, close_value=100.0 + (index * 5.0)) for index in range(30)]

    runner = WalkForwardTrainingRunner(target_name="future_max_drawdown_20d")
    card, fold_results = runner.run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
        regime_reference=regime_reference,
    )

    assert fold_results
    assert any(result.fold.regime == "bull" for result in fold_results)
    assert any(note.startswith("regime_summary: regime=bull") for note in card.notes)


def test_walk_forward_training_runner_prefers_batch_prediction() -> None:
    samples = [_sample(index, drawdown=(-0.12 if index % 3 == 0 else -0.03)) for index in range(30)]
    spec = BatchOnlyTrainerSpec()

    runner = WalkForwardTrainingRunner(target_name="future_max_drawdown_20d", trainer_spec=spec)
    _, fold_results = runner.run(
        samples=samples,
        train_window_days=12,
        validation_window_days=6,
        step_days=6,
    )

    assert fold_results
    assert spec.model.batch_calls == len(fold_results)
