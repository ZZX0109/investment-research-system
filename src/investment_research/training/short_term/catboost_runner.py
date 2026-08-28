"""§1 row-2 fortune CatBoost short-term direction runner.

Mirrors fortune's ``ml_trading_model.py`` (a CatBoost 1/5/20d direction model)
but adapted to this repo's archived OOF predictions: the runner trains a
``CatBoostClassifier`` that maps the existing long-term model's (score, regime,
industry, coverage, data-quality) → the **actual direction** (sign of the
realized target).  This is a stacking/enhancement model on REAL OOF data — it
learns regime/industry-conditioned direction calibration from the existing
model's predictions + outcomes, so the LLM ``get_four_task_forecasts`` tool
can cite a CatBoost-calibrated direction alongside the baseline.

Artifacts: ``artifacts/short_term/catboost_direction.cbm``.

**Honest scope:** the §1 row-2 fortune model targets 1/5/20d short-term
horizons; this runner trains on the available OOF target (the existing
model's horizon) — a real direction model on real data.  The 1/5/20d
short-term horizons need the raw price pipeline (a future round enriches
the labels).  Degrades to ``is_available()=False`` (→ callers fall back to
the persisted research_forecasts) when catboost or the trained ``.cbm`` is
missing — never synthesizes a forecast.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

# Feature contract: the existing model's OOF row columns used as CatBoost
# input.  Categorical features (regime / industry / data-quality) are passed
# to CatBoost's cat_features so no one-hot encoding is needed.
FEATURES: list[str] = [
    "score",
    "feature_coverage",
    "regime",
    "industry_key",
    "data_quality_status",
]
CAT_FEATURES: list[str] = ["regime", "industry_key", "data_quality_status"]

_ARTIFACT_DIR = "artifacts/short_term"
_MODEL_FILE = "catboost_direction.cbm"


class CatBoostShortTermRunner:
    """Train + serve a CatBoost short-term direction model.

    Construct with ``project_root`` (so artifact paths resolve regardless of
    cwd).  ``train(rows)`` fits a CatBoostClassifier on the OOF feature rows +
    saves the ``.cbm``; ``predict(row)`` loads the model + returns the
    calibrated direction for one feature row, or ``None`` when unavailable.
    """

    def __init__(self, project_root: object) -> None:
        self.project_root = Path(str(project_root))

    def _accuracy_path(self) -> Path:
        return self.project_root / _ARTIFACT_DIR / "catboost_direction_accuracy.json"

    def accuracy_summary(self) -> dict[str, Any] | None:
        """Read the saved OOF directional-accuracy artifact (from
        ``evaluate_with_split``).  Returns ``{status, n_train, n_holdout,
        directional_accuracy, up_precision, down_precision, ...}`` or
        ``None`` when no evaluation has been run (degrade)."""
        path = self._accuracy_path()
        if not path.exists():
            return None
        try:
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def evaluate_with_split(
        self,
        rows: list[Mapping[str, Any]],
        *,
        test_frac: float = 0.2,
        iterations: int = 200,
        depth: int = 4,
        learning_rate: float = 0.1,
        seed: int = 42,
    ) -> dict[str, Any]:
        """Honest OOF directional accuracy: train on a (1-test_frac) split,
        evaluate on the holdout — never in-sample.  Returns ``{status,
        n_train, n_holdout, directional_accuracy, up_precision,
        down_precision, up_recall, down_recall, base_rate}`` + saves it to
        ``catboost_direction_accuracy.json`` so callers (the
        ``get_four_task_forecasts`` tool) can cite "CatBoost OOF 方向命中 X%"
        (训练说清楚).  Degrades to ``{status: "no_data"}`` when rows are
        too few to split.
        """
        if len(rows) < 20:
            return {"status": "no_data", "n_rows": len(rows)}
        import random

        import pandas as pd
        from catboost import CatBoostClassifier, Pool

        rng = random.Random(seed)
        idx = list(range(len(rows)))
        rng.shuffle(idx)
        cut = int(len(rows) * (1.0 - test_frac))
        train_idx, test_idx = idx[:cut], idx[cut:]
        train_rows = [rows[i] for i in train_idx]
        test_rows = [rows[i] for i in test_idx]
        df_tr = pd.DataFrame(train_rows)
        df_te = pd.DataFrame(test_rows)
        pool = Pool(df_tr[FEATURES], df_tr["label"].astype(int), cat_features=CAT_FEATURES)
        model = CatBoostClassifier(
            iterations=iterations, depth=depth, learning_rate=learning_rate,
            verbose=False, allow_writing_files=False, random_seed=seed,
        )
        model.fit(pool)
        preds = [int(p) for p in model.predict(df_te[FEATURES])]
        actuals = [int(a) for a in df_te["label"].astype(int)]
        n = len(preds)
        correct = sum(1 for p, a in zip(preds, actuals) if p == a)
        # Up = label 1, down = label 0.  Precision/recall per class.
        up_pred = [i for i, p in enumerate(preds) if p == 1]
        down_pred = [i for i, p in enumerate(preds) if p == 0]
        up_precision = (sum(1 for i in up_pred if actuals[i] == 1) / len(up_pred)) if up_pred else None
        down_precision = (sum(1 for i in down_pred if actuals[i] == 0) / len(down_pred)) if down_pred else None
        up_actual = [i for i, a in enumerate(actuals) if a == 1]
        down_actual = [i for i, a in enumerate(actuals) if a == 0]
        up_recall = (sum(1 for i in up_actual if preds[i] == 1) / len(up_actual)) if up_actual else None
        down_recall = (sum(1 for i in down_actual if preds[i] == 0) / len(down_actual)) if down_actual else None
        base_rate = max(sum(actuals), n - sum(actuals)) / n  # majority-class base rate
        # Per-regime directional accuracy (训练说清楚: WHERE the model works vs
        # fails — e.g. "在震荡市 60%、在牛市 70%").  Groups the holdout by the
        # regime feature of each test row; only regimes with >=10 holdout rows.
        regime_correct: dict[str, int] = {}
        regime_total: dict[str, int] = {}
        for i, row in enumerate(test_rows):
            reg = str(row.get("regime") or "unknown")
            regime_total[reg] = regime_total.get(reg, 0) + 1
            if preds[i] == actuals[i]:
                regime_correct[reg] = regime_correct.get(reg, 0) + 1
        by_regime = {
            reg: {
                "n": regime_total[reg],
                "directional_accuracy": round(regime_correct.get(reg, 0) / regime_total[reg], 4),
            }
            for reg in sorted(regime_total)
            if regime_total[reg] >= 10
        }
        summary = {
            "status": "ok",
            "n_train": len(train_rows),
            "n_holdout": n,
            "directional_accuracy": round(correct / n, 4),
            "up_precision": round(up_precision, 4) if up_precision is not None else None,
            "down_precision": round(down_precision, 4) if down_precision is not None else None,
            "up_recall": round(up_recall, 4) if up_recall is not None else None,
            "down_recall": round(down_recall, 4) if down_recall is not None else None,
            "majority_base_rate": round(base_rate, 4),
            "edge_over_base": round((correct / n) - base_rate, 4),
            "by_regime": by_regime,
            "iterations": iterations,
            "test_frac": test_frac,
        }
        self._accuracy_path().parent.mkdir(parents=True, exist_ok=True)
        import json

        self._accuracy_path().write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def _model_path(self) -> Path:
        return self.project_root / _ARTIFACT_DIR / _MODEL_FILE

    def is_available(self) -> bool:
        """True iff a trained ``.cbm`` artifact exists (catboost installed)."""
        if not self._model_path().exists():
            return False
        try:
            import catboost  # noqa: F401
        except ImportError:
            return False
        return True

    def feature_importance(self) -> dict[str, Any] | None:
        """Load the trained model + return per-feature importance
        (PredictionValuesChange, sums to 100).  Surfaces WHAT drives the
        direction prediction so callers can cite "CatBoost 方向主要由 score
        (X%)、regime (Y%) 驱动" — the explainability complement to the
        round-15 accuracy (训练说清楚: how accurate + what drives it).
        Returns ``None`` when no model / catboost unavailable (degrade)."""
        if not self.is_available():
            return None
        try:
            from catboost import CatBoostClassifier

            model = CatBoostClassifier()
            model.load_model(str(self._model_path()))
            importances = model.get_feature_importance()
            pairs = sorted(
                zip(FEATURES, [float(v) for v in importances]),
                key=lambda kv: kv[1],
                reverse=True,
            )
            return {
                "status": "ok",
                "features": [{"feature": f, "importance_pct": round(v, 2)} for f, v in pairs],
            }
        except Exception:
            return None

    def train(
        self,
        rows: list[Mapping[str, Any]],
        *,
        iterations: int = 200,
        depth: int = 4,
        learning_rate: float = 0.1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Train a CatBoostClassifier on ``rows`` (each a dict with the
        ``FEATURES`` keys + ``label`` int).  Saves the ``.cbm`` artifact.

        Returns ``{status, rows, classes, model_path}`` or
        ``{status: "no_data"}`` when rows are empty.
        """
        if not rows:
            return {"status": "no_data", "rows": 0, "model_path": None}
        import pandas as pd
        from catboost import CatBoostClassifier, Pool

        df = pd.DataFrame(list(rows))
        X = df[FEATURES]
        y = df["label"].astype(int)
        pool = Pool(X, y, cat_features=CAT_FEATURES)
        model = CatBoostClassifier(
            iterations=iterations,
            depth=depth,
            learning_rate=learning_rate,
            verbose=verbose,
            allow_writing_files=False,
            random_seed=42,
        )
        model.fit(pool)
        self._model_path().parent.mkdir(parents=True, exist_ok=True)
        model.save_model(str(self._model_path()))
        return {
            "status": "ok",
            "rows": len(rows),
            "classes": list(model.classes_.astype(int)) if hasattr(model, "classes_") else [],
            "model_path": str(self._model_path()),
        }

    def predict(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        """Load the trained model + predict the direction for one feature row.

        Returns ``{direction, probability}`` or ``None`` when unavailable /
        the prediction fails (degrade — callers fall back to research_forecasts).
        """
        if not self.is_available():
            return None
        try:
            import pandas as pd
            from catboost import CatBoostClassifier

            model = CatBoostClassifier()
            model.load_model(str(self._model_path()))
            X = pd.DataFrame([{k: row.get(k) for k in FEATURES}])
            pred = int(model.predict(X)[0])
            proba = model.predict_proba(X)[0]
            confidence = float(max(proba)) if len(proba) else None
            return {"direction": pred, "probability": confidence}
        except Exception:
            return None

    def latest_feature_row_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Read the symbol's most-recent archived OOF row from the predictions
        parquet + return its CatBoost feature dict (score, feature_coverage,
        regime, industry_key, data_quality_status).  This is the feature row
        ``predict`` consumes to produce a calibrated direction for the asset.
        Returns ``None`` when the parquet / the symbol has no OOF rows
        (degrade — never synthesizes)."""
        path = self.project_root / "artifacts" / "long_term_training" / "latest.predictions.parquet"
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(
                path,
                columns=[
                    "split", "symbol", "decision_date", "industry_key",
                    "regime", "feature_coverage", "data_quality_status", "score",
                ],
            )
        except (ImportError, OSError, ValueError, KeyError):
            return None
        requested = "".join(ch for ch in str(symbol).upper() if ch.isalnum()).zfill(6)
        latest: dict[str, Any] | None = None
        latest_date = ""
        for row in table.to_pylist():
            if str(row.get("split", "")) != "oof":
                continue
            cand = "".join(ch for ch in str(row.get("symbol") or "").upper() if ch.isalnum()).zfill(6)
            if cand != requested:
                continue
            date = str(row.get("decision_date") or "")
            if date >= latest_date:
                latest_date = date
                latest = {
                    "score": float(row.get("score") or 0.0),
                    "feature_coverage": float(row.get("feature_coverage") or 1.0),
                    "regime": str(row.get("regime") or "unknown"),
                    "industry_key": str(row.get("industry_key") or "unknown"),
                    "data_quality_status": str(row.get("data_quality_status") or "unknown"),
                }
        return latest

    def calibrated_direction_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        """One-shot: fetch the symbol's latest OOF feature row + predict the
        CatBoost-calibrated direction.  Returns ``{direction, probability,
        as_of_decision_date}`` or ``None`` when no model / no feature row
        (degrade — callers fall back to research_forecasts)."""
        row = self.latest_feature_row_for_symbol(symbol)
        if row is None:
            return None
        prediction = self.predict(row)
        if prediction is None:
            return None
        return {**prediction, "features": row}
