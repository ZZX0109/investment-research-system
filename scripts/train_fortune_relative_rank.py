#!/usr/bin/env python3
"""Train a Fortune feature candidate on cross-sectional relative returns.

The original direction target is dominated by the market-wide up/down state.
This candidate predicts each stock's forward return minus the same-date
cross-sectional mean, then evaluates ranking and long-short behaviour.
"""
from __future__ import annotations

import argparse
import json
from math import sqrt
from pathlib import Path

import numpy as np

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.training.short_term.fortune_enhanced_horizon_runner import (
    HORIZONS,
    _expanding_folds,
    _num,
    _usable_features,
    FORTUNE_CATEGORICAL_FEATURES,
    FortuneEnhancedHorizonRunner,
)


def _metrics(rows: list[dict], horizon: str) -> dict:
    if not rows:
        return {"sample_count": 0}
    from scipy.stats import spearmanr

    actual = np.asarray([float(row["forward_return"]) for row in rows])
    prediction = np.asarray([float(row["prediction"]) for row in rows])
    date_groups: dict[str, list[dict]] = {}
    for row in rows:
        date_groups.setdefault(str(row["date"]), []).append(row)
    daily_ls: list[float] = []
    groups: list[list[float]] = [[] for _ in range(5)]
    for values in date_groups.values():
        if len(values) < 5:
            continue
        ordered = sorted(values, key=lambda row: float(row["prediction"]))
        width = max(1, len(ordered) // 5)
        for group in range(5):
            sample = ordered[group * width:(group + 1) * width] if group < 4 else ordered[group * width:]
            groups[group].append(float(np.mean([row["forward_return"] for row in sample])))
        bottom = np.mean([row["forward_return"] for row in ordered[:width]])
        top = np.mean([row["forward_return"] for row in ordered[-width:]])
        daily_ls.append(float(top - bottom))
    portfolio = np.asarray(daily_ls, dtype=float)
    equity = np.cumprod(1.0 + portfolio) if len(portfolio) else np.array([])
    sharpe = float(np.mean(portfolio) / np.std(portfolio, ddof=1) * sqrt(252 / max(1, {"1d": 1, "5d": 5, "20d": 20}[horizon]))) if len(portfolio) > 1 and np.std(portfolio, ddof=1) > 1e-12 else 0.0
    drawdown = float(np.min(equity / np.maximum.accumulate(equity) - 1.0)) if len(equity) else 0.0
    ic = float(spearmanr(prediction, actual).statistic) if len(set(prediction)) > 1 and len(set(actual)) > 1 else 0.0
    group_means = [float(np.mean(values)) if values else None for values in groups]
    return {
        "sample_count": len(rows), "decision_count": len(date_groups),
        "rank_ic": ic if np.isfinite(ic) else 0.0,
        "sharpe_long_short": sharpe, "max_drawdown_long_short": drawdown,
        "top_minus_bottom_mean_return": float(np.mean(portfolio)) if len(portfolio) else 0.0,
        "group_mean_forward_returns": group_means,
        "group_monotonic": bool(all(a is not None and b is not None and a <= b for a, b in zip(group_means, group_means[1:]))),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=12)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--feature-workers", type=int, default=10)
    parser.add_argument("--max-symbols", type=int, default=None)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output_root = root / "artifacts/short_term/fortune_relative_rank"
    output_root.mkdir(parents=True, exist_ok=True)
    uow = SQLiteUnitOfWork(get_default_database_path())
    try:
        symbols = [row[0] for row in uow.connection.execute("SELECT DISTINCT symbol FROM versioned_market_bars WHERE interval='1d' ORDER BY symbol")]
        if args.max_symbols:
            symbols = symbols[:args.max_symbols]
        runner = FortuneEnhancedHorizonRunner(root, candidate_name="fortune_relative_rank")
        rows = runner.build_dataset(uow.trusted_market, symbols, feature_workers=args.feature_workers)
    finally:
        uow.close()
    if len(rows) < 200:
        return 2
    for horizon in HORIZONS:
        by_date: dict[str, list[dict]] = {}
        for row in rows:
            by_date.setdefault(str(row["decision_date"]), []).append(row)
        relative_rows = []
        for row in rows:
            same_date = by_date[str(row["decision_date"])]
            market_mean = float(np.mean([x[f"forward_return_{horizon}"] for x in same_date]))
            relative_rows.append({**row, "target": float(row[f"forward_return_{horizon}"]) - market_mean})
        dates = sorted(by_date)
        folds = _expanding_folds(dates, n_folds=args.folds, purge_sessions=20)
        all_oof: list[dict] = []
        fold_reports = []
        for fold_id, (train_end, validation_dates) in enumerate(folds, start=1):
            checkpoint = output_root / f"{horizon}_fold_{fold_id}.json"
            context = {"train_end": train_end, "validation_start": validation_dates[0], "validation_end": validation_dates[-1], "iterations": args.iterations}
            if checkpoint.exists():
                try:
                    cached = json.loads(checkpoint.read_text())
                    if cached.get("context") == context:
                        fold_reports.append(cached["metrics"]); all_oof.extend(cached["oof"]); continue
                except (OSError, ValueError, KeyError):
                    pass
            train_rows = [row for row in relative_rows if str(row["decision_date"]) <= train_end]
            valid_rows = [row for row in relative_rows if str(row["decision_date"]) in set(validation_dates)]
            features = _usable_features(train_rows)
            import pandas as pd
            from catboost import CatBoostRegressor, Pool
            train_df, valid_df = pd.DataFrame(train_rows), pd.DataFrame(valid_rows)
            model = CatBoostRegressor(iterations=args.iterations, depth=6, learning_rate=0.05, loss_function="RMSE", verbose=False, allow_writing_files=False, random_seed=42)
            model.fit(Pool(train_df[features], train_df["target"], cat_features=[features.index(name) for name in FORTUNE_CATEGORICAL_FEATURES if name in features]))
            prediction = model.predict(valid_df[features])
            oof = [{"date": str(row["decision_date"]), "prediction": float(pred), "forward_return": float(row[f"forward_return_{horizon}"])} for row, pred in zip(valid_rows, prediction)]
            metrics = {"fold": fold_id, **_metrics(oof, horizon)}
            checkpoint.write_text(json.dumps({"schema_version": "fortune-relative-fold-v1", "context": context, "metrics": metrics, "oof": oof}, allow_nan=True), encoding="utf-8")
            fold_reports.append(metrics); all_oof.extend(oof)
        report = {"status": "ok", "schema_version": "fortune-relative-rank-v1", "n_rows": len(rows), "n_folds": len(folds), "features": _usable_features(relative_rows), "horizons": {horizon: {"folds": fold_reports, "aggregate": _metrics(all_oof, horizon)}}}
        (output_root / f"{horizon}_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8")
    print(json.dumps({"status": "ok", "rows": len(rows), "output": str(output_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
