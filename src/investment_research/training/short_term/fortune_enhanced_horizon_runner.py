"""Walk-forward CatBoost candidate using the Fortune-inspired feature panel.

Unlike the deployed lightweight runner, this candidate is deliberately trained
and evaluated chronologically.  It is an experiment artifact until its
walk-forward metrics improve on the current short-horizon baseline.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
import hashlib
import json
from math import sqrt
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from investment_research.training.short_term.fortune_feature_engine import (
    CausalMarketContext,
    FORTUNE_CATEGORICAL_FEATURES,
    FORTUNE_ENHANCED_FEATURES,
    FortuneFeatureCache,
    load_local_rate_observations,
    load_local_northbound_history,
    northbound_features_asof,
    rate_features_asof,
    symbol_feature_rows,
)
from investment_research.training.short_term.lstm_garch import LSTMGarchResidualModel, LSTM_GARCH_FEATURE
from investment_research.training.short_term.catboost_horizon_runner import FEATURES as PRICE_BASELINE_FEATURES


HORIZONS = ("1d", "5d", "20d")
FORTUNE_CORE_FEATURES = [
    "volatility_30pct", "ma250_slope", "volatility_30d", "bb_width_ma60",
    "network_regime_interaction", "volatility_70pct", "distance_support_120d",
    "network_garch_interaction", "garch_conditional_vol", "garch_vol_ratio_20",
    "garch_persistence", "garch_alpha", "garch_beta", "lstm_garch_residual_vol",
    "hmm_bear_probability", "hmm_range_probability", "hmm_bull_probability",
    "hmm_regime", "hmm_regime_duration", "network_cohesion", "network_degree",
    "network_betweenness", "network_community_size",
]
_HORIZON_DAYS = {"1d": 1, "5d": 5, "20d": 20}
_ARTIFACT_DIR = "artifacts/short_term/fortune_enhanced"


class FortuneEnhancedHorizonRunner:
    """Build, train and audit the enriched Fortune-style CatBoost candidate."""

    def __init__(self, project_root: object, *, candidate_name: str = "fortune_enhanced", feature_scope: str = "enhanced") -> None:
        self.project_root = Path(str(project_root))
        if feature_scope not in {"enhanced", "fortune_core", "price_baseline"}:
            raise ValueError("feature_scope must be enhanced, fortune_core or price_baseline")
        self.candidate_name = candidate_name
        self.feature_scope = feature_scope

    def _root(self) -> Path:
        path = self.project_root / "artifacts/short_term" / self.candidate_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _model_path(self, horizon: str) -> Path:
        return self._root() / f"fortune_enhanced_{horizon}.cbm"

    def _manifest_path(self) -> Path:
        return self._root() / "manifest.json"

    def _checkpoint_path(self, horizon: str, fold_id: int) -> Path:
        return self._root() / "checkpoints" / f"{horizon}_fold_{fold_id}.json"

    def _hybrid_checkpoint_path(self, rows: list[Mapping[str, Any]], train_end: str, seed: int) -> Path:
        cache_key = str(rows[0].get("cache_key", "unknown")) if rows else "unknown"
        identity = hashlib.sha256(f"{cache_key}|{train_end}|{seed}".encode()).hexdigest()[:16]
        return self._root() / "hybrid_checkpoints" / f"lstm_garch_{identity}.pt"

    def build_dataset(self, repo, symbols: list[str], *, use_cache: bool = True, feature_workers: int | None = None) -> list[dict[str, Any]]:
        """Materialise an as-of feature panel and 1/5/20d labels from bars."""
        bars_by_symbol: dict[str, list[Any]] = {}
        close_maps: dict[str, dict[date, float]] = {}
        for symbol in sorted(set(symbols)):
            bars = sorted(repo.active_bars(symbol, "1d"), key=lambda item: item.trade_date)
            if len(bars) >= 41:
                bars_by_symbol[symbol] = bars
                close_maps[symbol] = {bar.trade_date: float(bar.close) for bar in bars}
        if not bars_by_symbol:
            return []
        cache = FortuneFeatureCache(self.project_root)
        cache_key = cache.key(close_maps)
        context = cache.load(cache_key) if use_cache else None
        if context is None:
            context = CausalMarketContext().build(close_maps)
            cache.save(cache_key, context)
        rates = load_local_rate_observations(self.project_root)
        northbound = load_local_northbound_history(self.project_root)
        # GARCH and technical features are independent by symbol.  Parallelise
        # this CPU-bound stage while keeping the shared database reads above
        # single-threaded and the output order deterministic.
        feature_inputs = {
            symbol: (
                [bar.trade_date for bar in bars], [float(bar.close) for bar in bars],
                [float(bar.high) for bar in bars], [float(bar.low) for bar in bars],
                [float(bar.volume or 0.0) for bar in bars],
            )
            for symbol, bars in bars_by_symbol.items()
        }
        workers = feature_workers if feature_workers is not None else min(8, max(1, os.cpu_count() or 1))
        if workers <= 1:
            own_by_symbol = {symbol: symbol_feature_rows(symbol, *values) for symbol, values in feature_inputs.items()}
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {symbol: pool.submit(symbol_feature_rows, symbol, *values) for symbol, values in feature_inputs.items()}
                own_by_symbol = {symbol: futures[symbol].result() for symbol in sorted(futures)}
        rows: list[dict[str, Any]] = []
        for symbol, bars in bars_by_symbol.items():
            dates = [bar.trade_date for bar in bars]
            closes = [float(bar.close) for bar in bars]
            highs = [float(bar.high) for bar in bars]
            lows = [float(bar.low) for bar in bars]
            volumes = [float(bar.volume or 0.0) for bar in bars]
            own_features = own_by_symbol[symbol]
            for index in range(20, len(bars) - 20):
                day = dates[index]
                features: dict[str, Any] = {
                    **own_features[day], **context.get((symbol, day), {}),
                    **rate_features_asof(rates, day),
                    **northbound_features_asof(northbound.get(symbol, []), day),
                }
                cohesion = _num(features.get("network_cohesion"))
                duration = _num(features.get("hmm_regime_duration"))
                garch = _num(features.get("garch_conditional_vol"))
                features["network_regime_interaction"] = cohesion * duration if np.isfinite(cohesion) and np.isfinite(duration) else float("nan")
                features["network_garch_interaction"] = cohesion * garch if np.isfinite(cohesion) and np.isfinite(garch) else float("nan")
                label_values: dict[str, Any] = {}
                for horizon, sessions in _HORIZON_DAYS.items():
                    forward_return = closes[index + sessions] / closes[index] - 1.0 if closes[index] else 0.0
                    label_values[f"y_{horizon}"] = int(forward_return > 0)
                    label_values[f"forward_return_{horizon}"] = forward_return
                rows.append({**features, **label_values, "decision_date": day.isoformat(), "cache_key": cache_key})
        return rows

    def train_walk_forward(
        self,
        rows: list[Mapping[str, Any]],
        *,
        n_folds: int = 12,
        iterations: int = 500,
        seed: int = 42,
        purge_sessions: int = 20,
        max_features: int = 500,
        use_lstm_garch: bool = True,
        resume: bool = True,
        threshold_mode: str = "fixed",
        horizons: tuple[str, ...] = HORIZONS,
    ) -> dict[str, Any]:
        """Run expanding-window folds and persist final models + a model card."""
        if len(rows) < 200:
            return {"status": "no_data", "n_rows": len(rows)}
        if self.feature_scope == "price_baseline":
            features = list(PRICE_BASELINE_FEATURES)
        elif self.feature_scope == "fortune_core":
            features = [name for name in FORTUNE_CORE_FEATURES if name in _usable_features(rows)]
        else:
            features = _usable_features(rows)[:max_features]
        if use_lstm_garch and self.feature_scope in {"enhanced", "fortune_core"} and LSTM_GARCH_FEATURE not in features:
            features.append(LSTM_GARCH_FEATURE)
        dates = sorted({str(row["decision_date"]) for row in rows})
        if len(dates) < n_folds + purge_sessions + 20:
            return {"status": "no_folds", "decision_dates": len(dates)}
        folds = _expanding_folds(dates, n_folds=n_folds, purge_sessions=purge_sessions)
        report: dict[str, Any] = {
            "schema_version": "fortune-enhanced-walk-forward-v1",
            "candidate_name": self.candidate_name,
            "feature_scope": self.feature_scope,
            "status": "ok",
            "n_rows": len(rows),
            "decision_date_count": len(dates),
            "n_folds": len(folds),
            "purge_sessions": purge_sessions,
            "seed": seed,
            "feature_count": len(features),
            "features": features,
            "lstm_garch_enabled": use_lstm_garch,
            "feature_selection": {"max_features": max_features, "selected_count": len(features), "method": "all_valid_features_under_cap" if len(features) < max_features else "capped_feature_list"},
            "resume": bool(resume),
            "threshold_mode": threshold_mode,
            "horizons": {},
        }
        final_rows = list(rows)
        if use_lstm_garch:
            final_hybrid = LSTMGarchResidualModel(seed=seed).fit(final_rows)
            final_rows = _with_lstm_feature(final_rows, final_hybrid.predict(final_rows))
            final_hybrid.save(self._root() / "lstm_garch_residual_vol.pt")
        for horizon in horizons:
            fold_reports, oof = self._run_horizon_folds(rows, features, horizon, folds, iterations, seed, use_lstm_garch, resume, threshold_mode)
            report["horizons"][horizon] = {"folds": fold_reports, "aggregate": _aggregate_metrics(oof, horizon)}
            report["horizons"][horizon]["sentiment_filtered_aggregate"] = _aggregate_metrics(oof, horizon, active_mask=[bool(row.get("sentiment_active", True)) for row in oof])
            self._fit_final(final_rows, features, horizon, iterations, seed)
        self._manifest_path().write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8")
        return report

    def _run_horizon_folds(self, rows, features, horizon, folds, iterations, seed, use_lstm_garch, resume, threshold_mode):
        from catboost import CatBoostClassifier, Pool
        import pandas as pd

        reports, oof = [], []
        for fold_id, (train_end, validation_dates) in enumerate(folds, start=1):
            checkpoint_path = self._checkpoint_path(horizon, fold_id)
            expected = {"train_end": train_end, "validation_start": validation_dates[0], "validation_end": validation_dates[-1], "iterations": iterations, "seed": seed, "features": features, "lstm_garch": use_lstm_garch, "threshold_mode": threshold_mode}
            cached = _load_fold_checkpoint(checkpoint_path, expected) if resume else None
            if cached is not None:
                reports.append({"fold": fold_id, "resumed": True, **cached["metrics"]})
                oof.extend(cached["oof"])
                continue
            train_rows = [row for row in rows if str(row["decision_date"]) <= train_end]
            validation_set = set(validation_dates)
            validation_rows = [row for row in rows if str(row["decision_date"]) in validation_set]
            if not train_rows or not validation_rows:
                continue
            if use_lstm_garch:
                hybrid_path = self._hybrid_checkpoint_path(train_rows, train_end, seed)
                hybrid = LSTMGarchResidualModel.load(hybrid_path)
                if hybrid is None:
                    hybrid = LSTMGarchResidualModel(seed=seed).fit(train_rows)
                    hybrid.save(hybrid_path)
                all_predictions = hybrid.predict([*train_rows, *validation_rows])
                train_rows = _with_lstm_feature(train_rows, all_predictions)
                validation_rows = _with_lstm_feature(validation_rows, all_predictions)
            train_df, validation_df = pd.DataFrame(train_rows), pd.DataFrame(validation_rows)
            model = CatBoostClassifier(iterations=iterations, depth=6, learning_rate=0.05, verbose=False, allow_writing_files=False, random_seed=seed, loss_function="Logloss")
            model.fit(Pool(train_df[features], train_df[f"y_{horizon}"].astype(int), cat_features=[features.index(name) for name in FORTUNE_CATEGORICAL_FEATURES if name in features]))
            probability = model.predict_proba(validation_df[features])[:, 1]
            threshold = _training_quantile_threshold(model, train_df, features, horizon) if threshold_mode == "train_quantile" else 0.5
            predictions = (probability >= threshold).astype(int)
            rows_out = [
                {
                    "date": str(row["decision_date"]), "prediction": int(pred), "probability": float(prob),
                    "label": int(row[f"y_{horizon}"]), "forward_return": float(row[f"forward_return_{horizon}"]),
                    "sentiment_active": _sentiment_active(row),
                }
                for row, pred, prob in zip(validation_rows, predictions, probability)
            ]
            oof.extend(rows_out)
            metrics = _aggregate_metrics(rows_out, horizon)
            report = {"fold": fold_id, "resumed": False, "threshold": float(threshold), "train_end": train_end, "validation_start": validation_dates[0], "validation_end": validation_dates[-1], **metrics}
            reports.append(report)
            _write_fold_checkpoint(checkpoint_path, expected, metrics=report, oof=rows_out)
        return reports, oof

    def _fit_final(self, rows, features, horizon, iterations, seed) -> None:
        from catboost import CatBoostClassifier, Pool
        import pandas as pd

        frame = pd.DataFrame(rows)
        model = CatBoostClassifier(iterations=iterations, depth=6, learning_rate=0.05, verbose=False, allow_writing_files=False, random_seed=seed, loss_function="Logloss")
        model.fit(Pool(frame[features], frame[f"y_{horizon}"].astype(int), cat_features=[features.index(name) for name in FORTUNE_CATEGORICAL_FEATURES if name in features]))
        model.save_model(str(self._model_path(horizon)))


def _num(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def _training_quantile_threshold(model, train_df, features: list[str], horizon: str) -> float:
    """Choose a cutoff from training-fold prevalence only."""
    probability = model.predict_proba(train_df[features])[:, 1]
    positive_rate = float(np.mean(train_df[f"y_{horizon}"].astype(int)))
    threshold = float(np.quantile(probability, max(0.0, min(1.0, 1.0 - positive_rate))))
    return threshold if np.isfinite(threshold) else 0.5


def _with_lstm_feature(rows: list[Mapping[str, Any]], predictions: Mapping[tuple[str, str], float]) -> list[dict[str, Any]]:
    return [{**row, LSTM_GARCH_FEATURE: predictions.get((str(row.get("symbol", "")), str(row.get("decision_date", ""))), float("nan"))} for row in rows]


def _usable_features(rows: list[Mapping[str, Any]]) -> list[str]:
    selected: list[str] = []
    for feature in FORTUNE_ENHANCED_FEATURES:
        if feature == "symbol":
            selected.append(feature)
            continue
        values = np.asarray([_num(row.get(feature)) for row in rows], dtype=float)
        finite = values[np.isfinite(values)]
        if len(finite) >= 20 and float(np.nanstd(finite)) > 1e-12:
            selected.append(feature)
    return selected


def _expanding_folds(dates: list[str], *, n_folds: int, purge_sessions: int) -> list[tuple[str, list[str]]]:
    start_train = max(60, len(dates) // (n_folds + 2))
    remaining = len(dates) - start_train - purge_sessions
    width = max(1, remaining // n_folds)
    folds: list[tuple[str, list[str]]] = []
    for fold in range(n_folds):
        validation_start = start_train + purge_sessions + fold * width
        validation_end = min(validation_start + width, len(dates))
        if validation_start >= validation_end:
            break
        train_end_index = validation_start - purge_sessions - 1
        if train_end_index < 0:
            continue
        folds.append((dates[train_end_index], dates[validation_start:validation_end]))
    return folds


def _aggregate_metrics(rows: list[Mapping[str, Any]], horizon: str, active_mask: list[bool] | None = None) -> dict[str, Any]:
    total_count = len(rows)
    if active_mask is not None:
        rows = [row for row, active in zip(rows, active_mask) if active]
    if not rows:
        return {"sample_count": 0, "coverage": 0.0}
    labels = np.asarray([int(row["label"]) for row in rows])
    predictions = np.asarray([int(row["prediction"]) for row in rows])
    probability = np.asarray([float(row["probability"]) for row in rows])
    returns = np.asarray([float(row["forward_return"]) for row in rows])
    directional = float(np.mean(labels == predictions))
    base = float(max(np.mean(labels), 1.0 - np.mean(labels)))
    pnl = np.where(predictions == 1, returns, -returns)
    by_date: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    for row, value, probability_value, forward_return in zip(rows, pnl, probability, returns):
        by_date[str(row["date"])].append((float(value), float(probability_value), float(forward_return)))
    dated = sorted(by_date.items())
    portfolio = np.asarray([np.mean([value[0] for value in values]) for _, values in dated])
    sharpe = float(np.mean(portfolio) / np.std(portfolio, ddof=1) * sqrt(252 / max(1, _HORIZON_DAYS[horizon]))) if len(portfolio) > 1 and np.std(portfolio, ddof=1) > 1e-12 else 0.0
    equity = np.cumprod(1.0 + portfolio) if len(portfolio) else np.array([1.0])
    drawdown = float(np.min(equity / np.maximum.accumulate(equity) - 1.0)) if len(equity) else 0.0
    try:
        from scipy.stats import spearmanr
        rank_ic = float(spearmanr(probability, returns).statistic)
    except Exception:  # pragma: no cover
        rank_ic = 0.0
    quantiles = np.quantile(probability, [0.2, 0.4, 0.6, 0.8])
    groups = np.digitize(probability, quantiles, right=True)
    group_returns = [float(np.mean(returns[groups == group])) if np.any(groups == group) else None for group in range(5)]
    equity_values = np.cumprod(1.0 + portfolio) if len(portfolio) else np.array([])
    pnl_curve = [
        {"date": day, "return": float(portfolio[index]), "equity": float(equity_values[index])}
        for index, (day, _) in enumerate(dated)
    ]
    daily_ic: list[dict[str, Any]] = []
    for day, values in dated:
        day_probability = [value[1] for value in values]
        day_returns = [value[2] for value in values]
        if len(day_probability) < 3 or len(set(day_probability)) < 2 or len(set(day_returns)) < 2:
            continue
        try:
            from scipy.stats import spearmanr
            value = float(spearmanr(day_probability, day_returns).statistic)
        except Exception:  # pragma: no cover
            continue
        if np.isfinite(value):
            daily_ic.append({"date": day, "rank_ic": value})
    return {
        "sample_count": int(len(rows)),
        "coverage": float(len(rows) / max(1, total_count)),
        "directional_accuracy": directional,
        "base_rate": base,
        "edge": directional - base,
        "rank_ic": rank_ic if np.isfinite(rank_ic) else 0.0,
        "sharpe_proxy": sharpe,
        "max_drawdown_proxy": drawdown,
        "group_mean_forward_returns": group_returns,
        "group_monotonic": bool(all(left is not None and right is not None and left <= right for left, right in zip(group_returns, group_returns[1:]))),
        "pnl_curve": pnl_curve,
        "daily_rank_ic": daily_ic,
        "rank_ic_mean_by_date": float(np.mean([item["rank_ic"] for item in daily_ic])) if daily_ic else 0.0,
        "rank_ic_ir_by_date": float(np.mean([item["rank_ic"] for item in daily_ic]) / np.std([item["rank_ic"] for item in daily_ic], ddof=1)) if len(daily_ic) > 1 and np.std([item["rank_ic"] for item in daily_ic], ddof=1) > 1e-12 else 0.0,
    }


def _sentiment_active(row: Mapping[str, Any]) -> bool:
    """Disable risk-taking only in a confirmed bear + elevated-volatility state.

    It is intentionally a transparent execution filter, not a new label or a
    mutation of model probability.  Missing HMM values remain eligible so
    early history is not silently deleted from the raw comparison.
    """
    bear = _num(row.get("hmm_bear_probability"))
    regime = _num(row.get("hmm_regime"))
    volatility_ratio = _num(row.get("garch_vol_ratio_20"))
    if np.isfinite(bear) and np.isfinite(regime) and bear >= 0.55 and regime < 0:
        return False
    return not (np.isfinite(volatility_ratio) and volatility_ratio > 3.0 and np.isfinite(regime) and regime < 0)


def _load_fold_checkpoint(path: Path, expected: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("schema_version") != "fortune-enhanced-fold-v1" or payload.get("context") != dict(expected):
        return None
    if not isinstance(payload.get("metrics"), dict) or not isinstance(payload.get("oof"), list):
        return None
    return payload


def _write_fold_checkpoint(path: Path, context: Mapping[str, Any], *, metrics: Mapping[str, Any], oof: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "fortune-enhanced-fold-v1", "context": dict(context), "metrics": dict(metrics), "oof": list(oof)}, ensure_ascii=False, allow_nan=True), encoding="utf-8")
