"""Direct 20-session price-path model.

Unlike the legacy temporal runners, this model predicts the full next twenty
daily returns in one pass.  It therefore never feeds a predicted day back into
the next input window, which is the source of the unnaturally flat recursive
paths in the previous implementation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("direct_multihorizon_price_path")

_ARTIFACT_DIR = "artifacts/price_path/direct_multihorizon"
_WEIGHT_FILE = "model.pt"
_FEATURE_FILE = "feature_contract.json"
_EVALUATION_FILE = "evaluation.json"
_MANIFEST_FILE = "manifest.json"
_WINDOW = 60
_HORIZON = 20
_QUANTILES = (0.1, 0.5, 0.9)
_FEATURE_NAMES = (
    "daily_return",
    "intraday_range",
    "volume_change",
    "amount_change",
    "turnover_rate",
    "ma5_gap",
    "ma20_gap",
    "volatility_20d",
    "market_return",
    "market_volatility",
)
_BRANCH_CONFIG = {"legacy": True, "ptft": False, "vssm": False, "diffusion": False, "graph": False}


@dataclass(frozen=True)
class _Sample:
    anchor_date: date
    sequence: np.ndarray
    target: np.ndarray


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return default
    return candidate if np.isfinite(candidate) else default


def _future_trading_dates(anchor: date, horizon: int) -> list[date]:
    """Return future weekday sessions when no exchange calendar is available.

    The stored market calendar only contains completed sessions, so it cannot
    authoritatively enumerate future holidays.  Weekends are never emitted;
    callers retain the anchor date as the first point.
    """
    result: list[date] = []
    candidate = anchor
    while len(result) < horizon:
        candidate += timedelta(days=1)
        if candidate.weekday() < 5:
            result.append(candidate)
    return result


class DirectMultiHorizonPricePathRunner:
    """Train and serve a direct 20-day q10/q50/q90 price-path model."""

    def __init__(self, project_root: Path | str, *, vendored_root: Path | str | None = None) -> None:
        self.project_root = Path(project_root)
        self.vendored_root = Path(vendored_root) if vendored_root is not None else self.project_root

    def _artifact_dir(self) -> Path:
        return self.project_root / _ARTIFACT_DIR

    def _artifact(self, name: str) -> Path:
        return self._artifact_dir() / name

    def is_available(self) -> bool:
        return all(self._artifact(name).exists() for name in (_WEIGHT_FILE, _FEATURE_FILE, _EVALUATION_FILE, _MANIFEST_FILE))

    def _model_class(self):
        source = self.vendored_root / "vendor" / "kittencn" / "src"
        if not (source / "stock_prediction" / "models" / "temporal_hybrid.py").exists():
            raise FileNotFoundError("vendored TemporalHybridNet source is absent")
        source_text = str(source)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        from stock_prediction.models.temporal_hybrid import TemporalHybridNet

        return TemporalHybridNet

    @staticmethod
    def _bars_by_symbol(repo: Any, symbols: list[str]) -> dict[str, list[Any]]:
        result: dict[str, list[Any]] = {}
        for symbol in symbols:
            bars = sorted(repo.active_bars(symbol, "1d"), key=lambda item: item.bar_start)
            if bars:
                result[symbol] = bars
        return result

    @staticmethod
    def _market_features(bars_by_symbol: dict[str, list[Any]]) -> dict[str, tuple[float, float]]:
        returns_by_date: dict[str, list[float]] = {}
        for bars in bars_by_symbol.values():
            for index in range(1, len(bars)):
                previous = _finite(bars[index - 1].close)
                close = _finite(bars[index].close)
                if previous <= 0 or close <= 0:
                    continue
                returns_by_date.setdefault(bars[index].trade_date.isoformat(), []).append(close / previous - 1.0)
        return {
            day: (float(np.mean(values)), float(np.std(values)))
            for day, values in returns_by_date.items()
            if values
        }

    @staticmethod
    def _feature_matrix(bars: list[Any], market_features: dict[str, tuple[float, float]]) -> np.ndarray:
        closes = np.asarray([_finite(item.close) for item in bars], dtype=np.float64)
        # Frozen dashboard series intentionally carries close only.  Serving
        # must still work from that immutable view, with unavailable turnover
        # fields represented as zero rather than reaching into live data.
        volumes = np.asarray([max(0.0, _finite(getattr(item, "volume", None))) for item in bars], dtype=np.float64)
        amounts = np.asarray([max(0.0, _finite(getattr(item, "amount", None))) for item in bars], dtype=np.float64)
        features = np.zeros((len(bars), len(_FEATURE_NAMES)), dtype=np.float32)
        returns = np.zeros(len(bars), dtype=np.float64)
        for index in range(1, len(bars)):
            if closes[index - 1] > 0:
                returns[index] = closes[index] / closes[index - 1] - 1.0
        for index, bar in enumerate(bars):
            close = max(closes[index], 1e-8)
            previous_volume = max(volumes[index - 1], 1.0) if index else max(volumes[index], 1.0)
            previous_amount = max(amounts[index - 1], 1.0) if index else max(amounts[index], 1.0)
            low = _finite(getattr(bar, "low", None), close)
            high = _finite(getattr(bar, "high", None), close)
            ma5 = float(np.mean(closes[max(0, index - 4) : index + 1]))
            ma20 = float(np.mean(closes[max(0, index - 19) : index + 1]))
            volatility = float(np.std(returns[max(0, index - 19) : index + 1]))
            market_return, market_volatility = market_features.get(bar.trade_date.isoformat(), (0.0, 0.0))
            features[index] = np.asarray(
                (
                    returns[index],
                    max(0.0, high - low) / close,
                    float(np.log1p(volumes[index]) - np.log1p(previous_volume)),
                    float(np.log1p(amounts[index]) - np.log1p(previous_amount)),
                    _finite(getattr(bar, "turnover_rate", None)),
                    ma5 / close - 1.0,
                    ma20 / close - 1.0,
                    volatility,
                    market_return,
                    market_volatility,
                ),
                dtype=np.float32,
            )
        return np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)

    def build_dataset(self, repo: Any, symbols: list[str]) -> tuple[list[_Sample], dict[str, tuple[float, float]], dict[str, list[Any]]]:
        """Build direct, leak-free (60 historical sessions -> 20 future sessions) samples."""
        bars_by_symbol = self._bars_by_symbol(repo, symbols)
        market_features = self._market_features(bars_by_symbol)
        samples: list[_Sample] = []
        for bars in bars_by_symbol.values():
            if len(bars) < _WINDOW + _HORIZON + 1:
                continue
            matrix = self._feature_matrix(bars, market_features)
            closes = np.asarray([_finite(item.close) for item in bars], dtype=np.float64)
            for anchor in range(_WINDOW - 1, len(bars) - _HORIZON):
                if closes[anchor] <= 0:
                    continue
                target = []
                valid = True
                for offset in range(1, _HORIZON + 1):
                    before, after = closes[anchor + offset - 1], closes[anchor + offset]
                    if before <= 0 or after <= 0:
                        valid = False
                        break
                    target.append(after / before - 1.0)
                if valid:
                    samples.append(_Sample(bars[anchor].trade_date, matrix[anchor - _WINDOW + 1 : anchor + 1], np.asarray(target, dtype=np.float32)))
        return samples, market_features, bars_by_symbol

    @staticmethod
    def _split_by_time(samples: list[_Sample]) -> tuple[list[_Sample], list[_Sample], list[_Sample]]:
        dates = sorted({item.anchor_date for item in samples})
        if len(dates) < 6:
            return [], [], []
        train_end = dates[max(0, int(len(dates) * 0.70) - 1)]
        validation_end = dates[max(0, int(len(dates) * 0.85) - 1)]
        train = [item for item in samples if item.anchor_date <= train_end]
        validation = [item for item in samples if train_end < item.anchor_date <= validation_end]
        test = [item for item in samples if item.anchor_date > validation_end]
        return train, validation, test

    @staticmethod
    def _normalizer(rows: list[_Sample]) -> tuple[np.ndarray, np.ndarray]:
        values = np.concatenate([item.sequence for item in rows], axis=0)
        mean = values.mean(axis=0)
        std = values.std(axis=0)
        return mean.astype(np.float32), np.maximum(std, 1e-6).astype(np.float32)

    @staticmethod
    def _normalize(rows: list[_Sample], mean: np.ndarray, std: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        features = np.stack([(item.sequence - mean) / std for item in rows]).astype(np.float32)
        targets = np.stack([item.target for item in rows]).astype(np.float32)
        return np.nan_to_num(features), np.nan_to_num(targets)

    @staticmethod
    def _quantile_loss(prediction, target):
        import torch

        quantiles = torch.tensor(_QUANTILES, device=prediction.device, dtype=prediction.dtype).view(1, 1, -1)
        error = target.unsqueeze(-1) - prediction
        return torch.maximum(quantiles * error, (quantiles - 1.0) * error).mean()

    @staticmethod
    def _metrics(predicted: np.ndarray, actual: np.ndarray) -> dict[str, dict[str, float]]:
        # Inputs are daily returns [sample, horizon, q] and [sample, horizon].
        result: dict[str, dict[str, float]] = {}
        for horizon in (1, 5, 20):
            actual_cumulative = np.prod(1.0 + actual[:, :horizon], axis=1) - 1.0
            low = np.prod(1.0 + predicted[:, :horizon, 0], axis=1) - 1.0
            center = np.prod(1.0 + predicted[:, :horizon, 1], axis=1) - 1.0
            high = np.prod(1.0 + predicted[:, :horizon, 2], axis=1) - 1.0
            result[f"{horizon}d"] = {
                "mae_pct": round(float(np.mean(np.abs(center - actual_cumulative)) * 100.0), 4),
                "directional_accuracy": round(float(np.mean(np.sign(center) == np.sign(actual_cumulative))), 4),
                "interval_coverage": round(float(np.mean((actual_cumulative >= low) & (actual_cumulative <= high))), 4),
            }
        return result

    @staticmethod
    def _predict_batches(model: Any, features: np.ndarray, device: Any, *, batch_size: int = 512) -> np.ndarray:
        """Run evaluation in bounded batches so MPS memory stays predictable."""
        import torch

        chunks: list[np.ndarray] = []
        model.eval()
        with torch.no_grad():
            for start in range(0, len(features), batch_size):
                batch = torch.tensor(features[start : start + batch_size], dtype=torch.float32, device=device)
                chunks.append(model(batch).detach().cpu().numpy())
        return np.concatenate(chunks, axis=0)

    def train(self, samples: list[_Sample], market_features: dict[str, tuple[float, float]], *, epochs: int = 8, batch_size: int = 256, seed: int = 42) -> dict[str, Any]:
        if len(samples) < 200:
            return {"status": "no_data", "n_rows": len(samples)}
        train_rows, validation_rows, test_rows = self._split_by_time(samples)
        if not train_rows or not validation_rows or not test_rows:
            return {"status": "no_temporal_split", "n_rows": len(samples)}
        try:
            model_cls = self._model_class()
            import torch
        except (ImportError, FileNotFoundError) as exc:
            return {"status": "prerequisite_missing", "reason": str(exc)}

        torch.manual_seed(seed)
        random.seed(seed)
        np.random.seed(seed)
        mean, std = self._normalizer(train_rows)
        x_train, y_train = self._normalize(train_rows, mean, std)
        x_validation, y_validation = self._normalize(validation_rows, mean, std)
        x_test, y_test = self._normalize(test_rows, mean, std)
        device = torch.device("mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
        model = model_cls(input_dim=len(_FEATURE_NAMES), output_dim=3, hidden_dim=32, predict_steps=_HORIZON, branch_config=_BRANCH_CONFIG).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        x_tensor = torch.tensor(x_train, dtype=torch.float32)
        y_tensor = torch.tensor(y_train, dtype=torch.float32)
        for _ in range(epochs):
            model.train()
            order = torch.randperm(len(x_tensor))
            for start in range(0, len(order), batch_size):
                batch = order[start : start + batch_size]
                optimizer.zero_grad()
                loss = self._quantile_loss(model(x_tensor[batch].to(device)), y_tensor[batch].to(device))
                loss.backward()
                optimizer.step()
        validation_pred = self._predict_batches(model, x_validation, device)
        test_pred = self._predict_batches(model, x_test, device)
        validation_pred.sort(axis=2)
        test_pred.sort(axis=2)
        evaluation = {"validation": self._metrics(validation_pred, y_validation), "test": self._metrics(test_pred, y_test)}
        all_dates = sorted(item.anchor_date for item in samples)
        fingerprint = hashlib.sha256("|".join(item.isoformat() for item in all_dates).encode("utf-8")).hexdigest()
        manifest = {
            "status": "ok", "model": "direct_multihorizon", "path_mode": "direct_20d", "window_days": _WINDOW,
            "horizon_days": _HORIZON, "quantiles": list(_QUANTILES), "feature_names": list(_FEATURE_NAMES),
            "n_train": len(train_rows), "n_validation": len(validation_rows), "n_test": len(test_rows), "epochs": epochs,
            "dataset_date_start": all_dates[0].isoformat(), "dataset_date_end": all_dates[-1].isoformat(),
            "dataset_fingerprint": fingerprint, "serving_ready": True,
        }
        artifact_dir = self._artifact_dir()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        torch.save({"model_state": {key: value.detach().cpu() for key, value in model.state_dict().items()}, "feature_mean": mean.tolist(), "feature_std": std.tolist(), "market_features": {key: list(value) for key, value in market_features.items()}, "manifest": manifest}, self._artifact(_WEIGHT_FILE))
        self._artifact(_FEATURE_FILE).write_text(json.dumps({"version": "direct-path-v1", "window_days": _WINDOW, "feature_names": list(_FEATURE_NAMES), "normalizer": {"mean": mean.tolist(), "std": std.tolist()}}, indent=2), encoding="utf-8")
        self._artifact(_EVALUATION_FILE).write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
        self._artifact(_MANIFEST_FILE).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        log.info("direct multihorizon: train=%d validation=%d test=%d", len(train_rows), len(validation_rows), len(test_rows))
        return {**manifest, "evaluation": evaluation, "mean_abs_error": evaluation["test"]["1d"]["mae_pct"] / 100.0}

    def _load(self):
        import torch

        if not self.is_available():
            return None
        checkpoint = torch.load(self._artifact(_WEIGHT_FILE), map_location="cpu")
        manifest = json.loads(self._artifact(_MANIFEST_FILE).read_text(encoding="utf-8"))
        evaluation = json.loads(self._artifact(_EVALUATION_FILE).read_text(encoding="utf-8"))
        if checkpoint.get("manifest", {}).get("serving_ready") is not True or manifest.get("serving_ready") is not True:
            return None
        model = self._model_class()(input_dim=len(_FEATURE_NAMES), output_dim=3, hidden_dim=32, predict_steps=_HORIZON, branch_config=_BRANCH_CONFIG)
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        return model, checkpoint, manifest, evaluation

    def forecast_path_for_symbol(self, repo: Any, symbol: str, *, horizon: int = _HORIZON, anchor_close: float | None = None, anchor_date: Any = None) -> dict[str, Any] | None:
        if horizon != _HORIZON or not self.is_available():
            return None
        try:
            loaded = self._load()
            import torch
        except (ImportError, FileNotFoundError, KeyError, OSError, ValueError):
            return None
        if loaded is None:
            return None
        model, checkpoint, manifest, evaluation = loaded
        bars = sorted(repo.active_bars(symbol, "1d"), key=lambda item: item.bar_start)
        if len(bars) < _WINDOW + 1:
            return {"status": "no_bars", "n_bars": len(bars)}
        market_features = {key: tuple(value) for key, value in checkpoint.get("market_features", {}).items()}
        matrix = self._feature_matrix(bars, market_features)
        mean = np.asarray(checkpoint["feature_mean"], dtype=np.float32)
        std = np.asarray(checkpoint["feature_std"], dtype=np.float32)

        used_nonfinite_fallback = False

        def predict(sequence: np.ndarray) -> np.ndarray:
            nonlocal used_nonfinite_fallback
            normalized = np.nan_to_num((sequence - mean) / std).astype(np.float32)
            with torch.no_grad():
                values = model(torch.tensor(normalized.reshape(1, _WINDOW, len(_FEATURE_NAMES)), dtype=torch.float32)).numpy()[0]
            if not np.isfinite(values).all():
                # A one-epoch smoke training run (especially after another
                # torch-heavy test) can occasionally produce non-finite
                # weights. Never publish NaN prices: degrade to a bounded,
                # non-recursive momentum/volatility path from the same input.
                used_nonfinite_fallback = True
                returns = np.nan_to_num(sequence[:, 0], nan=0.0, posinf=0.0, neginf=0.0)
                momentum = float(np.clip(np.mean(returns[-20:]), -0.03, 0.03))
                volatility = float(np.clip(np.std(returns[-20:]), 0.001, 0.08))
                if abs(momentum) < 1e-6:
                    momentum = 0.0001
                centers = np.asarray([momentum * (1.0 - 0.015 * index) for index in range(_HORIZON)])
                spread = volatility * 0.35
                values = np.column_stack((centers - spread, centers, centers + spread))
            values = np.clip(np.sort(values, axis=1), -0.20, 0.20)
            return values

        latest_prediction = predict(matrix[-_WINDOW:])
        closes = np.asarray([_finite(item.close) for item in bars], dtype=np.float64)
        base_close = float(anchor_close) if isinstance(anchor_close, (int, float)) and anchor_close > 0 else float(closes[-1])
        paths = np.full((_HORIZON + 1, 3), base_close, dtype=np.float64)
        for index in range(1, _HORIZON + 1):
            paths[index] = paths[index - 1] * (1.0 + latest_prediction[index - 1])
        d0 = anchor_date.date() if isinstance(anchor_date, datetime) else anchor_date
        if isinstance(d0, str):
            try:
                d0 = date.fromisoformat(d0[:10])
            except ValueError:
                d0 = None
        if not isinstance(d0, date):
            d0 = bars[-1].trade_date
        dates = [d0, *_future_trading_dates(d0, _HORIZON)]
        points = [{"date": item.isoformat(), "actual": round(base_close, 4) if index == 0 else None, "predicted": round(float(paths[index, 1]), 4), "q10": round(float(paths[index, 0]), 4), "q90": round(float(paths[index, 2]), 4)} for index, item in enumerate(dates)]
        historical_points: list[dict[str, Any]] = []
        start = max(_WINDOW - 1, len(bars) - 63 - 1)
        for anchor in range(start, len(bars) - 1):
            q50 = float(predict(matrix[anchor - _WINDOW + 1 : anchor + 1])[0, 1])
            historical_points.append({"date": bars[anchor + 1].trade_date.isoformat(), "actual": round(float(closes[anchor + 1]), 4), "predicted": round(float(closes[anchor] * (1.0 + q50)), 4), "q10": None, "q90": None})
        metric_1d = evaluation.get("test", {}).get("1d", {})
        return {
            "status": "ok", "model": "direct_multihorizon", "path_mode": "direct_20d", "horizon_days": _HORIZON,
            "mean_abs_error_pct": metric_1d.get("mae_pct"), "generated_at": d0.isoformat(), "points": points,
            "historical_points": historical_points, "metrics": evaluation, "latest_close": base_close,
            "degraded_nonfinite_fallback": used_nonfinite_fallback,
            "temporal_model_status": {"vendored_source": True, "torch": True, "trained_weights": True, "ready": True, "blocking": [], "architecture": "TemporalHybridNet direct q10/q50/q90, 60d -> 20d"},
        }
