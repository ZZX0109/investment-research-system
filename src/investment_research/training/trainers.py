from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from investment_research.training.baseline import LinearRiskBaseline, PercentileCalibrator
from investment_research.training.models import CalibratedPrediction, FeatureContribution, PredictionExplanation, TrainingSample


class TrainerModel(Protocol):
    target_name: str

    def fit(self, samples: list[TrainingSample]):
        ...

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        ...

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        ...

    def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
        ...


class TrainerSpec(Protocol):
    name: str
    algorithm_family: str
    algorithm_name: str

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        ...


@dataclass(frozen=True)
class LinearBaselineTrainerSpec:
    name: str = "linear-baseline"
    algorithm_family: str = "linear_baseline"
    algorithm_name: str = "correlation_logit"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        return LinearRiskBaseline(target_name=target_name, threshold=drawdown_threshold)


class SklearnTrainerModel:
    def __init__(self, *, target_name: str, threshold: float, estimator, algorithm_name: str) -> None:
        self.target_name = target_name
        self.threshold = threshold
        self.estimator = estimator
        self.algorithm_name = algorithm_name
        self.feature_order: list[str] = []
        self.feature_stats: dict[str, tuple[float, float]] = {}
        self.calibrator = PercentileCalibrator()

    def fit(self, samples: list[TrainingSample]) -> "SklearnTrainerModel":
        if not samples:
            raise ValueError("samples must not be empty")
        self.feature_order = sorted(samples[0].features)
        for feature_name in self.feature_order:
            values = [sample.features.get(feature_name, 0.0) for sample in samples]
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            std = variance ** 0.5 if variance > 0 else 1.0
            self.feature_stats[feature_name] = (mean, std)
        matrix = [self._vectorize(sample) for sample in samples]
        labels = [self._target_label(sample) for sample in samples]
        self.estimator.fit(self._estimator_matrix(matrix), labels)
        raw_scores = self._predict_score_matrix(matrix)
        self.calibrator.fit(raw_scores, labels)
        return self

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        return self.predict_many([sample])[0]

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        if not samples:
            return []
        matrix = [self._vectorize(sample) for sample in samples]
        raw_scores = self._predict_score_matrix(matrix)
        predictions: list[CalibratedPrediction] = []
        for sample, raw in zip(samples, raw_scores):
            calibrated = self.calibrator.predict(raw)
            predictions.append(
                CalibratedPrediction(
                    symbol=sample.symbol,
                    as_of_date=sample.as_of_date,
                    raw_score=raw,
                    calibrated_score=calibrated,
                    target_name=self.target_name,
                    predicted_label=1 if calibrated >= 0.5 else 0,
                )
            )
        return predictions

    def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
        vector = self._vectorize(sample)
        if hasattr(self.estimator, "coef_"):
            weights = list(self.estimator.coef_[0])
        elif hasattr(self.estimator, "feature_importances_"):
            weights = list(self.estimator.feature_importances_)
        else:
            weights = [0.0 for _ in self.feature_order]

        contributions: list[FeatureContribution] = []
        for feature_name, feature_value, weight in zip(self.feature_order, vector, weights):
            contribution = feature_value * float(weight)
            if contribution == 0:
                continue
            contributions.append(
                FeatureContribution(
                    feature_name=feature_name,
                    contribution=contribution,
                    direction="up" if contribution > 0 else "down",
                )
            )
        top = sorted(contributions, key=lambda item: abs(item.contribution), reverse=True)[:top_k]
        summary = "No dominant contributors."
        if top:
            summary = ", ".join(f"{item.feature_name} ({item.direction}, {item.contribution:.3f})" for item in top)
        return PredictionExplanation(
            symbol=sample.symbol,
            as_of_date=sample.as_of_date,
            target_name=self.target_name,
            top_contributors=top,
            summary=summary,
        )

    def _vectorize(self, sample: TrainingSample) -> list[float]:
        vector: list[float] = []
        for feature_name in self.feature_order or sorted(sample.features):
            value = sample.features.get(feature_name, 0.0)
            mean, std = self.feature_stats[feature_name]
            vector.append(0.0 if std == 0 else (value - mean) / std)
        return vector

    def _predict_score_vector(self, vector: list[float]) -> float:
        return self._predict_score_matrix([vector])[0]

    def _predict_score_matrix(self, matrix: list[list[float]]) -> list[float]:
        if not matrix:
            return []
        values = self._estimator_matrix(matrix)
        if hasattr(self.estimator, "predict_proba"):
            probabilities = self.estimator.predict_proba(values)
            classes = list(getattr(self.estimator, "classes_", []))
            positive_index = classes.index(1) if 1 in classes else (1 if len(probabilities[0]) > 1 else 0)
            scores = [float(row[positive_index]) for row in probabilities]
        else:
            scores = [float(value) for value in self.estimator.predict(values)]
        return [min(1.0, max(0.0, score)) for score in scores]

    def _estimator_matrix(self, matrix: list[list[float]]):
        """Use the same named matrix contract for fit and inference.

        LightGBM records feature names even when its sklearn wrapper receives
        an unnamed array.  Supplying a DataFrame consistently prevents noisy
        feature-name warnings and, more importantly, makes column-order drift
        detectable at the estimator boundary.
        """
        import pandas as pd

        return pd.DataFrame(matrix, columns=self.feature_order, dtype=float)

    def _target_label(self, sample: TrainingSample) -> int:
        value = getattr(sample.labels, self.target_name)
        if value is None:
            return 0
        if "drawdown" in self.target_name:
            return 1 if value <= self.threshold else 0
        return 1 if value > 0 else 0


@dataclass(frozen=True)
class SklearnLogisticRegressionTrainerSpec:
    name: str = "logistic-regression"
    algorithm_family: str = "logistic_regression"
    algorithm_name: str = "sklearn_logistic_regression"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        from sklearn.linear_model import LogisticRegression

        return SklearnTrainerModel(
            target_name=target_name,
            threshold=drawdown_threshold,
            estimator=LogisticRegression(max_iter=200, class_weight="balanced", random_state=7),
            algorithm_name=self.algorithm_name,
        )


@dataclass(frozen=True)
class SklearnRandomForestTrainerSpec:
    name: str = "random-forest"
    algorithm_family: str = "random_forest"
    algorithm_name: str = "sklearn_random_forest"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        from sklearn.ensemble import RandomForestClassifier

        return SklearnTrainerModel(
            target_name=target_name,
            threshold=drawdown_threshold,
            estimator=RandomForestClassifier(
                n_estimators=100,
                max_depth=5,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                random_state=7,
                n_jobs=-1,
            ),
            algorithm_name=self.algorithm_name,
        )


@dataclass(frozen=True)
class OptionalDependencyTrainerSpec:
    name: str
    algorithm_family: str
    algorithm_name: str
    dependency_name: str

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        self.ensure_available()
        return LinearRiskBaseline(target_name=target_name, threshold=drawdown_threshold)

    def ensure_available(self) -> None:
        __import__(self.dependency_name)


class LightGBMTrainerModel(SklearnTrainerModel):
    """LightGBM-specific trainer with tree-specific defaults."""

    def __init__(self, *, target_name: str, threshold: float, **kwargs: int) -> None:
        import lightgbm as lgb

        estimator = lgb.LGBMClassifier(
            n_estimators=kwargs.pop("n_estimators", 200),
            max_depth=kwargs.pop("max_depth", 6),
            num_leaves=kwargs.pop("num_leaves", 31),
            learning_rate=kwargs.pop("learning_rate", 0.05),
            min_child_samples=kwargs.pop("min_child_samples", 5),
            class_weight=kwargs.pop("class_weight", "balanced"),
            random_state=7,
            verbose=-1,
            **kwargs,
        )
        super().__init__(
            target_name=target_name,
            threshold=threshold,
            estimator=estimator,
            algorithm_name="lightgbm_classifier",
        )


@dataclass(frozen=True)
class LightGBMTrainerSpec:
    name: str = "lightgbm"
    algorithm_family: str = "lightgbm"
    algorithm_name: str = "lightgbm_classifier"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        return LightGBMTrainerModel(target_name=target_name, threshold=drawdown_threshold)


@dataclass(frozen=True)
class CatBoostTrainerSpec:
    name: str = "catboost"
    algorithm_family: str = "catboost"
    algorithm_name: str = "catboost_classifier"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        from catboost import CatBoostClassifier

        estimator = CatBoostClassifier(
            iterations=250,
            depth=6,
            learning_rate=0.05,
            loss_function="Logloss",
            random_seed=7,
            verbose=False,
            allow_writing_files=False,
        )
        return SklearnTrainerModel(
            target_name=target_name,
            threshold=drawdown_threshold,
            estimator=estimator,
            algorithm_name=self.algorithm_name,
        )


@dataclass(frozen=True)
class XGBoostTrainerSpec:
    name: str = "xgboost"
    algorithm_family: str = "xgboost"
    algorithm_name: str = "xgboost_classifier"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        import xgboost as xgb

        estimator = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            scale_pos_weight=1.0,
            random_state=7,
            verbosity=0,
            n_jobs=1,
        )
        return SklearnTrainerModel(
            target_name=target_name,
            threshold=drawdown_threshold,
            estimator=estimator,
            algorithm_name="xgboost_classifier",
        )


@dataclass(frozen=True)
class DeepMLPTrainerSpec:
    """Simple deep learning MLP trainer using PyTorch.

    Provides a real deep learning alternative to the tree-based models.
    Architecture: 2-layer MLP with batch norm + dropout.
    """
    name: str = "deep-mlp"
    algorithm_family: str = "deep_learning"
    algorithm_name: str = "deep_mlp"

    def build(self, *, target_name: str, drawdown_threshold: float) -> TrainerModel:
        import torch
        import torch.nn as nn

        class MLPModel(nn.Module):
            def __init__(self, input_dim: int) -> None:
                super().__init__()
                self.net = nn.Sequential(
                    nn.Linear(input_dim, 64),
                    nn.BatchNorm1d(64),
                    nn.ReLU(),
                    nn.Dropout(0.3),
                    nn.Linear(64, 32),
                    nn.BatchNorm1d(32),
                    nn.ReLU(),
                    nn.Dropout(0.2),
                    nn.Linear(32, 1),
                )

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return self.net(x).squeeze(-1)

        class DeepMLPWrapper(SklearnTrainerModel):
            """Adapter that wraps PyTorch MLP into SklearnTrainerModel interface."""

            def __init__(self, *, target_name: str, threshold: float) -> None:
                self._target_name = target_name
                self._threshold = threshold
                self._mlp: MLPModel | None = None
                self.feature_order: list[str] = []
                self.feature_stats: dict[str, tuple[float, float]] = {}
                self.calibrator = PercentileCalibrator()
                self._fit_done = False

            @property
            def target_name(self) -> str:
                return self._target_name

            def fit(self, samples: list[TrainingSample]) -> "DeepMLPWrapper":
                import torch
                import torch.nn as nn
                import torch.optim as optim

                if not samples:
                    raise ValueError("samples must not be empty")
                torch.set_num_threads(1)
                torch.manual_seed(42)
                self.feature_order = sorted(samples[0].features)
                _compute_feature_stats(self.feature_order, samples, self.feature_stats)

                matrix = torch.tensor(
                    [self._vectorize(sample) for sample in samples],
                    dtype=torch.float32,
                )
                labels = torch.tensor(
                    [self._target_label(sample) for sample in samples],
                    dtype=torch.float32,
                )

                self._mlp = MLPModel(input_dim=len(self.feature_order))
                criterion = nn.BCEWithLogitsLoss()
                optimizer = optim.Adam(self._mlp.parameters(), lr=0.005, weight_decay=1e-4)
                scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, min_lr=1e-5)

                self._mlp.train()
                best_loss = float("inf")
                best_state: dict | None = None
                patience = 0
                for epoch in range(200):
                    optimizer.zero_grad()
                    outputs = self._mlp(matrix)
                    loss = criterion(outputs, labels)
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(self._mlp.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step(float(loss.detach().item()))

                    loss_val = loss.item()
                    patience = patience + 1 if loss_val >= best_loss else 0
                    if loss_val < best_loss:
                        best_loss = loss_val
                        best_state = {k: v.clone() for k, v in self._mlp.state_dict().items()}
                    if patience >= 10:
                        break

                if best_state is not None:
                    self._mlp.load_state_dict(best_state)
                self._mlp.eval()

                with torch.no_grad():
                    raw_scores = torch.sigmoid(self._mlp(matrix)).numpy().tolist()
                self.calibrator.fit(raw_scores, [int(l.item()) for l in labels])
                self._fit_done = True
                return self

            def predict(self, sample: TrainingSample) -> CalibratedPrediction:
                return self.predict_many([sample])[0]

            def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
                if not samples:
                    return []
                matrix = torch.tensor(
                    [self._vectorize(sample) for sample in samples],
                    dtype=torch.float32,
                )
                with torch.no_grad():
                    raw_scores = (
                        torch.sigmoid(self._mlp(matrix)).numpy().tolist()
                        if self._mlp
                        else [0.5 for _ in samples]
                    )
                predictions: list[CalibratedPrediction] = []
                for sample, raw in zip(samples, raw_scores):
                    raw_value = float(raw)
                    calibrated = self.calibrator.predict(raw_value)
                    predictions.append(
                        CalibratedPrediction(
                            symbol=sample.symbol,
                            as_of_date=sample.as_of_date,
                            raw_score=raw_value,
                            calibrated_score=calibrated,
                            target_name=self._target_name,
                            predicted_label=1 if calibrated >= 0.5 else 0,
                        )
                    )
                return predictions

            def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
                vector = torch.tensor([self._vectorize(sample)], dtype=torch.float32, requires_grad=True)
                if self._mlp is None:
                    return PredictionExplanation(
                        symbol=sample.symbol,
                        as_of_date=sample.as_of_date,
                        target_name=self._target_name,
                        top_contributors=[],
                        summary="Model not fitted.",
                    )
                self._mlp.eval()
                output = self._mlp(vector)
                self._mlp.zero_grad()
                output.backward()

                grads = vector.grad.squeeze(0).abs().numpy()
                contributions: list[FeatureContribution] = []
                for feature_name, grad in zip(self.feature_order, grads):
                    contributions.append(
                        FeatureContribution(
                            feature_name=feature_name,
                            contribution=float(grad),
                            direction="up",
                        )
                    )
                top = sorted(contributions, key=lambda c: c.contribution, reverse=True)[:top_k]
                summary = ", ".join(f"{c.feature_name} ({c.contribution:.4f})" for c in top)
                return PredictionExplanation(
                    symbol=sample.symbol,
                    as_of_date=sample.as_of_date,
                    target_name=self._target_name,
                    top_contributors=top,
                    summary=summary,
                )

            def _vectorize(self, sample: TrainingSample) -> list[float]:
                vector: list[float] = []
                for feature_name in self.feature_order or sorted(sample.features):
                    value = sample.features.get(feature_name, 0.0)
                    mean, std = self.feature_stats.get(feature_name, (0.0, 1.0))
                    vector.append(0.0 if std == 0 else (value - mean) / std)
                return vector

            def _target_label(self, sample: TrainingSample) -> int:
                value = getattr(sample.labels, self._target_name)
                if value is None:
                    return 0
                if "drawdown" in self._target_name:
                    return 1 if value <= self._threshold else 0
                return 1 if value > 0 else 0

        return DeepMLPWrapper(target_name=target_name, threshold=drawdown_threshold)


def _compute_feature_stats(
    feature_order: list[str],
    samples: list[TrainingSample],
    stats: dict[str, tuple[float, float]],
) -> None:
    for feature_name in feature_order:
        values = [sample.features.get(feature_name, 0.0) for sample in samples]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = variance ** 0.5 if variance > 0 else 1.0
        stats[feature_name] = (mean, std)


def default_trainer_specs() -> list[TrainerSpec]:
    return [
        LinearBaselineTrainerSpec(),
        SklearnLogisticRegressionTrainerSpec(),
        SklearnRandomForestTrainerSpec(),
        LightGBMTrainerSpec(),
        XGBoostTrainerSpec(),
        DeepMLPTrainerSpec(),
    ]
