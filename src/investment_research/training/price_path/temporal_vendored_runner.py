"""Temporal price-path runner backed by the VENDORED kittenCN architecture.

Round 31 — this is the faithful port of the §1 row-5 named model
(``temporal_hybrid``).  Where ``temporal_runner.py`` (round 29) ships a
self-contained simplified LSTM as the temporal CORE, this runner drives the
ACTUAL vendored ``TemporalHybridNet`` from ``vendor/kittencn/src/stock_prediction/
models/temporal_hybrid.py`` — the depthwise-conv + attention hybrid that the
goal names explicitly — trained price-only on the universe's real daily bars.

Honest scope: this is the vendored architecture's temporal core trained WITHOUT
the multi-hour BERT branch (the main ``predict.py`` is price-only per its 0 BERT
refs).  The directional accuracy is surfaced verbatim (训练说清楚); a tiny
price-only next-day model is expected to sit near coin-flip.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("temporal_vendored")

_ARTIFACT_DIR = "artifacts/price_path"
_WINDOW = 20  # input sequence length (trading days)

# The two §1 row-5 NAMED vendored kittenCN models. Each maps to its model class
# + artifact filenames so one runner drives either.
_MODEL_SPECS: dict[str, dict[str, str]] = {
    "temporal_hybrid": {
        "module": "stock_prediction.models.temporal_hybrid",
        "class": "TemporalHybridNet",
        "weight": "temporal_hybrid.pt",
        "accuracy": "temporal_hybrid_accuracy.json",
        "arch": "TemporalHybridNet (vendored kittenCN temporal_hybrid, price-only, window=20)",
        "tag": "temporal_hybrid (vendored kittenCN, price-only)",
    },
    "ptft_vssm": {
        "module": "stock_prediction.models.ptft_vssm",
        "class": "PTFTVSSMEnsemble",
        "weight": "temporal_ptft_vssm.pt",
        "accuracy": "temporal_ptft_vssm_accuracy.json",
        "arch": "PTFTVSSMEnsemble (vendored kittenCN ptft_vssm, price-only, window=20)",
        "tag": "ptft_vssm (vendored kittenCN, price-only)",
    },
}


def _vendored_src_path(project_root: Path) -> Path:
    return project_root / "vendor" / "kittencn" / "src"


def _vendored_source_present(project_root: Path) -> bool:
    return (_vendored_src_path(project_root) / "stock_prediction" / "models" / "temporal_hybrid.py").exists()


class TemporalVendoredRunner:
    """Drives a vendored kittenCN temporal model on the universe's daily bars.

    ``project_root`` is where the trained artifacts live (``artifacts/price_path``);
    ``vendored_root`` (defaults to ``project_root``) locates the vendored
    ``vendor/kittencn/src`` tree — separated so tests can point artifacts at a
    temp dir while still resolving the real vendored source.  ``model_kind``
    selects which §1 row-5 named model to drive (``temporal_hybrid`` default,
    or ``ptft_vssm``).
    """

    def __init__(
        self,
        project_root: Path | str,
        *,
        vendored_root: Path | str | None = None,
        model_kind: str = "temporal_hybrid",
    ) -> None:
        if model_kind not in _MODEL_SPECS:
            raise ValueError(f"unknown model_kind {model_kind!r}")
        self.project_root = Path(project_root)
        self.vendored_root = Path(vendored_root) if vendored_root is not None else self.project_root
        self.model_kind = model_kind
        self._spec = _MODEL_SPECS[model_kind]
        self._weight_file = self._spec["weight"]
        self._accuracy_file = self._spec["accuracy"]
        self._arch = self._spec["arch"]
        self._tag = self._spec["tag"]

    # ---- artifacts ----
    def _artifact(self, name: str) -> Path:
        return self.project_root / _ARTIFACT_DIR / name

    def _artifact_dir_ensure(self) -> None:
        (self.project_root / _ARTIFACT_DIR).mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return self._artifact(self._weight_file).exists() and self._artifact(self._accuracy_file).exists()

    # ---- dataset (same shape as temporal_runner: 20-return seq, next-return) ----
    def build_dataset(self, repo, symbols: list[str]) -> list[tuple[np.ndarray, float]]:
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
        """Fit the vendored ``TemporalHybridNet`` with MSE + save ``.pt`` + an
        accuracy artifact.  Degrades to ``{status: "no_data"}`` when too few rows
        or when the vendored source is absent."""
        if not _vendored_source_present(self.vendored_root):
            return {"status": "vendored_source_absent"}
        if len(rows) < 200:
            return {"status": "no_data", "n_rows": len(rows)}
        import json
        import random

        src = str(_vendored_src_path(self.vendored_root))
        if src not in sys.path:
            sys.path.insert(0, src)
        import importlib

        import torch
        import torch.nn as nn  # noqa: F401

        model_module = importlib.import_module(self._spec["module"])
        model_cls = getattr(model_module, self._spec["class"])

        torch.manual_seed(seed)
        random.seed(seed)
        rng = random.Random(seed)
        idx = list(range(len(rows)))
        rng.shuffle(idx)
        cut = int(len(rows) * 0.8)
        train_idx, val_idx = idx[:cut], idx[cut:]
        model = model_cls(input_dim=1, output_dim=1, hidden_dim=32, predict_steps=1)
        model.train()
        opt = torch.optim.Adam(model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()
        X_tr = torch.tensor(np.stack([rows[i][0] for i in train_idx]), dtype=torch.float32)
        y_tr = torch.tensor([rows[i][1] for i in train_idx], dtype=torch.float32)
        X_va = torch.tensor(np.stack([rows[i][0] for i in val_idx]), dtype=torch.float32)
        y_va = torch.tensor([rows[i][1] for i in val_idx], dtype=torch.float32)
        self._artifact_dir_ensure()
        for ep in range(epochs):
            model.train()
            perm = torch.randperm(len(X_tr))
            for s in range(0, len(X_tr), batch_size):
                b = perm[s : s + batch_size]
                opt.zero_grad()
                pred = model.forward(X_tr[b]).squeeze(-1)
                loss = loss_fn(pred, y_tr[b])
                loss.backward()
                opt.step()
        model.eval()
        with torch.no_grad():
            va_pred = model.forward(X_va).squeeze(-1).numpy()
            va_act = y_va.numpy()
        sign_acc = float(np.mean(np.sign(va_pred) == np.sign(va_act))) if len(va_act) else 0.0
        mae = float(np.mean(np.abs(va_pred - va_act))) if len(va_act) else 0.0
        torch.save(model.state_dict(), self._artifact(self._weight_file))
        acc = {
            "status": "ok", "n_train": len(train_idx), "n_val": len(val_idx),
            "epochs": epochs, "directional_accuracy": round(sign_acc, 4),
            "mean_abs_error": round(mae, 6), "architecture": self._arch,
        }
        self._artifact(self._accuracy_file).write_text(json.dumps(acc, indent=2), encoding="utf-8")
        log.info("vendored temporal_hybrid: n_val=%d sign_acc=%.3f mae=%.5f", len(val_idx), sign_acc, mae)
        return acc

    def accuracy_summary(self) -> dict[str, Any] | None:
        path = self._artifact(self._accuracy_file)
        if not path.exists():
            return None
        try:
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def prereq_status(self) -> dict[str, Any]:
        import torch

        return {
            "vendored_source": _vendored_source_present(self.vendored_root),
            "torch": True,
            "trained_weights": self.is_available(),
            "ready": _vendored_source_present(self.vendored_root) and self.is_available(),
            "blocking": [] if self.is_available() else ["temporal_hybrid weights not trained"],
            "architecture": self._arch,
        }

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
        """Autoregress the vendored ``TemporalHybridNet`` forward ``horizon``
        days to produce a daily q10/q50/q90 price path."""
        if not self.is_available() or not _vendored_source_present(self.vendored_root):
            return None
        bars = repo.active_bars(symbol, "1d")
        if len(bars) < _WINDOW + 2:
            return {"status": "no_bars", "n_bars": len(bars)}
        src = str(_vendored_src_path(self.vendored_root))
        if src not in sys.path:
            sys.path.insert(0, src)
        import importlib

        import torch

        model_module = importlib.import_module(self._spec["module"])
        model_cls = getattr(model_module, self._spec["class"])

        model = model_cls(input_dim=1, output_dim=1, hidden_dim=32, predict_steps=1)
        model.eval()
        sd = torch.load(self._artifact(self._weight_file), map_location="cpu")
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
        base_close = float(anchor_close) if isinstance(anchor_close, (int, float)) and anchor_close > 0 else closes[-1]
        # Historical replay is an evaluation surface, not the forward horizon.
        # Keep three months (63 trading sessions) so both the 1m and 3m chart
        # can show a continuous predicted-vs-actual comparison.
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
        path_q50: list[float] = [base_close]
        for _ in range(horizon):
            x = torch.tensor(np.array(seq[-_WINDOW:], dtype=np.float32).reshape(1, _WINDOW, 1))
            with torch.no_grad():
                r = float(model.forward(x).item())
            seq.append(r)
            path_q50.append(path_q50[-1] * (1.0 + r))
        band = mae * 1.6
        path_q10 = [path_q50[0]]
        path_q90 = [path_q50[0]]
        for i, p in enumerate(path_q50[1:], 1):
            spread = band * (i ** 0.5)
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
            "model": self._tag,
            "horizon_days": horizon,
            "mean_abs_error_pct": round(mae * 100, 4),
            "generated_at": dates[0],
            "historical_points": historical_points,
            "temporal_model_status": {
                "vendored_source": True, "torch": True, "trained_weights": True,
                "ready": True, "blocking": [],
                "architecture": acc.get("architecture", self._arch),
                "directional_accuracy": acc.get("directional_accuracy"),
            },
            "points": points,
            "latest_close": closes[-1],
            "directional_accuracy": acc.get("directional_accuracy"),
        }
