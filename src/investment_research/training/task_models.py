from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from investment_research.training.models import TrainingSample


class TaskFamily(str, Enum):
    RISK = "risk"
    RETURN = "return"
    DIRECTION = "direction"


@dataclass(frozen=True)
class TaskScope:
    market: str
    decision_context: str
    task: TaskFamily
    horizon_days: int

    @property
    def key(self) -> str:
        return f"{self.market}:{self.decision_context}:{self.task.value}:{self.horizon_days}d"


class HistoricalDistributionBaseline:
    """Explainable baseline for return quantiles and drawdown probabilities."""

    def __init__(self, target_name: str, *, threshold: float | None = None) -> None:
        self.target_name = target_name
        self.threshold = threshold
        self.values: list[float] = []

    def fit(self, samples: list[TrainingSample]) -> "HistoricalDistributionBaseline":
        self.values = sorted(
            float(value)
            for sample in samples
            if sample.labels.label_available
            if (value := getattr(sample.labels, self.target_name)) is not None
        )
        if not self.values:
            raise ValueError("baseline has no available PIT labels")
        return self

    def predict(self) -> dict[str, float]:
        output = {
            "p10": _quantile(self.values, 0.1),
            "p50": _quantile(self.values, 0.5),
            "p90": _quantile(self.values, 0.9),
        }
        if self.threshold is not None:
            output["threshold_probability"] = sum(
                value <= self.threshold for value in self.values
            ) / len(self.values)
        return output


class MultinomialDirectionBaseline:
    def __init__(self, horizon_days: int) -> None:
        if horizon_days not in {1, 5, 20}:
            raise ValueError("direction horizon must be 1, 5, or 20")
        self.horizon_days = horizon_days
        self.feature_order: list[str] = []
        self.model = None

    def fit(self, samples: list[TrainingSample]) -> "MultinomialDirectionBaseline":
        from sklearn.linear_model import LogisticRegression

        target = f"direction_{self.horizon_days}d"
        eligible = [
            sample
            for sample in samples
            if sample.labels.label_available
            and getattr(sample.labels, target) in {"up", "down", "flat"}
        ]
        if not eligible:
            raise ValueError("direction baseline has no eligible labels")
        self.feature_order = sorted(
            {name for sample in eligible for name in sample.features}
        )
        matrix = [
            [float(sample.features.get(name, 0.0)) for name in self.feature_order]
            for sample in eligible
        ]
        labels = [getattr(sample.labels, target) for sample in eligible]
        self.model = LogisticRegression(
            max_iter=300, class_weight="balanced", random_state=42
        ).fit(matrix, labels)
        return self

    def predict(self, sample: TrainingSample) -> dict[str, float]:
        if self.model is None:
            raise ValueError("direction baseline is not fitted")
        vector = [
            [float(sample.features.get(name, 0.0)) for name in self.feature_order]
        ]
        values = self.model.predict_proba(vector)[0]
        output = {name: 0.0 for name in ("up", "down", "flat")}
        output.update(
            {
                str(name): float(value)
                for name, value in zip(self.model.classes_, values)
            }
        )
        return output


class TimeOOFWeightedEnsemble:
    def __init__(self) -> None:
        self.weights: list[float] = []

    def fit(self, model_brier_scores: list[float], *, from_time_oof: bool) -> None:
        if not from_time_oof:
            raise ValueError(
                "ensemble weights must be learned from time-out-of-fold scores"
            )
        inverse = [1.0 / max(score, 1e-6) for score in model_brier_scores]
        total = sum(inverse)
        self.weights = [value / total for value in inverse]

    def predict(self, probabilities: list[float]) -> float:
        if not self.weights or len(probabilities) != len(self.weights):
            raise ValueError("ensemble probabilities do not match fitted weights")
        return sum(
            weight * probability
            for weight, probability in zip(self.weights, probabilities)
        )


def _quantile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight
