"""True multi-day sequence models for the free-data research path.

The old ``deep_trainers`` module remains a compatibility adapter for the
legacy Trainer protocol.  These models consume ``SequenceExample`` windows,
fit all transforms on the supplied training partition, and expose immutable
configuration/provenance for research manifests.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
import json
import random
from typing import Iterable

import torch
from torch import nn
from torch.nn import functional as F

from investment_research.training.sequence_dataset import SequenceExample


TASKS = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")
DIRECTION_CLASSES = ("up", "down", "flat")
SEEDS = (42, 2026, 3407)


@dataclass(frozen=True)
class SequenceModelConfig:
    architecture: str
    task: str
    window_sessions: int
    hidden_size: int = 64
    patch_len: int = 8
    patch_stride: int = 4
    tcn_kernel_size: int = 3
    tcn_blocks: int = 3
    attention_heads: int = 4
    layers: int = 2
    dropout: float = 0.15
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    batch_size: int = 64
    max_epochs: int = 24
    patience: int = 5
    loss_name: str = "weighted_cross_entropy"
    quality_dropout: float = 0.05


def set_deterministic_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def sequence_input_width(example: SequenceExample) -> int:
    # value + missing-mask channels, followed by quality/event provenance,
    # source delay, provider identity, revision identity and cache state.
    return len(example.feature_order) * 2 + 3 + 2 + 4


def _matrix(examples: list[SequenceExample], stats: dict[str, tuple[float, float]], *, quality_dropout: float = 0.0, training: bool = False) -> torch.Tensor:
    rows: list[list[list[float]]] = []
    feature_names = examples[0].feature_order
    for example in examples:
        time_rows = []
        for index, values in enumerate(example.values):
            normalized = []
            for name, value in zip(feature_names, values):
                mean, std = stats.get(name, (0.0, 1.0))
                normalized.append((float(value) - mean) / max(std, 1e-6))
            missing = [1.0 if value else 0.0 for value in example.missing_mask[index]]
            quality = list(example.data_quality_mask[index])
            event = list(example.event_missing_mask[index])
            delay = [min(float(example.source_delay_seconds[index]) / 86_400.0, 30.0)]
            provider = [(example.provider_ids[index] % 10_000) / 10_000.0]
            revision = [_stable_revision_value(example.revision_ids[index])]
            cache = [{"fresh": 0.0, "stale_usable": 0.33, "expired": 0.66, "unavailable": 1.0}.get(example.cache_states[index], 0.5)]
            if training and quality_dropout and random.random() < quality_dropout:
                event = [1.0, 0.0]
                quality[1] = 0.0
            time_rows.append([*normalized, *missing, *quality, *event, *delay, *provider, *revision, *cache])
        rows.append(time_rows)
    return torch.tensor(rows, dtype=torch.float32)


def fit_sequence_stats(examples: list[SequenceExample]) -> dict[str, tuple[float, float]]:
    if not examples:
        raise ValueError("sequence training requires examples")
    names = examples[0].feature_order
    stats: dict[str, tuple[float, float]] = {}
    for index, name in enumerate(names):
        values = [float(row.values[position][index]) for row in examples for position in range(len(row.values))]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
        stats[name] = (mean, max(variance ** 0.5, 1e-6))
    return stats


def _stable_revision_value(revision: str | None) -> float:
    """Encode revision provenance without treating revision numbers as ordered."""
    if not revision:
        return 0.0
    return int.from_bytes(sha256(revision.encode()).digest()[:4], "big") / 2**32


def task_target(example: SequenceExample, task: str) -> float | int:
    value = example.target
    if task.startswith("direction_"):
        if value not in DIRECTION_CLASSES:
            raise ValueError(f"invalid direction label:{value}")
        return DIRECTION_CLASSES.index(str(value))
    if task == "drawdown_20d":
        return int(float(value) <= -0.08)
    return float(value)


class _PatchTST(nn.Module):
    def __init__(self, width: int, config: SequenceModelConfig, output_dim: int):
        super().__init__()
        self.patch_len = min(config.patch_len, config.window_sessions)
        self.stride = min(config.patch_stride, self.patch_len)
        self.projection = nn.Linear(width * self.patch_len, config.hidden_size)
        n_patches = max(1, (config.window_sessions - self.patch_len) // self.stride + 1)
        self.position = nn.Parameter(torch.zeros(1, n_patches, config.hidden_size))
        layer = nn.TransformerEncoderLayer(config.hidden_size, config.attention_heads, config.hidden_size * 2, config.dropout, batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, config.layers)
        self.head = nn.Sequential(nn.LayerNorm(config.hidden_size), nn.Linear(config.hidden_size, output_dim))

    def forward(self, values):
        patches = values.unfold(1, self.patch_len, self.stride)
        patches = patches.contiguous().view(values.shape[0], patches.shape[1], -1)
        encoded = self.encoder(self.projection(patches) + self.position[:, :patches.shape[1]])
        return self.head(encoded[:, -1])


class _CausalConv1d(nn.Module):
    def __init__(self, channels_in: int, channels_out: int, kernel_size: int, dilation: int):
        super().__init__()
        self.left_padding = (kernel_size - 1) * dilation
        self.conv = nn.Conv1d(channels_in, channels_out, kernel_size, padding=0, dilation=dilation)

    def forward(self, values):
        return self.conv(F.pad(values, (self.left_padding, 0)))


class _TCN(nn.Module):
    def __init__(self, width: int, config: SequenceModelConfig, output_dim: int):
        super().__init__()
        blocks = []
        channels = width
        for index in range(config.tcn_blocks):
            dilation = 2 ** index
            blocks.extend([
                _CausalConv1d(channels, config.hidden_size, config.tcn_kernel_size, dilation),
                nn.BatchNorm1d(config.hidden_size), nn.GELU(), nn.Dropout(config.dropout),
            ])
            channels = config.hidden_size
        self.blocks = nn.Sequential(*blocks)
        self.head = nn.Sequential(nn.LayerNorm(config.hidden_size), nn.Linear(config.hidden_size, output_dim))

    def forward(self, values):
        out = self.blocks(values.transpose(1, 2))[:, :, : values.shape[1]]
        return self.head(out[:, :, -1])


class _iTransformer(nn.Module):
    def __init__(self, width: int, config: SequenceModelConfig, output_dim: int):
        super().__init__()
        self.value_projection = nn.Linear(config.window_sessions, config.hidden_size)
        self.variable_embedding = nn.Parameter(torch.zeros(1, width, config.hidden_size))
        layer = nn.TransformerEncoderLayer(config.hidden_size, config.attention_heads, config.hidden_size * 2, config.dropout, batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, config.layers)
        self.head = nn.Sequential(nn.LayerNorm(config.hidden_size), nn.Linear(config.hidden_size, output_dim))

    def forward(self, values):
        tokens = self.value_projection(values.transpose(1, 2)) + self.variable_embedding[:, : values.shape[2]]
        return self.head(self.encoder(tokens).mean(dim=1))


class _DeepMLP(nn.Module):
    def __init__(self, width: int, config: SequenceModelConfig, output_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(), nn.Linear(width * config.window_sessions, config.hidden_size), nn.GELU(),
            nn.Dropout(config.dropout), nn.Linear(config.hidden_size, config.hidden_size), nn.GELU(),
            nn.Linear(config.hidden_size, output_dim),
        )

    def forward(self, values):
        return self.net(values)


def build_sequence_network(config: SequenceModelConfig, width: int, output_dim: int) -> nn.Module:
    factories = {"patchtst": _PatchTST, "tcn": _TCN, "itransformer": _iTransformer, "deep_mlp": _DeepMLP}
    if config.architecture not in factories:
        raise ValueError(f"unknown sequence architecture:{config.architecture}")
    return factories[config.architecture](width, config, output_dim)


class SequenceTaskRunner:
    """Train one architecture for exactly one task and one time split."""

    def __init__(self, config: SequenceModelConfig, *, seed: int = 42):
        if config.task not in TASKS:
            raise ValueError(f"unsupported sequence task:{config.task}")
        set_deterministic_seed(seed)
        self.config = config
        self.seed = seed
        self.stats: dict[str, tuple[float, float]] = {}
        self.feature_order: list[str] = []
        self.model: nn.Module | None = None
        self.training_curve: list[dict[str, float]] = []

    @property
    def output_dim(self) -> int:
        return 3 if self.config.task.startswith("direction_") or self.config.task == "return_20d" else 1

    def fit(self, train: list[SequenceExample], validation: list[SequenceExample] | None = None) -> "SequenceTaskRunner":
        if not train:
            raise ValueError("sequence training requires non-empty train rows")
        self.feature_order = list(train[0].feature_order)
        self.stats = fit_sequence_stats(train)
        width = sequence_input_width(train[0])
        self.model = build_sequence_network(self.config, width, self.output_dim)
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.config.learning_rate, weight_decay=self.config.weight_decay)
        train_x = _matrix(train, self.stats, quality_dropout=self.config.quality_dropout, training=True)
        train_y = torch.tensor([task_target(item, self.config.task) for item in train])
        val_x = _matrix(validation, self.stats) if validation else None
        val_y = torch.tensor([task_target(item, self.config.task) for item in validation]) if validation else None
        best_state = None
        best_loss = float("inf")
        stale = 0
        for epoch in range(self.config.max_epochs):
            self.model.train()
            optimizer.zero_grad()
            loss = self._loss(self.model(train_x), train_y)
            loss.backward()
            nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            optimizer.step()
            self.model.eval()
            with torch.no_grad():
                validation_loss = float(self._loss(self.model(val_x), val_y).item()) if val_x is not None else float(loss.item())
            self.training_curve.append({"epoch": float(epoch), "train_loss": float(loss.item()), "validation_loss": validation_loss})
            if validation_loss < best_loss:
                best_loss = validation_loss
                best_state = {key: value.detach().clone() for key, value in self.model.state_dict().items()}
                stale = 0
            else:
                stale += 1
            if stale >= self.config.patience:
                break
        if best_state is not None:
            self.model.load_state_dict(best_state)
        self.model.eval()
        return self

    def _loss(self, output, target):
        if self.config.task.startswith("direction_"):
            weights = torch.bincount(target.long(), minlength=3).float().clamp_min(1.0)
            weights = weights.sum() / (3 * weights)
            if self.config.loss_name == "focal_cross_entropy":
                ce = nn.functional.cross_entropy(output, target.long(), weight=weights, reduction="none")
                return ((1 - torch.exp(-ce)) ** 2 * ce).mean()
            return nn.functional.cross_entropy(output, target.long(), weight=weights, label_smoothing=0.02 if self.config.loss_name == "label_smoothed_cross_entropy" else 0.0)
        if self.config.task == "return_20d":
            taus = torch.tensor([0.1, 0.5, 0.9])
            error = target.float().unsqueeze(1) - output
            return torch.maximum(taus * error, (taus - 1) * error).mean()
        logits = output.view(-1)
        bce = nn.functional.binary_cross_entropy_with_logits(logits, target.float())
        order = torch.combinations(logits, r=2)
        return bce if order.numel() == 0 else bce + 0.05 * torch.relu(1.0 - order[:, 0] + order[:, 1]).mean()

    def predict_raw(self, examples: list[SequenceExample]) -> list[list[float]]:
        if self.model is None:
            raise RuntimeError("sequence model is not fitted")
        if not examples:
            return []
        with torch.no_grad():
            output = self.model(_matrix(examples, self.stats))
            if self.config.task.startswith("direction_"):
                return torch.softmax(output, dim=1).tolist()
            if self.config.task == "return_20d":
                return output.tolist()
            return torch.sigmoid(output).tolist()

    def artifact_hash(self) -> str:
        if self.model is None:
            raise RuntimeError("sequence model is not fitted")
        buffer = BytesIO()
        torch.save({"state_dict": self.model.state_dict(), "config": asdict(self.config), "stats": self.stats, "feature_order": self.feature_order, "seed": self.seed}, buffer)
        return sha256(buffer.getvalue()).hexdigest()

    def save(self, path) -> str:
        if self.model is None:
            raise RuntimeError("sequence model is not fitted")
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state_dict": self.model.state_dict(), "config": asdict(self.config), "stats": self.stats, "feature_order": self.feature_order, "seed": self.seed, "training_curve": self.training_curve}, path)
        return sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path):
        payload = torch.load(path, map_location="cpu", weights_only=False)
        config = SequenceModelConfig(**payload["config"])
        runner = cls(config, seed=int(payload.get("seed", 42)))
        runner.stats = {str(key): (float(value[0]), float(value[1])) for key, value in payload["stats"].items()}
        runner.feature_order = list(payload["feature_order"])
        # Eight provenance channels plus one cache-state channel are appended
        # to the value and missing-mask channels by ``_matrix``.
        runner.model = build_sequence_network(config, len(runner.feature_order) * 2 + 9, runner.output_dim)
        runner.model.load_state_dict(payload["state_dict"])
        runner.model.eval()
        runner.training_curve = list(payload.get("training_curve", []))
        return runner
