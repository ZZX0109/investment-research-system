"""Tests for deep time-series trainers: PatchTST, TCN, iTransformer."""

from datetime import date, datetime, timezone

from investment_research.training.deep_trainers import (
    PatchTSTModel,
    PatchTSTTrainerSpec,
    TCNModel,
    TCNTrainerSpec,
    iTransformerModel,
    iTransformerTrainerSpec,
    deep_trainer_specs,
)
from investment_research.training.models import (
    CalibratedPrediction,
    InstrumentType,
    LabelSet,
    Market,
    TrainingSample,
)


def _make_samples(n: int = 60) -> list[TrainingSample]:
    samples = []
    for i in range(n):
        samples.append(
            TrainingSample(
                symbol="AAPL",
                market=Market.US,
                instrument_type=InstrumentType.EQUITY,
                as_of_date=date(2023, 1, 1) + __import__("datetime", fromlist=["timedelta"]).timedelta(days=i),
                as_of_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
                feature_cutoff=datetime(2023, 1, 1, 23, 59, tzinfo=timezone.utc),
                feature_version="v1",
                data_version="v1",
                features={
                    "ret_5d": i * 0.001,
                    "ret_20d": i * 0.002,
                    "vol_5d": 0.01 + i * 0.0005,
                    "vol_20d": 0.015 + i * 0.0003,
                    "volume_z_20d": (i - n / 2) / n,
                    "halted_flag": 0.0,
                    "news_count_7d": float(i % 3),
                    "filing_count_30d": float(i % 5),
                    "earnings_count_30d": float(i % 7),
                    "market_cn_flag": 0.0,
                    "benchmark_ret_20d": i * 0.001,
                    "relative_strength_20d": i * 0.001,
                },
                labels=LabelSet(
                    symbol="AAPL",
                    as_of_date=date(2023, 1, 1),
                    future_max_drawdown_20d=(-0.05 - i * 0.002) if i < n / 2 else (-0.03 - i * 0.001),
                ),
            )
        )
    return samples


class TestPatchTSTModel:
    def test_fit_predict_explain(self):
        samples = _make_samples(60)
        model = PatchTSTModel(
            target_name="future_max_drawdown_20d",
            threshold=-0.08,
        ).fit(samples)

        assert model._model is not None
        assert len(model.feature_order) > 0

        pred = model.predict(samples[0])
        assert isinstance(pred, CalibratedPrediction)
        assert 0.0 <= pred.calibrated_score <= 1.0

        expl = model.explain(samples[0], top_k=4)
        assert expl.symbol == "AAPL"
        assert len(expl.top_contributors) > 0

    def test_trainer_spec(self):
        spec = PatchTSTTrainerSpec()
        assert spec.algorithm_family == "patchtst"
        model = spec.build(target_name="future_max_drawdown_20d", drawdown_threshold=-0.08)
        assert model.target_name == "future_max_drawdown_20d"

    def test_raises_on_empty(self):
        import pytest

        model = PatchTSTModel(target_name="x", threshold=-0.08)
        with pytest.raises(ValueError):
            model.fit([])


class TestTCNModel:
    def test_fit_predict_explain(self):
        samples = _make_samples(60)
        model = TCNModel(
            target_name="future_max_drawdown_20d",
            threshold=-0.08,
        ).fit(samples)

        assert model._model is not None
        assert len(model.feature_order) > 0

        pred = model.predict(samples[0])
        assert isinstance(pred, CalibratedPrediction)
        assert 0.0 <= pred.calibrated_score <= 1.0

        expl = model.explain(samples[0], top_k=4)
        assert expl.symbol == "AAPL"
        assert len(expl.top_contributors) > 0

    def test_trainer_spec(self):
        spec = TCNTrainerSpec()
        assert spec.algorithm_family == "tcn"
        model = spec.build(target_name="future_max_drawdown_20d", drawdown_threshold=-0.08)
        assert model.target_name == "future_max_drawdown_20d"


class TestiTransformerModel:
    def test_fit_predict_explain(self):
        samples = _make_samples(60)
        model = iTransformerModel(
            target_name="future_max_drawdown_20d",
            threshold=-0.08,
        ).fit(samples)

        assert model._model is not None
        assert len(model.feature_order) > 0

        pred = model.predict(samples[0])
        assert isinstance(pred, CalibratedPrediction)
        assert 0.0 <= pred.calibrated_score <= 1.0

        expl = model.explain(samples[0], top_k=4)
        assert expl.symbol == "AAPL"
        assert len(expl.top_contributors) > 0

    def test_trainer_spec(self):
        spec = iTransformerTrainerSpec()
        assert spec.algorithm_family == "itransformer"
        model = spec.build(target_name="future_max_drawdown_20d", drawdown_threshold=-0.08)
        assert model.target_name == "future_max_drawdown_20d"


class TestDeepTrainerSpecs:
    def test_deep_trainer_specs_returns_three(self):
        specs = deep_trainer_specs()
        assert len(specs) == 3
        families = {spec.algorithm_family for spec in specs}
        assert families == {"patchtst", "tcn", "itransformer"}
