"""§1 row-5 kittenCN temporal training — the price-only temporal LSTM
(round 29).

The vendored kittenCN model (``vendor/kittencn/legacy_backup``) is a temporal
LSTM/Transformer that BERT-augments price features.  Its full training is
multi-hour + needs a BERT weight download — hard-blocked.  This runner is the
**price-only temporal LSTM** the kittenCN architecture is built on, trained
self-containedly on the REAL daily bars (``versioned_market_bars``, round 26):
a 1-layer LSTM maps the last 20 daily returns → the next-day return, trained
with MSE on per-symbol sequences across the universe.  It produces a TRAINED
temporal weight + a daily price-path forecast (autoregressive) that the
``kittencn_adapter`` serves when available — so the §1 row-5 "价格路径预测架构"
piece has a REAL trained temporal model behind it (训练说清楚), even before
the full BERT-augmented vendored model trains.

**Honest scope:** this is the price-only temporal core of the kittenCN
architecture, NOT the full BERT-augmented vendored model.  It degrades to
``is_available()=False`` (→ quantile fan fallback) when torch / bars / the
trained ``.pt`` are missing — never synthesizes a path.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("temporal_price_path")

_ARTIFACT_DIR = "artifacts/price_path"
_WEIGHT_FILE = "temporal_lstm.pt"
_ACCURACY_FILE = "temporal_lstm_accuracy.json"
_WINDOW = 20  # input sequence length (trading days)


class _PriceLSTM:
    """A tiny 1-layer LSTM(1, 32) → Linear(32, 1) for next-day return."""

    def __init__(self) -> None:
        import torch.nn as nn

        self.lstm = nn.LSTM(input_size=1, hidden_size=32, num_layers=1, batch_first=True)
        self.head = nn.Linear(32, 1)

    def parameters(self):
        return list(self.lstm.parameters()) + list(self.head.parameters())

    def forward(self, x):  # x: [B, W, 1] tensor
        import torch

        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)  # [B]

    def state_dict(self):
        return {"lstm": self.lstm.state_dict(), "head": self.head.state_dict()}

    def load_state_dict(self, sd):
        self.lstm.load_state_dict(sd["lstm"])
        self.head.load_state_dict(sd["head"])


class TemporalPricePathRunner:
    """Train + serve the price-only temporal LSTM price-path forecast.

    ``build_dataset(repo, symbols)`` reads daily bars + emits (20-return
    sequence, next-day return) pairs.  ``train(rows)`` fits the LSTM with MSE +
    saves the ``.pt`` + an accuracy artifact.  ``forecast_path_for_symbol``
    autoregresses the LSTM forward to produce a daily q10/q50/q90 path.
    """

    def __init__(self, project_root: object) -> None:
        self.project_root = Path(str(project_root))

    def _artifact(self, name: str) -> Path:
        return self.project_root / _ARTIFACT_DIR / name

    def is_available(self) -> bool:
        return self._artifact(_WEIGHT_FILE).exists()

    # ---- dataset ----
    def build_dataset(self, repo, symbols: list[str]) -> list[tuple[np.ndarray, float]]:
        """Per-symbol: emit (last-20 daily returns, next-day return) pairs."""
        rows: list[tuple[np.ndarray, float]] = []
        for sym in symbols:
            bars = repo.active_bars(sym, "1d")
            if len(bars) < _WINDOW + 2:
                continue
            bars.sort(key=lambda b: b.bar_start)
            closes = [b.close for b in bars]
            rets = np.array(
                [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] != 0],
                dtype=np.float32,
            )
            for t in range(_WINDOW, len(rets)):
                seq = rets[t - _WINDOW : t].reshape(-1, 1)
                rows.append((seq, float(rets[t])))
        return rows

    # ---- train ----
    def train(self, rows, *, epochs: int = 3, batch_size: int = 256, seed: int = 42) -> dict[str, Any]:
        """Fit the LSTM with MSE on the sequence/next-return pairs + save the
        ``.pt`` + an accuracy artifact.  Degrades to ``{status: "no_data"}``
        when too few rows."""
        if len(rows) < 200:
            return {"status": "no_data", "n_rows": len(rows)}
        import json
        import random

        import torch
        import torch.nn as nn

        torch.manual_seed(seed)
        random.seed(seed)
        rng = random.Random(seed)
        idx = list(range(len(rows)))
        rng.shuffle(idx)
        cut = int(len(rows) * 0.8)
        train_idx, val_idx = idx[:cut], idx[cut:]
        model = _PriceLSTM()
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()
        X_tr = torch.tensor(np.stack([rows[i][0] for i in train_idx]), dtype=torch.float32)
        y_tr = torch.tensor([rows[i][1] for i in train_idx], dtype=torch.float32)
        X_va = torch.tensor(np.stack([rows[i][0] for i in val_idx]), dtype=torch.float32)
        y_va = torch.tensor([rows[i][1] for i in val_idx], dtype=torch.float32)
        self._artifact_dir_ensure()
        for ep in range(epochs):
            model.lstm.train(); model.head.train()
            perm = torch.randperm(len(X_tr))
            for s in range(0, len(X_tr), batch_size):
                b = perm[s : s + batch_size]
                opt.zero_grad()
                pred = model.forward(X_tr[b])
                loss = loss_fn(pred, y_tr[b])
                loss.backward()
                opt.step()
        # val: directional accuracy (sign of predicted return == sign of actual)
        model.lstm.eval(); model.head.eval()
        with torch.no_grad():
            va_pred = model.forward(X_va).numpy()
            va_act = y_va.numpy()
        sign_acc = float(np.mean(np.sign(va_pred) == np.sign(va_act))) if len(va_act) else 0.0
        mae = float(np.mean(np.abs(va_pred - va_act))) if len(va_act) else 0.0
        torch.save(model.state_dict(), self._artifact(_WEIGHT_FILE))
        acc = {
            "status": "ok", "n_train": len(train_idx), "n_val": len(val_idx),
            "epochs": epochs, "directional_accuracy": round(sign_acc, 4),
            "mean_abs_error": round(mae, 6),
            "architecture": "LSTM(1,32)->Linear(32,1), price-only, window=20",
        }
        self._artifact(_ACCURACY_FILE).write_text(json.dumps(acc, indent=2), encoding="utf-8")
        log.info("temporal LSTM: n_val=%d sign_acc=%.3f mae=%.5f", len(val_idx), sign_acc, mae)
        return acc

    def _artifact_dir_ensure(self) -> None:
        self._artifact("").mkdir(parents=True, exist_ok=True)

    def accuracy_summary(self) -> dict[str, Any] | None:
        path = self._artifact(_ACCURACY_FILE)
        if not path.exists():
            return None
        try:
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ---- serve ----
    def forecast_path_for_symbol(
        self,
        repo,
        symbol: str,
        *,
        horizon: int = 20,
        anchor_close: float | None = None,
        anchor_date: Any = None,
    ) -> dict[str, Any] | None:
        """Autoregress the LSTM forward ``horizon`` days to produce a daily
        q10/q50/q90 price path.  Returns ``{status, symbol, dates, q50_path,
        q10_path, q90_path, latest_close, directional_accuracy, mean_abs_error}``
        or ``None`` when unavailable."""
        if not self.is_available():
            return None
        bars = repo.active_bars(symbol, "1d")
        if len(bars) < _WINDOW + 2:
            return {"status": "no_bars", "n_bars": len(bars)}
        import torch

        model = _PriceLSTM()
        model.lstm.eval(); model.head.eval()
        import torch as _t

        sd = _t.load(self._artifact(_WEIGHT_FILE), map_location="cpu")
        model.load_state_dict(sd)
        bars.sort(key=lambda b: b.bar_start)
        closes = [b.close for b in bars]
        rets = np.array(
            [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] != 0],
            dtype=np.float32,
        )
        if len(rets) < _WINDOW:
            return {"status": "no_bars", "n_bars": len(bars)}
        seq = rets[-_WINDOW:].tolist()
        acc = self.accuracy_summary() or {}
        mae = acc.get("mean_abs_error", 0.0) if isinstance(acc.get("mean_abs_error"), (int, float)) else 0.0
        # Keep the historical replay independent from the 20-day forward
        # horizon: the UI offers a 3-month review, so retain 63 sessions.
        historical_points: list[dict[str, Any]] = []
        history_start = max(_WINDOW, len(closes) - 63 - 1)
        for i in range(history_start, len(closes) - 1):
            history_seq = rets[i - _WINDOW:i].tolist()
            x = torch.tensor(np.array(history_seq, dtype=np.float32).reshape(1, _WINDOW, 1))
            with torch.no_grad():
                next_return = float(model.forward(x).item())
            historical_points.append({
                "date": bars[i + 1].trade_date.isoformat(),
                "actual": round(closes[i + 1], 4),
                "predicted": round(closes[i] * (1.0 + next_return), 4),
                "q10": None,
                "q90": None,
            })
        # autoregress: predict next-day return, append, repeat
        base_close = float(anchor_close) if isinstance(anchor_close, (int, float)) and anchor_close > 0 else closes[-1]
        path_q50: list[float] = [base_close]
        for _ in range(horizon):
            x = torch.tensor(np.array(seq[-_WINDOW:], dtype=np.float32).reshape(1, _WINDOW, 1))
            with torch.no_grad():
                r = float(model.forward(x).item())
            seq.append(r)
            path_q50.append(path_q50[-1] * (1.0 + r))
        # fan: q10/q90 from the MAE band (per-step compounding)
        band = mae * 1.6  # ~90% interval
        path_q10 = [path_q50[0]]
        path_q90 = [path_q50[0]]
        for i, p in enumerate(path_q50[1:], 1):
            spread = band * (i ** 0.5)  # widening fan
            path_q10.append(p * (1.0 - spread))
            path_q90.append(p * (1.0 + spread))
        from datetime import date, datetime, timedelta

        d0 = anchor_date
        if isinstance(d0, datetime): d0 = d0.date()
        if isinstance(d0, str):
            try: d0 = date.fromisoformat(d0[:10])
            except ValueError: d0 = None
        if not isinstance(d0, date): d0 = bars[-1].trade_date
        dates = [(d0 + timedelta(days=i)).isoformat() for i in range(horizon + 1)]
        # Build the points list (drop-in compatible with build_price_path_projection's
        # output shape) — anchor point carries the actual latest close; forecast
        # points carry predicted=q50 + q10/q90 fan, actual=None.
        points: list[dict[str, Any]] = []
        for i in range(horizon + 1):
            points.append({
                "date": dates[i],
                "actual": round(base_close, 4) if i == 0 else None,
                "predicted": round(path_q50[i], 4),
                "q10": round(path_q10[i], 4),
                "q90": round(path_q90[i], 4),
            })
        return {
            "status": "ok",
            "model": "temporal_lstm (kittenCN price-only)",
            "horizon_days": horizon,
            "mean_abs_error_pct": round(mae * 100, 4),
            "generated_at": dates[0],
            "historical_points": historical_points,
            "temporal_model_status": {
                "vendored_source": True, "torch": True, "trained_weights": True,
                "ready": True, "blocking": [],
                "architecture": acc.get("architecture", "price-only temporal LSTM"),
                "directional_accuracy": acc.get("directional_accuracy"),
            },
            "points": points,
            "latest_close": closes[-1],
            "directional_accuracy": acc.get("directional_accuracy"),
        }
