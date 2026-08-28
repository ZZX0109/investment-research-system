"""LSTM residual-volatility model used with causal GARCH features.

GARCH describes conditional variance with a compact parametric recurrence.
This module learns the remaining volatility clustering in standardised GARCH
residuals.  It is deliberately trained inside each chronological fold by the
enhanced runner, so validation rows never influence its fitted weights.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import pickle
from typing import Any, Mapping

import numpy as np


LSTM_GARCH_FEATURE = "lstm_garch_residual_vol"


@dataclass
class LSTMGarchResidualModel:
    sequence_length: int = 20
    hidden_size: int = 24
    epochs: int = 8
    batch_size: int = 512
    seed: int = 42
    _model: object | None = None
    _mean: np.ndarray | None = None
    _std: np.ndarray | None = None

    def fit(self, rows: list[Mapping[str, Any]]) -> "LSTMGarchResidualModel":
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset

        torch.manual_seed(self.seed)
        examples, targets = _sequence_examples(rows, self.sequence_length, with_target=True)
        if len(examples) < 32:
            self._model = None
            return self
        data = np.asarray(examples, dtype=np.float32)
        labels = np.asarray(targets, dtype=np.float32)
        self._mean = data.reshape(-1, data.shape[-1]).mean(axis=0)
        self._std = np.maximum(data.reshape(-1, data.shape[-1]).std(axis=0), 1e-6)
        data = (data - self._mean) / self._std
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _ResidualLSTM(input_size=data.shape[-1], hidden_size=self.hidden_size).to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        loader = DataLoader(TensorDataset(torch.from_numpy(data), torch.from_numpy(labels)), batch_size=self.batch_size, shuffle=True)
        model.train()
        for _ in range(self.epochs):
            for sequence, target in loader:
                sequence, target = sequence.to(device), target.to(device)
                optimizer.zero_grad()
                loss = nn.functional.smooth_l1_loss(model(sequence), target)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
        self._model = model.cpu().eval()
        return self

    def predict(self, rows: list[Mapping[str, Any]]) -> dict[tuple[str, str], float]:
        if self._model is None or self._mean is None or self._std is None:
            return {}
        import torch

        examples, _, keys = _sequence_examples(rows, self.sequence_length, with_target=False, include_keys=True)
        if not examples:
            return {}
        values = (np.asarray(examples, dtype=np.float32) - self._mean) / self._std
        with torch.no_grad():
            output = self._model(torch.from_numpy(values)).numpy()
        return {key: float(value) for key, value in zip(keys, output)}

    def save(self, path: Path) -> None:
        if self._model is None or self._mean is None or self._std is None:
            return
        import torch

        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "sequence_length": self.sequence_length, "hidden_size": self.hidden_size,
            # Lists keep the checkpoint compatible with PyTorch's
            # ``weights_only=True`` safe loader.
            "epochs": self.epochs, "mean": self._mean.tolist(), "std": self._std.tolist(),
            "state_dict": self._model.state_dict(),
        }, path)

    @classmethod
    def load(cls, path: Path) -> "LSTMGarchResidualModel | None":
        try:
            import torch
            try:
                payload = torch.load(path, map_location="cpu", weights_only=True)
            except pickle.UnpicklingError:
                # Migration path for our own pre-v1 checkpoint, which stored
                # NumPy arrays.  It is immediately rewritten in the safe
                # format by the caller after successful loading.
                payload = torch.load(path, map_location="cpu", weights_only=False)
            instance = cls(sequence_length=int(payload["sequence_length"]), hidden_size=int(payload["hidden_size"]), epochs=int(payload.get("epochs", 8)))
            model = _ResidualLSTM(input_size=3, hidden_size=instance.hidden_size)
            model.load_state_dict(payload["state_dict"])
            instance._model = model.eval()
            instance._mean = np.asarray(payload["mean"], dtype=np.float32)
            instance._std = np.asarray(payload["std"], dtype=np.float32)
            return instance
        except (OSError, KeyError, RuntimeError, ValueError, pickle.UnpicklingError):
            return None


def _sequence_examples(rows: list[Mapping[str, Any]], sequence_length: int, *, with_target: bool, include_keys: bool = False):
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("symbol", ""))].append(row)
    examples: list[list[list[float]]] = []
    targets: list[float] = []
    keys: list[tuple[str, str]] = []
    for symbol, items in grouped.items():
        items.sort(key=lambda item: str(item.get("decision_date", "")))
        vectors = [_vector(item) for item in items]
        for index in range(sequence_length - 1, len(items)):
            if with_target:
                if index + 1 >= len(items):
                    continue
                target = _target(items[index + 1])
                if not np.isfinite(target):
                    continue
            window = vectors[index - sequence_length + 1:index + 1]
            if not np.all(np.isfinite(window)):
                continue
            examples.append(window)
            if with_target:
                targets.append(float(target))
            keys.append((symbol, str(items[index].get("decision_date"))))
    if include_keys:
        return examples, targets, keys
    return examples, targets


def _vector(row: Mapping[str, Any]) -> list[float]:
    garch = _number(row.get("garch_conditional_vol"))
    ret = _number(row.get("ret_1d"))
    residual = ret / garch if np.isfinite(ret) and np.isfinite(garch) and garch > 1e-10 else np.nan
    return [residual, _number(row.get("garch_vol_ratio_20")), _number(row.get("volatility_30d"))]


def _target(row: Mapping[str, Any]) -> float:
    garch = _number(row.get("garch_conditional_vol"))
    ret = _number(row.get("ret_1d"))
    return abs(ret / garch) if np.isfinite(ret) and np.isfinite(garch) and garch > 1e-10 else np.nan


def _number(value: object) -> float:
    try:
        value = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return np.nan
    return value if np.isfinite(value) else np.nan


def _ResidualLSTM(*, input_size: int, hidden_size: int):
    import torch
    from torch import nn

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(input_size=input_size, hidden_size=hidden_size, batch_first=True)
            self.head = nn.Sequential(nn.Linear(hidden_size, hidden_size // 2), nn.GELU(), nn.Linear(hidden_size // 2, 1), nn.Softplus())

        def forward(self, sequence):
            values, _ = self.lstm(sequence)
            return self.head(values[:, -1, :]).squeeze(-1)

    return Model()
