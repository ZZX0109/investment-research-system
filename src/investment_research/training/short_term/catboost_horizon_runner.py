"""§1 row-2 fortune CatBoost 1/5/20d short-term horizon runner — the price-based
variant (round 27, post data-root unblock).

The existing ``catboost_runner.py`` (round 14) is a 240d *stacking* model on the
long-term model's archived OOF (score/regime/industry → direction).  This runner
is the **price-based 1/5/20d** variant the fortune ``ml_trading_model.py`` piece
was meant to provide: it reads REAL daily ``VersionedMarketBar`` rows from
``versioned_market_bars`` (populated by ``scripts/seed_market_bars_from_akshare.py``
in round 26), builds technical features per (symbol, date), labels each row with
the 1/5/20-day forward-return direction, and trains one ``CatBoostClassifier``
per horizon.

Artifacts: ``artifacts/short_term/catboost_horizon_{1d,5d,20d}.cbm`` +
``catboost_horizon_accuracy.json``.

**Honest scope:** this is a REAL direction model on REAL price bars (no
synthesis).  It degrades to ``is_available()=False`` (callers fall back to the
persisted ``research_forecasts``) when catboost / bars / the trained ``.cbm``
are missing.  It is ADDITIVE to the baseline 1/5/20d forecasts in
``get_four_task_forecasts`` (a ``catboost_short_term_horizons`` field), never
replacing them.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger("catboost_horizon")

HORIZONS = ("1d", "5d", "20d")
_ARTIFACT_DIR = "artifacts/short_term"

# Price-based technical features (per (symbol, date)).  All ratios / bounded so
# the model generalizes across price levels.  ``symbol`` is categorical so the
# model can learn per-symbol bias without one-hot.
FEATURES: list[str] = [
    "ret_1d", "ret_5d", "ret_20d", "vol_20d", "volume_ratio_5d",
    "ma_5_ratio", "ma_20_ratio", "range_20d", "symbol",
]
CAT_FEATURES: list[str] = ["symbol"]


def _features_for_window(closes: list[float], highs: list[float], lows: list[float],
                         volumes: list[float], symbol: str) -> dict[str, Any] | None:
    """Build the feature row for the LAST bar in the window (needs >= 20 prior
    bars).  Returns None when the window is too short."""
    if len(closes) < 21:
        return None
    c = closes[-1]
    import statistics

    def _ret(back: int) -> float:
        if len(closes) <= back or closes[-1 - back] == 0:
            return 0.0
        return closes[-1] / closes[-1 - back] - 1.0

    ret_1d = _ret(1)
    ret_5d = _ret(5)
    ret_20d = _ret(20)
    daily_rets = [
        (closes[i] / closes[i - 1] - 1.0) for i in range(max(1, len(closes) - 20), len(closes))
        if closes[i - 1] != 0
    ]
    vol_20d = statistics.pstdev(daily_rets) if len(daily_rets) >= 2 else 0.0
    vols = volumes[-5:]
    vol_mean = sum(vols) / len(vols) if vols and sum(vols) > 0 else 0.0
    volume_ratio_5d = (volumes[-1] / vol_mean) if vol_mean > 0 else 1.0
    ma5 = sum(closes[-5:]) / 5.0
    ma20 = sum(closes[-20:]) / 20.0
    hi20 = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    lo20 = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    return {
        "ret_1d": ret_1d, "ret_5d": ret_5d, "ret_20d": ret_20d, "vol_20d": vol_20d,
        "volume_ratio_5d": volume_ratio_5d, "ma_5_ratio": c / ma5 if ma5 else 1.0,
        "ma_20_ratio": c / ma20 if ma20 else 1.0,
        "range_20d": (hi20 - lo20) / c if c > 0 else 0.0, "symbol": symbol,
    }


class CatBoostHorizonRunner:
    """Train + serve the price-based 1/5/20d CatBoost direction model.

    ``build_dataset(repo, symbols)`` reads daily bars from
    ``versioned_market_bars`` + returns labeled rows.  ``train(rows)``
    fits one ``CatBoostClassifier`` per horizon + saves ``.cbm`` + an
    accuracy artifact.  ``horizon_forecast_for_symbol(repo, symbol, as_of)``
    loads the models + predicts the 1/5/20d direction for the symbol's
    latest bar.  Degrades to ``None`` when unavailable.
    """

    def __init__(self, project_root: object) -> None:
        self.project_root = Path(str(project_root))

    def _artifact(self, name: str) -> Path:
        return self.project_root / _ARTIFACT_DIR / name

    def _model_path(self, horizon: str) -> Path:
        return self._artifact(f"catboost_horizon_{horizon}.cbm")

    def is_available(self) -> bool:
        return all(self._model_path(h).exists() for h in HORIZONS)

    # ---- dataset build ----
    def build_dataset(self, repo, symbols: list[str]) -> list[dict[str, Any]]:
        """Read active daily bars per symbol + emit one labeled row per
        (symbol, date) that has enough history (>= 20 prior bars) AND a
        forward window for ALL three horizons (so each row carries y_1d /
        y_5d / y_20d).  Returns a list of dicts (features + 3 labels)."""
        rows: list[dict[str, Any]] = []
        for sym in symbols:
            bars = repo.active_bars(sym, "1d")
            if len(bars) < 41:  # 20 history + 20 forward (max horizon)
                continue
            bars.sort(key=lambda b: b.bar_start)
            closes = [b.close for b in bars]
            highs = [b.high for b in bars]
            lows = [b.low for b in bars]
            volumes = [b.volume or 0.0 for b in bars]
            for t in range(20, len(closes) - 20):
                feat = _features_for_window(closes[: t + 1], highs[: t + 1],
                                            lows[: t + 1], volumes[: t + 1], sym)
                if feat is None:
                    continue
                # forward direction labels (1 = up, 0 = down)
                y_1d = 1 if closes[t + 1] > closes[t] else 0
                y_5d = 1 if closes[t + 5] > closes[t] else 0
                y_20d = 1 if closes[t + 20] > closes[t] else 0
                rows.append({**feat, "y_1d": y_1d, "y_5d": y_5d, "y_20d": y_20d})
        return rows

    # ---- train ----
    def train(self, rows: list[Mapping[str, Any]], *, test_frac: float = 0.2,
              iterations: int = 200, seed: int = 42) -> dict[str, Any]:
        """Train one CatBoostClassifier per horizon on a (1-test_frac) split,
        evaluate directional accuracy on the holdout — never in-sample.
        Saves each ``.cbm`` + a combined accuracy artifact.  Degrades to
        ``{status: "no_data"}`` when too few rows."""
        if len(rows) < 50:
            return {"status": "no_data", "n_rows": len(rows)}
        import random

        import pandas as pd
        from catboost import CatBoostClassifier, Pool

        self._artifact_dir_ensure()
        rng = random.Random(seed)
        idx = list(range(len(rows)))
        rng.shuffle(idx)
        cut = int(len(rows) * (1.0 - test_frac))
        train_idx, test_idx = idx[:cut], idx[cut:]
        df_tr = pd.DataFrame([rows[i] for i in train_idx])
        df_te = pd.DataFrame([rows[i] for i in test_idx])
        acc: dict[str, Any] = {"status": "ok", "n_train": len(df_tr), "n_holdout": len(df_te),
                               "horizons": {}}
        for h in HORIZONS:
            label = f"y_{h}"
            pool = Pool(df_tr[FEATURES], df_tr[label].astype(int), cat_features=CAT_FEATURES)
            model = CatBoostClassifier(
                iterations=iterations, depth=4, learning_rate=0.1,
                verbose=False, allow_writing_files=False, random_seed=seed,
            )
            model.fit(pool)
            model.save_model(str(self._model_path(h)))
            preds = [int(p) for p in model.predict(df_te[FEATURES])]
            actuals = [int(a) for a in df_te[label].astype(int)]
            n = len(preds)
            correct = sum(1 for p, a in zip(preds, actuals) if p == a)
            base = max(sum(actuals), n - sum(actuals)) / n if n else 0.0
            acc["horizons"][h] = {
                "n_holdout": n, "directional_accuracy": correct / n if n else 0.0,
                "base_rate": base, "edge": (correct / n - base) if n else 0.0,
                "up_pct": sum(actuals) / n if n else 0.0,
            }
            log.info("horizon %s: n=%d acc=%.3f base=%.3f edge=%.3f",
                     h, n, correct / n if n else 0, base, (correct / n - base) if n else 0)
        self._artifact("catboost_horizon_accuracy.json").write_text(
            json.dumps(acc, indent=2), encoding="utf-8")
        return acc

    def _artifact_dir_ensure(self) -> None:
        d = self._artifact("")
        d.mkdir(parents=True, exist_ok=True)

    # ---- serve ----
    def accuracy_summary(self) -> dict[str, Any] | None:
        path = self._artifact("catboost_horizon_accuracy.json")
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def horizon_forecast_for_symbol(self, repo, symbol: str) -> dict[str, Any] | None:
        """Predict the 1/5/20d direction for the symbol's latest bar.
        Returns ``{horizons: {1d: {direction, probability, n_train}, ...},
        status: "ok" | "no_model" | "no_bars"}`` or None when unavailable."""
        if not self.is_available():
            return None
        bars = repo.active_bars(symbol, "1d")
        if len(bars) < 21:
            return {"status": "no_bars", "n_bars": len(bars)}
        bars.sort(key=lambda b: b.bar_start)
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume or 0.0 for b in bars]
        feat = _features_for_window(closes, highs, lows, volumes, symbol)
        if feat is None:
            return {"status": "no_bars", "n_bars": len(bars)}
        import pandas as pd

        from catboost import CatBoostClassifier

        df = pd.DataFrame([feat])[FEATURES]
        out: dict[str, Any] = {"status": "ok", "as_of": bars[-1].trade_date.isoformat(),
                               "latest_close": closes[-1], "horizons": {}}
        acc = self.accuracy_summary() or {}
        horizons_acc = acc.get("horizons") or {}
        for h in HORIZONS:
            m = CatBoostClassifier()
            m.load_model(str(self._model_path(h)))
            pred = int(m.predict(df)[0])
            proba = float(m.predict_proba(df)[0][pred])
            ha = horizons_acc.get(h, {}) if isinstance(horizons_acc, dict) else {}
            out["horizons"][h] = {
                "direction": "up" if pred == 1 else "down",
                "probability": round(proba, 4),
                "n_holdout": ha.get("n_holdout"),
                "directional_accuracy": ha.get("directional_accuracy"),
                "edge": ha.get("edge"),
            }
        return out

    # ---- per-asset walk-forward (§1 row-3, round 28) ----
    def walk_forward_daily_for_symbol(self, repo, symbol: str) -> dict[str, Any] | None:
        """Replay the trained 1/5/20d model over the symbol's historical bars:
        at each date t (with >= 20 prior bars + a forward window for ALL three
        horizons), build the feature row, predict the 1/5/20d direction, compare
        to the realized forward direction.  Returns per-horizon realized
        directional accuracy (训练说清楚 WHERE per-asset for the short-term
        model).  Mirrors the long-term ``summarize_walk_forward`` output shape
        (status/decision_count/directional_accuracy/mean_abs_error/
        mean_signed_error) so the snapshot + plain_answer can render it
        identically.  Degrades to None when no model / no bars.
        """
        if not self.is_available():
            return None
        bars = repo.active_bars(symbol, "1d")
        if len(bars) < 41:
            return {"status": "no_bars", "n_bars": len(bars), "horizons": {}}
        bars.sort(key=lambda b: b.bar_start)
        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        volumes = [b.volume or 0.0 for b in bars]
        import pandas as pd

        from catboost import CatBoostClassifier

        models = {h: CatBoostClassifier() for h in HORIZONS}
        for h in HORIZONS:
            models[h].load_model(str(self._model_path(h)))
        # per-horizon accumulators
        acc = {h: {"correct": 0, "n": 0, "up_pred": 0,
                   "abs_err": [], "signed_err": [], "conf": []} for h in HORIZONS}
        dates_detail: list[dict] = []
        for t in range(20, len(closes) - 20):
            feat = _features_for_window(closes[: t + 1], highs[: t + 1],
                                        lows[: t + 1], volumes[: t + 1], symbol)
            if feat is None:
                continue
            df = pd.DataFrame([feat])[FEATURES]
            for h in HORIZONS:
                m = models[h]
                pred = int(m.predict(df)[0])
                proba = float(m.predict_proba(df)[0][pred])
                actual = 1 if closes[t + (1 if h == "1d" else 5 if h == "5d" else 20)] > closes[t] else 0
                a = acc[h]
                a["n"] += 1
                a["correct"] += int(pred == actual)
                a["up_pred"] += int(pred == 1)
                a["conf"].append(proba)
                # error = distance between predicted prob-of-actual and certainty
                a["abs_err"].append(1.0 - (proba if pred == actual else (1.0 - proba)))
                a["signed_err"].append((1.0 - proba) if actual == 1 else (proba - 1.0))
        out_h: dict[str, Any] = {}
        for h in HORIZONS:
            a = acc[h]
            n = a["n"]
            if n == 0:
                out_h[h] = {"status": "no_data", "decision_count": 0}
                continue
            da = a["correct"] / n
            mae = sum(a["abs_err"]) / n
            mse = sum(a["signed_err"]) / n
            out_h[h] = {
                "status": "ok",
                "decision_count": n,
                "directional_accuracy": round(da, 4),
                "mean_abs_error": round(mae, 4),
                "mean_signed_error": round(mse, 4),
                "mean_confidence": round(sum(a["conf"]) / n, 4),
                "up_decision_pct": round(a["up_pred"] / n, 4),
            }
        return {"status": "ok", "symbol": symbol, "n_bars": len(bars), "horizons": out_h}
