"""Deep time-series trainers: PatchTST, TCN, iTransformer.

Each trainer implements the TrainerModel protocol (fit/predict/explain) and is
wrapped by a TrainerSpec for integration with the walk-forward validation
framework. All models operate on the same feature vectors as the existing
trainers by treating each feature as a univariate time-step channel.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

import torch
import torch.nn as nn
import torch.optim as optim

from investment_research.training.baseline import PercentileCalibrator
from investment_research.training.models import (
    CalibratedPrediction,
    FeatureContribution,
    PredictionExplanation,
    TrainingSample,
)


# ──────────────────────────────────────────────
#  Shared utilities
# ──────────────────────────────────────────────

DEFAULT_DEEP_MAX_EPOCHS = 24
DEFAULT_DEEP_PATIENCE = 4
DEFAULT_DEEP_MAX_SAMPLES = 4096


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _deep_max_epochs() -> int:
    return _env_int("INVESTMENT_RESEARCH_DEEP_MAX_EPOCHS", DEFAULT_DEEP_MAX_EPOCHS)


def _deep_patience() -> int:
    return _env_int("INVESTMENT_RESEARCH_DEEP_PATIENCE", DEFAULT_DEEP_PATIENCE)


def _deep_max_samples() -> int:
    return _env_int("INVESTMENT_RESEARCH_DEEP_MAX_SAMPLES", DEFAULT_DEEP_MAX_SAMPLES)

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


def _standardize(values: list[float], mean: float, std: float) -> float:
    return 0.0 if std == 0 else (values - mean) / std


# ──────────────────────────────────────────────
#  Base wrapper
# ──────────────────────────────────────────────

class _DeepTrainerBase:
    """Shared logic for PyTorch-based trainers."""

    def __init__(self, target_name: str, threshold: float):
        self._target_name = target_name
        self._threshold = threshold
        self.feature_order: list[str] = []
        self.feature_stats: dict[str, tuple[float, float]] = {}
        self.calibrator = PercentileCalibrator()

    @property
    def target_name(self) -> str:
        return self._target_name

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

    def _bounded_fit_samples(self, samples: list[TrainingSample]) -> list[TrainingSample]:
        max_samples = _deep_max_samples()
        if len(samples) <= max_samples:
            return samples
        step = len(samples) / max_samples
        return [samples[min(int(index * step), len(samples) - 1)] for index in range(max_samples)]

    def _predictions_from_scores(
        self,
        samples: list[TrainingSample],
        raw_scores: list[float],
    ) -> list[CalibratedPrediction]:
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

    def _explain_from_gradient(self, sample: TrainingSample, grads: list[float], top_k: int = 4) -> PredictionExplanation:
        contributions: list[FeatureContribution] = []
        for feature_name, grad in zip(self.feature_order, grads):
            contributions.append(
                FeatureContribution(
                    feature_name=feature_name,
                    contribution=float(abs(grad)),
                    direction="up",
                )
            )
        top = sorted(contributions, key=lambda c: c.contribution, reverse=True)[:top_k]
        summary = ", ".join(f"{c.feature_name} ({c.contribution:.4f})" for c in top) if top else "No contributors"
        return PredictionExplanation(
            symbol=sample.symbol,
            as_of_date=sample.as_of_date,
            target_name=self._target_name,
            top_contributors=top,
            summary=summary,
        )


# ──────────────────────────────────────────────
#  PatchTST
# ──────────────────────────────────────────────

class PatchTSTModel(_DeepTrainerBase):
    """Patch-based Time Series Transformer.

    Splits the feature vector into patches, projects each patch,
    and applies a lightweight Transformer encoder.
    """

    def __init__(
        self,
        target_name: str,
        threshold: float,
        *,
        patch_len: int = 4,
        stride: int = 2,
        d_model: int = 32,
        n_heads: int = 4,
        n_layers: int = 2,
        dropout: float = 0.1,
    ):
        super().__init__(target_name, threshold)
        self.patch_len = patch_len
        self.stride = stride
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.dropout = dropout
        self._model: Optional["_PatchTSTNetwork"] = None

    def fit(self, samples: list[TrainingSample]) -> "PatchTSTModel":
        if not samples:
            raise ValueError("samples must not be empty")
        self.feature_order = sorted(samples[0].features)
        _compute_feature_stats(self.feature_order, samples, self.feature_stats)
        fit_samples = self._bounded_fit_samples(samples)

        # (n_samples, n_features) -> (n_samples, 1, n_features)
        matrix = torch.tensor(
            [self._vectorize(s) for s in fit_samples],
            dtype=torch.float32,
        ).unsqueeze(1)
        labels = torch.tensor(
            [self._target_label(s) for s in fit_samples],
            dtype=torch.float32,
        )

        n_vars, seq_len = 1, len(self.feature_order)
        self._model = _PatchTSTNetwork(
            n_vars=n_vars,
            seq_len=seq_len,
            patch_len=self.patch_len,
            stride=self.stride,
            d_model=self.d_model,
            n_heads=self.n_heads,
            n_layers=self.n_layers,
            dropout=self.dropout,
        )

        criterion = nn.BCEWithLogitsLoss()
        optimizer = optim.Adam(self._model.parameters(), lr=0.003, weight_decay=1e-4)
        early_stop_patience = _deep_patience()
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=early_stop_patience, min_lr=1e-5)

        self._model.train()
        best_loss = float("inf")
        best_state = None
        patience = 0
        for epoch in range(_deep_max_epochs()):
            optimizer.zero_grad()
            outputs = self._model(matrix).view(-1)
            loss = criterion(outputs, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
            optimizer.step()
            scheduler.step(loss)

            loss_val = loss.item()
            patience = patience + 1 if loss_val >= best_loss else 0
            if loss_val < best_loss:
                best_loss = loss_val
                best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
            if patience >= early_stop_patience:
                break

        if best_state is not None:
            self._model.load_state_dict(best_state)
        self._model.eval()

        with torch.no_grad():
            raw_scores = torch.sigmoid(self._model(matrix).view(-1)).numpy().tolist()
        self.calibrator.fit(raw_scores, [int(l.item()) for l in labels])
        return self

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        return self.predict_many([sample])[0]

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        if not samples:
            return []
        matrix = torch.tensor(
            [self._vectorize(sample) for sample in samples],
            dtype=torch.float32,
        ).unsqueeze(1)
        with torch.no_grad():
            raw_scores = (
                torch.sigmoid(self._model(matrix).view(-1)).numpy().tolist()
                if self._model
                else [0.5 for _ in samples]
            )
        return self._predictions_from_scores(samples, raw_scores)

    def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
        if self._model is None:
            return self._explain_from_gradient(sample, [0.0] * len(self.feature_order))
        vec = torch.tensor(
            [[self._vectorize(sample)]], dtype=torch.float32, requires_grad=True
        )
        self._model.eval()
        output = self._model(vec)
        self._model.zero_grad()
        output.backward()
        grads = vec.grad.flatten().abs().tolist()
        return self._explain_from_gradient(sample, grads, top_k)


class _PatchTSTNetwork(torch.nn.Module):
    def __init__(self, n_vars, seq_len, patch_len, stride, d_model, n_heads, n_layers, dropout):
        import torch
        import torch.nn as nn

        super().__init__()
        self.patch_len = patch_len
        self.stride = stride
        self.n_patches = max(1, (seq_len - patch_len) // stride + 1)

        self.patch_proj = nn.Linear(patch_len, d_model)
        self.pos_embed = nn.Parameter(torch.randn(1, self.n_patches, d_model) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 2,
            dropout=dropout, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, 1),
        )

    def forward(self, x):
        # x: (batch, n_vars, seq_len)
        b, n_vars, seq_len = x.shape
        # Create patches across seq_len
        patches = x.unfold(dimension=2, size=self.patch_len, step=self.stride)
        # patches: (batch, n_vars, n_patches, patch_len)
        patches = patches.contiguous().view(b * n_vars, self.n_patches, self.patch_len)

        # Project patches
        patch_emb = self.patch_proj(patches)  # (b*n_vars, n_patches, d_model)
        patch_emb = patch_emb + self.pos_embed[:, : self.n_patches, :]

        # Transformer
        encoded = self.encoder(patch_emb)  # (b*n_vars, n_patches, d_model)

        # Mean pooling over patches
        pooled = encoded.mean(dim=1)  # (b*n_vars, d_model)
        pooled = pooled.view(b, n_vars, -1).mean(dim=1)  # (b, d_model)
        return self.head(pooled)


@dataclass(frozen=True)
class PatchTSTTrainerSpec:
    name: str = "patchtst"
    algorithm_family: str = "patchtst"
    algorithm_name: str = "patchtst_classifier"

    def build(self, *, target_name: str, drawdown_threshold: float):
        return PatchTSTModel(target_name=target_name, threshold=drawdown_threshold)


# ──────────────────────────────────────────────
#  TCN
# ──────────────────────────────────────────────

class TCNModel(_DeepTrainerBase):
    """Temporal Convolutional Network.

    Uses stacked dilated causal convolutions over the feature vector treated
    as a 1-D sequence.
    """

    def __init__(
        self,
        target_name: str,
        threshold: float,
        *,
        n_channels: int = 32,
        kernel_size: int = 3,
        n_blocks: int = 3,
        dropout: float = 0.1,
    ):
        super().__init__(target_name, threshold)
        self.n_channels = n_channels
        self.kernel_size = kernel_size
        self.n_blocks = n_blocks
        self.dropout = dropout
        self._model: Optional["_TCNNetwork"] = None

    def fit(self, samples: list[TrainingSample]) -> "TCNModel":
        import torch
        import torch.nn as nn
        import torch.optim as optim

        if not samples:
            raise ValueError("samples must not be empty")
        self.feature_order = sorted(samples[0].features)
        _compute_feature_stats(self.feature_order, samples, self.feature_stats)
        fit_samples = self._bounded_fit_samples(samples)

        # (n_samples, n_features) -> (n_samples, 1, n_features)
        matrix = torch.tensor(
            [self._vectorize(s) for s in fit_samples],
            dtype=torch.float32,
        ).unsqueeze(1)
        labels = torch.tensor(
            [self._target_label(s) for s in fit_samples],
            dtype=torch.float32,
        )

        n_vars, seq_len = 1, len(self.feature_order)
        self._model = _TCNNetwork(
            n_vars=n_vars,
            seq_len=seq_len,
            n_channels=self.n_channels,
            kernel_size=self.kernel_size,
            n_blocks=self.n_blocks,
            dropout=self.dropout,
        )

        criterion = nn.BCEWithLogitsLoss()
        optimizer = optim.Adam(self._model.parameters(), lr=0.003, weight_decay=1e-4)
        early_stop_patience = _deep_patience()
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=early_stop_patience, min_lr=1e-5)

        self._model.train()
        best_loss = float("inf")
        best_state = None
        patience = 0
        for epoch in range(_deep_max_epochs()):
            optimizer.zero_grad()
            outputs = self._model(matrix).view(-1)
            loss = criterion(outputs, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
            optimizer.step()
            scheduler.step(loss)

            loss_val = loss.item()
            patience = patience + 1 if loss_val >= best_loss else 0
            if loss_val < best_loss:
                best_loss = loss_val
                best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
            if patience >= early_stop_patience:
                break

        if best_state is not None:
            self._model.load_state_dict(best_state)
        self._model.eval()

        with torch.no_grad():
            raw_scores = torch.sigmoid(self._model(matrix).view(-1)).numpy().tolist()
        self.calibrator.fit(raw_scores, [int(l.item()) for l in labels])
        return self

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        return self.predict_many([sample])[0]

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        if not samples:
            return []
        matrix = torch.tensor(
            [self._vectorize(sample) for sample in samples],
            dtype=torch.float32,
        ).unsqueeze(1)
        with torch.no_grad():
            raw_scores = (
                torch.sigmoid(self._model(matrix).view(-1)).numpy().tolist()
                if self._model
                else [0.5 for _ in samples]
            )
        return self._predictions_from_scores(samples, raw_scores)

    def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
        if self._model is None:
            return self._explain_from_gradient(sample, [0.0] * len(self.feature_order))
        vec = torch.tensor(
            [[self._vectorize(sample)]], dtype=torch.float32, requires_grad=True
        )
        self._model.eval()
        output = self._model(vec)
        self._model.zero_grad()
        output.backward()
        grads = vec.grad.flatten().abs().tolist()
        return self._explain_from_gradient(sample, grads, top_k)


class _TCNNetwork(nn.Module):
    """Stacked dilated causal convolutions."""

    def __init__(self, n_vars, seq_len, n_channels, kernel_size, n_blocks, dropout):
        super().__init__()
        layers = []
        in_ch = n_vars
        for i in range(n_blocks):
            dilation = 2 ** i
            layers.append(
                nn.Conv1d(
                    in_ch, n_channels, kernel_size,
                    padding=(kernel_size - 1) * dilation,
                    dilation=dilation,
                )
            )
            layers.append(nn.BatchNorm1d(n_channels))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout))
            in_ch = n_channels

        self.conv_blocks = nn.Sequential(*layers)
        self.head = nn.Linear(n_channels, 1)
        self._kernel_size = kernel_size
        self._dilations = [2 ** i for i in range(n_blocks)]
        self._receptive_field = sum((kernel_size - 1) * d for d in self._dilations) + 1

    def forward(self, x):
        # x: (batch, n_vars, seq_len)
        out = self.conv_blocks(x)  # (batch, n_channels, seq_len)
        pooled = out.mean(dim=2)  # (batch, n_channels)
        return self.head(pooled)


@dataclass(frozen=True)
class TCNTrainerSpec:
    name: str = "tcn"
    algorithm_family: str = "tcn"
    algorithm_name: str = "tcn_classifier"

    def build(self, *, target_name: str, drawdown_threshold: float):
        return TCNModel(target_name=target_name, threshold=drawdown_threshold)


# ──────────────────────────────────────────────
#  iTransformer
# ──────────────────────────────────────────────

class iTransformerModel(_DeepTrainerBase):
    """Inverted Transformer: applies attention across variates instead of time.

    Treats each feature as a variable token and applies self-attention across
    features, followed by a simple feed-forward over time.
    """

    def __init__(
        self,
        target_name: str,
        threshold: float,
        *,
        d_model: int = 32,
        n_heads: int = 4,
        n_layers: int = 2,
        dropout: float = 0.1,
    ):
        super().__init__(target_name, threshold)
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.dropout = dropout
        self._model: Optional["_iTransformerNetwork"] = None

    def fit(self, samples: list[TrainingSample]) -> "iTransformerModel":
        import torch
        import torch.nn as nn
        import torch.optim as optim

        if not samples:
            raise ValueError("samples must not be empty")
        self.feature_order = sorted(samples[0].features)
        _compute_feature_stats(self.feature_order, samples, self.feature_stats)
        fit_samples = self._bounded_fit_samples(samples)

        # Each sample is a "time point", features are "variates"
        # We treat this as: n_vars = len(feature_order), seq_len = n_samples
        # In iTransformer, attention is across variates, so we need:
        # (batch, n_vars, seq_len) where n_vars = feature count, seq_len = 1 (single time)
        # Actually for our use case where each sample is a single feature vector,
        # we reshape to (1, n_features, n_samples)
        matrix = torch.tensor(
            [self._vectorize(s) for s in fit_samples],
            dtype=torch.float32,
        ).T.unsqueeze(0)  # (1, n_features, n_samples)

        labels = torch.tensor(
            [self._target_label(s) for s in fit_samples],
            dtype=torch.float32,
        ).unsqueeze(0).unsqueeze(0)  # (1, 1, n_samples)

        n_vars, seq_len = len(self.feature_order), len(fit_samples)
        self._model = _iTransformerNetwork(
            n_vars=n_vars,
            seq_len=seq_len,
            d_model=self.d_model,
            n_heads=self.n_heads,
            n_layers=self.n_layers,
            dropout=self.dropout,
        )

        criterion = nn.BCEWithLogitsLoss()
        optimizer = optim.Adam(self._model.parameters(), lr=0.003, weight_decay=1e-4)
        early_stop_patience = _deep_patience()
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=early_stop_patience, min_lr=1e-5)

        self._model.train()
        best_loss = float("inf")
        best_state = None
        patience = 0
        for epoch in range(_deep_max_epochs()):
            optimizer.zero_grad()
            outputs = self._model(matrix).view(1, -1)  # (1, n_samples)
            loss = criterion(outputs, labels.view(1, -1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self._model.parameters(), 1.0)
            optimizer.step()
            scheduler.step(loss)

            loss_val = loss.item()
            patience = patience + 1 if loss_val >= best_loss else 0
            if loss_val < best_loss:
                best_loss = loss_val
                best_state = {k: v.clone() for k, v in self._model.state_dict().items()}
            if patience >= early_stop_patience:
                break

        if best_state is not None:
            self._model.load_state_dict(best_state)
        self._model.eval()

        with torch.no_grad():
            raw_scores = torch.sigmoid(self._model(matrix).view(-1)).numpy().tolist()
        self.calibrator.fit(raw_scores, [int(l.item()) for l in labels.view(-1)])
        return self

    def predict(self, sample: TrainingSample) -> CalibratedPrediction:
        return self.predict_many([sample])[0]

    def predict_many(self, samples: list[TrainingSample]) -> list[CalibratedPrediction]:
        if not samples:
            return []
        matrix = torch.tensor(
            [self._vectorize(sample) for sample in samples],
            dtype=torch.float32,
        ).T.unsqueeze(0)  # (1, n_features, n_samples)
        with torch.no_grad():
            raw_scores = (
                torch.sigmoid(self._model(matrix).view(-1)).numpy().tolist()
                if self._model
                else [0.5 for _ in samples]
            )
        return self._predictions_from_scores(samples, raw_scores)

    def explain(self, sample: TrainingSample, *, top_k: int = 4) -> PredictionExplanation:
        if self._model is None:
            return self._explain_from_gradient(sample, [0.0] * len(self.feature_order))
        vec = torch.tensor(
            [self._vectorize(sample)], dtype=torch.float32
        ).T.unsqueeze(0).requires_grad_(True)  # (1, n_features, 1)
        self._model.eval()
        output = self._model(vec)
        self._model.zero_grad()
        output.backward()
        grads = vec.grad.flatten().abs().tolist()
        return self._explain_from_gradient(sample, grads, top_k)


class _iTransformerNetwork(nn.Module):
    """Inverted Transformer: attention across variates with scalar projection.

    Projects each variate's scalar value into d_model via a learned linear
    projection, enabling variable-length (single-sample) predictions.
    """

    def __init__(self, n_vars, seq_len, d_model, n_heads, n_layers, dropout):
        super().__init__()
        self.value_proj = nn.Linear(1, d_model, bias=False)
        self.variate_embed = nn.Parameter(torch.randn(1, n_vars, d_model) * 0.02)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=n_heads, dim_feedforward=d_model * 2,
            dropout=dropout, batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.out_proj = nn.Linear(d_model, 1)

    def forward(self, x):
        # x: (batch, n_vars, seq_len)
        b, n_vars, seq_len = x.shape

        # (b, n_vars, seq_len) -> (b*seq_len, n_vars, 1)
        x_flat = x.permute(0, 2, 1).contiguous().view(b * seq_len, n_vars, 1)
        variate_emb = self.value_proj(x_flat)  # (b*seq_len, n_vars, d_model)
        variate_emb = variate_emb + self.variate_embed[:, :n_vars, :]

        encoded = self.encoder(variate_emb)  # (b*seq_len, n_vars, d_model)
        scalars = self.out_proj(encoded)  # (b*seq_len, n_vars, 1)
        out = scalars.view(b, seq_len, n_vars).mean(dim=2)  # (b, seq_len)
        return out


@dataclass(frozen=True)
class iTransformerTrainerSpec:
    name: str = "itransformer"
    algorithm_family: str = "itransformer"
    algorithm_name: str = "itransformer_classifier"

    def build(self, *, target_name: str, drawdown_threshold: float):
        return iTransformerModel(target_name=target_name, threshold=drawdown_threshold)


# ──────────────────────────────────────────────
#  Spec registry
# ──────────────────────────────────────────────

def deep_trainer_specs():
    return [
        PatchTSTTrainerSpec(),
        TCNTrainerSpec(),
        iTransformerTrainerSpec(),
    ]
