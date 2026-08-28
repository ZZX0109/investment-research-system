"""§4 / Step-4 quick enriched retrain (round 32) — does adding the round-25 DB
fundamentals to price features improve the long-term model's rank_ic?

This is a PRELIMINARY check (NOT the formal purged walk-forward pipeline): it
builds a panel from the universe's real daily bars + the seeded fundamental
line_items, fits a LightGBM on the excess_return_240d target, and reports the
holdout rank_ic — with vs without the fundamental features — so the
"训练说清楚" question (does enrichment help?) gets a concrete, honest answer.

Usage::
    NODE_ENV=development python3 -m scripts.retrain_long_term_enriched
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path

log = logging.getLogger("enriched_retrain")
_HORIZON = 240  # 240-trading-day forward excess return (the long-term task)


def _load_panel(uow: SQLiteUnitOfWork) -> pd.DataFrame:
    """Per-symbol daily OHLCV (via the repo's active_bars, which decodes the
    payload_json) + the latest fundamental line_items (round-25 seed)."""
    repo = uow.trusted_market
    cur = uow.connection.cursor()
    cur.execute("SELECT DISTINCT symbol FROM versioned_market_bars ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]
    cur.close()
    rows: list[dict] = []
    for sym in symbols:
        bars = repo.active_bars(sym, "1d")
        bars.sort(key=lambda b: b.bar_start)
        for b in bars:
            rows.append({"symbol": sym, "trade_date": b.trade_date, "close": b.close, "volume": getattr(b, "volume", 0.0) or 0.0})
    bars = pd.DataFrame(rows)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    # fundamentals: one row per symbol (latest line_items, round-25 seed)
    cur = uow.connection.cursor()
    cur.execute(
        """SELECT symbol, metric, json_extract(payload_json, '$.value') AS value
           FROM financial_line_items
           WHERE metric IN ('roe','roa','net_margin','operating_profit','revenue','net_profit','gross_margin')
             AND status='active'"""
    )
    fis = cur.fetchall()
    cur.close()
    if fis:
        fi = pd.DataFrame(fis, columns=["symbol", "metric", "value"])
        fi["value"] = pd.to_numeric(fi["value"], errors="coerce")
        fi = fi.groupby(["symbol", "metric"])["value"].mean().unstack("metric").reset_index()
        bars = bars.merge(fi, on="symbol", how="left")
    else:
        for c in ("roe", "roa", "net_margin", "operating_profit", "revenue", "net_profit", "gross_margin"):
            bars[c] = np.nan
    return bars


def _features(df: pd.DataFrame, *, with_fund: bool) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Engineer price (+ optional fundamental) features + the 240d forward excess
    return target. Excess return = symbol return - equal-weight universe return."""
    g = df.sort_values(["symbol", "trade_date"]).copy()
    g["ret_1d"] = g.groupby("symbol")["close"].pct_change(1)
    g["ret_5d"] = g.groupby("symbol")["close"].pct_change(5)
    g["ret_20d"] = g.groupby("symbol")["close"].pct_change(20)
    g["ret_60d"] = g.groupby("symbol")["close"].pct_change(60)
    g["vol_20d"] = g.groupby("symbol")["ret_1d"].transform(lambda s: s.rolling(20).std())
    g["vol_ratio_5d"] = g["volume"] / g.groupby("symbol")["volume"].transform(lambda s: s.rolling(5).mean())
    g["ma_5_ratio"] = g["close"] / g.groupby("symbol")["close"].transform(lambda s: s.rolling(5).mean())
    g["ma_20_ratio"] = g["close"] / g.groupby("symbol")["close"].transform(lambda s: s.rolling(20).mean())
    # 240d forward return
    g["fwd_240d"] = g.groupby("symbol")["close"].pct_change(_HORIZON).shift(-_HORIZON)
    # equal-weight universe return per date (benchmark for excess)
    uni = g.groupby("trade_date")["ret_1d"].mean()
    g["uni_fwd_240d"] = g["trade_date"].map(uni).rolling(_HORIZON).sum().shift(-_HORIZON)
    g["excess_240d"] = g["fwd_240d"] - g["uni_fwd_240d"]
    feat_price = ["ret_1d", "ret_5d", "ret_20d", "ret_60d", "vol_20d", "vol_ratio_5d", "ma_5_ratio", "ma_20_ratio"]
    feat_fund = ["roe", "roa", "net_margin", "operating_margin", "gross_margin"] if with_fund else []
    # operating_margin ≈ operating_profit/revenue (engineered)
    if with_fund:
        g["operating_margin"] = np.where(g["revenue"] > 0, g["operating_profit"] / g["revenue"], np.nan)
    feats = feat_price + feat_fund
    g = g.dropna(subset=["excess_240d"] + feat_price)
    # sample one row per symbol per MONTH (decision dates) to avoid leakage clustering
    g["ym"] = g["trade_date"].dt.to_period("M")
    panel = g.groupby(["symbol", "ym"]).last().reset_index()
    X = panel[feats].copy()
    # fill NaN fundamentals with the cross-sectional median (so the model sees them)
    X = X.fillna(X.median())
    y = panel["excess_240d"].astype(float)
    return X, y, panel["symbol"]


def _rank_ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    s = pd.Series(y_pred).rank()
    t = pd.Series(y_true).rank()
    return float(s.corr(t))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    import lightgbm as lgb

    uow = SQLiteUnitOfWork(get_default_database_path())
    df = _load_panel(uow)
    uow.close()
    n_sym = df["symbol"].nunique()
    n_bars = len(df)
    has_fund = df["roe"].notna().any()
    log.info("panel: %d symbols, %d bars, fundamentals present=%s", n_sym, n_bars, has_fund)
    if n_bars < 1000:
        print(json.dumps({"status": "no_data", "n_bars": n_bars}))
        return 1
    # time split: last 20% of decision dates → holdout
    results = {}
    for label, with_fund in (("price_only", False), ("enriched", True)):
        X, y, _ = _features(df, with_fund=with_fund)
        if len(X) < 200:
            results[label] = {"status": "no_data", "n": len(X)}
            continue
        cut = int(len(X) * 0.8)
        X_tr, X_va = X.iloc[:cut], X.iloc[cut:]
        y_tr, y_va = y.iloc[:cut], y.iloc[cut:]
        model = lgb.LGBMRegressor(
            objective="regression", n_estimators=200, learning_rate=0.05,
            num_leaves=31, min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbose=-1, n_jobs=4,
        )
        model.fit(X_tr, y_tr)
        pred_va = model.predict(X_va)
        ric = _rank_ic(y_va.values, pred_va)
        # feature importance (top 5)
        fi = dict(zip(X.columns, model.feature_importances_))
        top5 = sorted(fi.items(), key=lambda kv: -kv[1])[:5]
        results[label] = {
            "status": "ok", "n_train": len(X_tr), "n_val": len(X_va),
            "rank_ic": round(ric, 4), "passes_0.10": ric > 0.10,
            "top_features": [{"name": n, "importance": int(i)} for n, i in top5],
        }
        log.info("%s: rank_ic=%.4f n_val=%d", label, ric, len(X_va))
    delta = None
    if results.get("price_only", {}).get("rank_ic") is not None and results.get("enriched", {}).get("rank_ic") is not None:
        delta = round(results["enriched"]["rank_ic"] - results["price_only"]["rank_ic"], 4)
    out = {"status": "ok", "horizon_days": _HORIZON, "n_symbols": int(n_sym), "results": results, "enrichment_delta_rank_ic": delta}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    Path("artifacts/model_performance/enriched_retrain_round32.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
