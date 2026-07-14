from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt

from investment_research.training.models import CalibratedPrediction, FeatureContribution, PredictionExplanation, TrainingSample


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = exp(-value)
        return 1.0 / (1.0 + z)
    z = exp(value)
    return z / (1.0 + z)


@dataclass(frozen=True)
class FeatureStats:
    mean: float
    std: float


class PercentileCalibrator:
    def __init__(self, *, bucket_count: int = 10) -> None:
        self.bucket_count = max(2, bucket_count)
        self.boundaries: list[float] = []
        self.bucket_means: list[float] = []

    def fit(self, scores: list[float], labels: list[int]) -> "PercentileCalibrator":
        if len(scores) != len(labels):
            raise ValueError("scores and labels must have the same length")
        if not scores:
            self.boundaries = [0.0, 1.0]
            self.bucket_means = [0.5]
            return self

        ordered = sorted(zip(scores, labels), key=lambda item: item[0])
        chunk_size = max(1, len(ordered) // self.bucket_count)
        boundaries = [0.0]
        bucket_means: list[float] = []
        for index in range(0, len(ordered), chunk_size):
            chunk = ordered[index : index + chunk_size]
            bucket_means.append(sum(label for _, label in chunk) / len(chunk))
            boundaries.append(chunk[-1][0])
        boundaries[-1] = 1.0
        self.boundaries = boundaries
        self.bucket_means = bucket_means
        return self

    def predict(self, score: float) -> float:
        if not self.bucket_means:
            return score
        for index in range(len(self.bucket_means)):
            lower = self.boundaries[index]
            upper = self.boundaries[index + 1] if index + 1 < len(self.boundaries) else 1.0
            if lower <= score <= upper:
                return self.bucket_means[index]
        return self.bucket_means[-1]


class LinearRiskBaseline:
    def __init__(self, *, target_name: str, threshold: float = -0.08) -> None:
        self.target_name = target_name
        self.threshold = threshold
        self.feature_order: list[str] = []
        self.feature_stats: dict[str, FeatureStats] = {}
        self.weights: dict[str, float] = {}
        self.intercept: float = 0.0
        self.calibrator = PercentileCalibrator()

    def fit(self, samples: list[TrainingSample]) -> "LinearRiskBaseline":
        if not samples:
            raise ValueError("samples must not be empty")
        self.feature_order = sorted(samples[0].features)
        labels = [self._target_label(sample) for sample in samples]
        positive_rate = sum(labels) / len(labels)
        self.intercept = _safe_logit(positive_rate)

        for feature_name in self.feature_order:
            values = [sample.features.get(feature_name, 0.0) for sample in samples]
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            std = sqrt(variance) if variance > 0 else 1.0
            self.feature_stats[feature_name] = FeatureStats(mean=mean, std=std)
            standardized = [self._standardize(feature_name, value) for value in values]
            self.weights[feature_name] = _correlation(standardized, labels)

        raw_scores = [self.predict_raw(sample) for sample in samples]
        self.calibrator.fit(raw_scores, labels)
        return self

    def predict_raw(self, sample: TrainingSample) -> float:
        total = self.intercept
        for feature_name in self.feature_order:
            total += self.weights.get(feature_name, 0.0) * self._standardize(feature_name, sample.features.get(feature_name, 0.0))
        return _sigmoid(total)

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        raw = self.predict_raw(sample)
        calibrated = self.calibrator.predict(raw)
        return CalibratedPrediction(
            symbol=sample.symbol,
            as_of_date=sample.as_of_date,
            raw_score=raw,
            calibrated_score=calibrated,
            target_name=self.target_name,
            predicted_label=1 if calibrated >= 0.5 else 0,
        )

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        return [self.predict(sample) for sample in samples]

    def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
        contributions: list[FeatureContribution] = []
        for feature_name in self.feature_order:
            standardized = self._standardize(feature_name, sample.features.get(feature_name, 0.0))
            contribution = self.weights.get(feature_name, 0.0) * standardized
            if contribution == 0:
                continue
            contributions.append(
                FeatureContribution(
                    feature_name=feature_name,
                    contribution=contribution,
                    direction="up" if contribution > 0 else "down",
                )
            )
        ordered = sorted(contributions, key=lambda item: abs(item.contribution), reverse=True)[:top_k]
        summary = "No dominant contributors."
        if ordered:
            summary = ", ".join(
                f"{item.feature_name} ({item.direction}, {item.contribution:.3f})"
                for item in ordered
            )
        return PredictionExplanation(
            symbol=sample.symbol,
            as_of_date=sample.as_of_date,
            target_name=self.target_name,
            top_contributors=ordered,
            summary=summary,
        )

    def _target_label(self, sample: TrainingSample) -> int:
        value = getattr(sample.labels, self.target_name)
        if value is None:
            return 0
        if "drawdown" in self.target_name:
            return 1 if value <= self.threshold else 0
        return 1 if value > 0 else 0

    def _standardize(self, feature_name: str, value: float) -> float:
        stats = self.feature_stats.get(feature_name)
        if stats is None or stats.std == 0:
            return 0.0
        return (value - stats.mean) / stats.std


def _correlation(values: list[float], labels: list[int]) -> float:
    if len(values) != len(labels) or len(values) < 2:
        return 0.0
    label_mean = sum(labels) / len(labels)
    value_mean = sum(values) / len(values)
    numerator = sum((value - value_mean) * (label - label_mean) for value, label in zip(values, labels))
    value_var = sum((value - value_mean) ** 2 for value in values)
    label_var = sum((label - label_mean) ** 2 for label in labels)
    denominator = sqrt(value_var * label_var)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _safe_logit(probability: float) -> float:
    clipped = min(0.999, max(0.001, probability))
    return log(clipped / (1.0 - clipped))
