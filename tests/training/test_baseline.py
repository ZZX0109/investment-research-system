from datetime import date, datetime, timezone

from investment_research.training.baseline import LinearRiskBaseline
from investment_research.training.models import (
    InstrumentType,
    LabelSet,
    Market,
    TrainingSample,
)


def _sample(index: int, *, risk_value: float) -> TrainingSample:
    return TrainingSample(
        symbol=f"SYM{index}",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        as_of_date=date(2026, 1, index + 1),
        as_of_time=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
        feature_cutoff=datetime(2026, 1, index + 1, 23, tzinfo=timezone.utc),
        feature_version="f-v1",
        data_version="d-v1",
        features={
            "ret_20d": -0.1 * index,
            "vol_20d": 0.02 * index,
            "news_count_7d": float(index % 3),
        },
        labels=LabelSet(
            symbol=f"SYM{index}",
            as_of_date=date(2026, 1, index + 1),
            future_max_drawdown_20d=risk_value,
        ),
    )


def test_linear_baseline_produces_calibrated_predictions_and_explanations() -> None:
    samples = [
        _sample(1, risk_value=-0.02),
        _sample(2, risk_value=-0.03),
        _sample(3, risk_value=-0.12),
        _sample(4, risk_value=-0.15),
        _sample(5, risk_value=-0.18),
    ]
    model = LinearRiskBaseline(target_name="future_max_drawdown_20d").fit(samples)

    prediction = model.predict(samples[-1])
    explanation = model.explain(samples[-1])

    assert 0.0 <= prediction.raw_score <= 1.0
    assert 0.0 <= prediction.calibrated_score <= 1.0
    assert explanation.top_contributors
    assert explanation.summary
