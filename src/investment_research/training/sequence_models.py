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
from math import isfinite
import os
import random
from typing import Iterable

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

if torch.cuda.is_available():
    # RTX-class devices benefit from the high-precision matmul selection used
    # by the dense projections in the sequence challengers.
    torch.set_float32_matmul_precision("high")

from investment_research.training.sequence_dataset import (
    SequenceExample,
    SequenceShapeError,
    validate_sequence_examples,
)


TASKS = (
    "direction_1d", "direction_5d", "return_20d", "drawdown_20d",
    "excess_return_5d", "excess_return_20d",
    "excess_return_120d", "excess_return_240d",
    "future_max_drawdown_120d", "future_max_drawdown_240d",
)
QUANTILE_TASKS = frozenset({
    "return_20d", "excess_return_5d", "excess_return_20d",
    "excess_return_120d", "excess_return_240d",
    "future_max_drawdown_120d", "future_max_drawdown_240d",
})
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
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _select_compute_device() -> torch.device:
    """Select CUDA when usable, while respecting shared-GPU limits.

    The research server shares one Tesla P40 with other projects.  A per-
    process allocator cap prevents a challenger from consuming the entire
    device; the limit is configurable without changing the model artifact.
    """
    requested = os.getenv("INVESTMENT_RESEARCH_TORCH_DEVICE", "auto").lower()
    if requested == "cpu":
        return torch.device("cpu")
    if requested not in {"auto", "cuda"} or not torch.cuda.is_available():
        return torch.device("cpu")
    try:
        fraction = float(os.getenv("INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION", "0.20"))
        if 0.05 <= fraction <= 0.90:
            torch.cuda.set_per_process_memory_fraction(fraction, device=0)
    except (TypeError, ValueError, RuntimeError):
        # A driver may expose CUDA but reject allocator limits.  Training can
        # still proceed with the normal CUDA allocator and the caller's
        # process-level resource controls.
        pass
    return torch.device("cuda")


def sequence_input_width(example: SequenceExample) -> int:
    # value + missing-mask channels, followed by quality/event provenance,
    # source delay, provider identity, revision identity and cache state.
    return len(example.feature_order) * 2 + 3 + 2 + 4


def _matrix(
    examples: list[SequenceExample],
    stats: dict[str, tuple[float, float]],
    *,
    quality_dropout: float = 0.0,
    training: bool = False,
    device: torch.device | None = None,
    validate: bool = True,
) -> torch.Tensor:
    if not examples:
        raise ValueError("sequence matrix requires non-empty examples")
    if validate:
        invalid = validate_sequence_examples(examples)
        if invalid:
            raise SequenceShapeError(
                f"sequence_shape_mismatch: {len(invalid)}/{len(examples)} examples invalid; first={invalid[0]}"
            )
    feature_names = examples[0].feature_order
    feature_count = len(feature_names)
    values = np.asarray([example.values for example in examples], dtype=np.float32)
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    means = np.asarray([stats.get(name, (0.0, 1.0))[0] for name in feature_names], dtype=np.float32)
    scales = np.asarray([max(stats.get(name, (0.0, 1.0))[1], 1e-6) for name in feature_names], dtype=np.float32)
    normalized = np.clip((values - means[None, None, :]) / scales[None, None, :], -20.0, 20.0)
    normalized = np.nan_to_num(normalized, nan=0.0, posinf=0.0, neginf=0.0)

    missing = np.asarray([example.missing_mask for example in examples], dtype=np.float32)
    quality = np.asarray([example.data_quality_mask for example in examples], dtype=np.float32)
    event = np.asarray([example.event_missing_mask for example in examples], dtype=np.float32)
    delays = np.asarray([example.source_delay_seconds for example in examples], dtype=np.float32)
    delays = np.nan_to_num(delays, nan=0.0, posinf=0.0, neginf=0.0)
    delays = np.clip(delays / 86_400.0, 0.0, 30.0)[..., None]
    providers = (np.asarray([example.provider_ids for example in examples], dtype=np.float32) % 10_000.0 / 10_000.0)[..., None]
    revisions = np.asarray(
        [[_stable_revision_value(value) for value in example.revision_ids] for example in examples],
        dtype=np.float32,
    )[..., None]
    cache_codes = {"fresh": 0.0, "stale_usable": 0.33, "expired": 0.66, "unavailable": 1.0}
    cache = np.asarray(
        [[cache_codes.get(value, 0.5) for value in example.cache_states] for example in examples],
        dtype=np.float32,
    )[..., None]

    if training and quality_dropout:
        dropped = np.random.random(quality.shape[:2]) < quality_dropout
        quality[dropped, 1] = 0.0
        event[dropped, 0] = 1.0
        event[dropped, 1] = 0.0

    rows = np.concatenate((normalized, missing, quality, event, delays, providers, revisions, cache), axis=2)
    if rows.shape[2] != feature_count * 2 + 9:
        raise SequenceShapeError(f"sequence matrix width mismatch: {rows.shape[2]} != {feature_count * 2 + 9}")
    tensor = torch.from_numpy(np.ascontiguousarray(rows))
    if device is not None:
        tensor = tensor.to(device, non_blocking=device.type == "cuda")
    return tensor


def fit_sequence_stats(examples: list[SequenceExample]) -> dict[str, tuple[float, float]]:
    if not examples:
        raise ValueError("sequence training requires examples")
    invalid = validate_sequence_examples(examples)
    if invalid:
        raise SequenceShapeError(
            f"sequence_shape_mismatch: {len(invalid)}/{len(examples)} examples invalid; first={invalid[0]}"
        )
    names = examples[0].feature_order
    expected_width = len(names)
    values = np.asarray([example.values for example in examples], dtype=np.float64)
    if values.ndim != 3 or values.shape[2] != expected_width:
        raise SequenceShapeError(
            f"sequence_shape_mismatch: expected_feature_count={expected_width} actual_shape={values.shape}"
        )
    finite = np.isfinite(values)
    safe_values = np.where(finite, values, 0.0)
    counts = finite.sum(axis=(0, 1))
    sums = safe_values.sum(axis=(0, 1))
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    centered = np.where(finite, values - means[None, None, :], 0.0)
    variances = np.divide(
        (centered * centered).sum(axis=(0, 1)), counts,
        out=np.ones_like(means), where=counts > 0,
    )
    scales = np.maximum(np.sqrt(variances), 1e-6)
    return {name: (float(mean), float(scale)) for name, mean, scale in zip(names, means, scales)}


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
        self.encoder = nn.TransformerEncoder(layer, config.layers, enable_nested_tensor=False)
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
        self.encoder = nn.TransformerEncoder(layer, config.layers, enable_nested_tensor=False)
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
        # Keep one explicit compute device for the complete sequence path.  A
        # CUDA build that cannot initialize (for example an older driver) is
        # treated as CPU rather than failing the research run.
        self.device = _select_compute_device()

    @property
    def output_dim(self) -> int:
        return 3 if self.config.task.startswith("direction_") or self.config.task in QUANTILE_TASKS else 1

    def fit(self, train: list[SequenceExample], validation: list[SequenceExample] | None = None) -> "SequenceTaskRunner":
        if not train:
            raise ValueError("sequence training requires non-empty train rows")
        self.feature_order = list(train[0].feature_order)
        invalid = validate_sequence_examples(
            train, window_sessions=self.config.window_sessions, feature_order=self.feature_order,
        )
        if invalid:
            raise SequenceShapeError(
                "sequence_shape_mismatch: %d/%d training examples invalid; first=%s"
                % (len(invalid), len(train), invalid[0])
            )
        self.stats = fit_sequence_stats(train)
        width = sequence_input_width(train[0])
        self.model = build_sequence_network(self.config, width, self.output_dim).to(self.device)
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.config.learning_rate, weight_decay=self.config.weight_decay)
        # Materialize each split once.  The previous implementation rebuilt
        # and revalidated every nested Python list for every batch, fold, seed,
        # and epoch, leaving CUDA idle while the CPU serialized features.
        train_matrix = _matrix(train, self.stats, validate=False)
        validation_matrix = _matrix(validation, self.stats, validate=False) if validation else None
        train_targets = torch.tensor([task_target(item, self.config.task) for item in train])
        validation_targets = (
            torch.tensor([task_target(item, self.config.task) for item in validation])
            if validation else None
        )
        # A fold for the 162-stock long-horizon pool is normally only a few
        # GiB.  Keeping it on GPU0 removes thousands of tiny host-to-device
        # copies, which otherwise leave a 4090 mostly idle between batches.
        # The conservative cap leaves ample room for activations and the
        # optimizer; oversized folds retain the streaming fallback below.
        if self.device.type == "cuda":
            combined_bytes = train_matrix.numel() * train_matrix.element_size()
            if validation_matrix is not None:
                combined_bytes += validation_matrix.numel() * validation_matrix.element_size()
            total_memory = torch.cuda.get_device_properties(self.device).total_memory
            if combined_bytes <= int(total_memory * 0.45):
                train_matrix = train_matrix.to(self.device, non_blocking=True)
                train_targets = train_targets.to(self.device, non_blocking=True)
                if validation_matrix is not None and validation_targets is not None:
                    validation_matrix = validation_matrix.to(self.device, non_blocking=True)
                    validation_targets = validation_targets.to(self.device, non_blocking=True)
        best_state = None
        best_loss = float("inf")
        stale = 0
        for epoch in range(self.config.max_epochs):
            self.model.train()
            epoch_loss = 0.0
            batch_count = 0
            generator = torch.Generator().manual_seed(self.seed + epoch)
            order = torch.randperm(len(train), generator=generator)
            if train_matrix.device.type == "cuda":
                order = order.to(train_matrix.device, non_blocking=True)
            for offset in range(0, len(order), self.config.batch_size):
                indexes = order[offset: offset + self.config.batch_size]
                train_x = train_matrix.index_select(0, indexes).to(
                    self.device, non_blocking=self.device.type == "cuda"
                )
                if self.config.quality_dropout:
                    dropped = torch.rand(train_x.shape[:2], device=self.device) < self.config.quality_dropout
                    quality_start = len(self.feature_order) * 2
                    quality_coverage = train_x[:, :, quality_start + 1]
                    event_missing = train_x[:, :, quality_start + 3]
                    event_source = train_x[:, :, quality_start + 4]
                    quality_coverage[dropped] = 0.0
                    event_missing[dropped] = 1.0
                    event_source[dropped] = 0.0
                train_y = train_targets.index_select(0, indexes).to(
                    self.device, non_blocking=self.device.type == "cuda"
                )
                optimizer.zero_grad()
                loss = self._loss(self.model(train_x), train_y)
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += float(loss.item())
                batch_count += 1
            self.model.eval()
            with torch.no_grad():
                validation_loss = (
                    self._evaluation_loss(validation, validation_matrix, validation_targets)
                    if validation else epoch_loss / max(1, batch_count)
                )
            train_loss = epoch_loss / max(1, batch_count)
            self.training_curve.append({"epoch": float(epoch), "train_loss": train_loss, "validation_loss": validation_loss})
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

    def _evaluation_loss(
        self,
        examples: list[SequenceExample],
        matrix: torch.Tensor | None = None,
        targets: torch.Tensor | None = None,
    ) -> float:
        matrix = matrix if matrix is not None else _matrix(examples, self.stats)
        targets = targets if targets is not None else torch.tensor(
            [task_target(item, self.config.task) for item in examples]
        )
        losses: list[float] = []
        for offset in range(0, len(examples), self.config.batch_size):
            values = matrix[offset: offset + self.config.batch_size].to(
                self.device, non_blocking=self.device.type == "cuda"
            )
            batch_targets = targets[offset: offset + self.config.batch_size].to(
                self.device, non_blocking=self.device.type == "cuda"
            )
            losses.append(float(self._loss(self.model(values), batch_targets).item()))
        return sum(losses) / max(1, len(losses))

    def _loss(self, output, target):
        if self.config.task.startswith("direction_"):
            weights = torch.bincount(target.long(), minlength=3).float().clamp_min(1.0)
            weights = weights.sum() / (3 * weights)
            if self.config.loss_name == "focal_cross_entropy":
                ce = nn.functional.cross_entropy(output, target.long(), weight=weights, reduction="none")
                return ((1 - torch.exp(-ce)) ** 2 * ce).mean()
            return nn.functional.cross_entropy(output, target.long(), weight=weights, label_smoothing=0.02 if self.config.loss_name == "label_smoothed_cross_entropy" else 0.0)
        if self.config.task in QUANTILE_TASKS:
            taus = torch.tensor([0.1, 0.5, 0.9], device=output.device)
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
        matrix = _matrix(examples, self.stats, validate=True)
        results: list[list[float]] = []
        with torch.no_grad():
            for offset in range(0, len(examples), self.config.batch_size):
                values = matrix[offset: offset + self.config.batch_size].to(
                    self.device, non_blocking=self.device.type == "cuda"
                )
                output = self.model(values)
                if self.config.task.startswith("direction_"):
                    results.extend(torch.softmax(output, dim=1).detach().cpu().tolist())
                elif self.config.task in QUANTILE_TASKS:
                    results.extend(output.detach().cpu().tolist())
                else:
                    results.extend(torch.sigmoid(output).detach().cpu().tolist())
        return results

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
        runner.model = build_sequence_network(
            config, len(runner.feature_order) * 2 + 9, runner.output_dim
        ).to(runner.device)
        runner.model.load_state_dict(payload["state_dict"])
        runner.model.eval()
        runner.training_curve = list(payload.get("training_curve", []))
        return runner
