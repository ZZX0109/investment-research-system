#!/usr/bin/env python3
"""Factor-evaluation diagnostics for the optimized panel model.

Answers 'how good is rank_ic=0.1533?' with a full holdout diagnostic suite, and
compares the optimized model (price+fund_rich+event) against the price-only
baseline on EVERY metric so the improvement is judged on robustness, not a single
number.

Metrics (all on the 20% time holdout, 240d forward excess return target):
  * rank_ic        : Spearman rank corr(pred, actual)        — single-number signal
  * IC IR           : mean(quarterly rank_ic) / std          — stability (a good factor > 0.5)
  * decile L/S spread : top-decile mean - bottom-decile mean realized excess return per period, averaged
  * top-decile hit   : fraction of periods where top decile excess return > 0
  * monotonicity     : Spearman(decile_rank, decile_mean_return) per period, averaged (1.0 = perfect monotone)
  * per-year rank_ic  : stability across holdout years
  * top-decile annualized spread (rough): spread * (252/240)

Usage: python3 scripts/eval_diagnostics.py
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import panel_eval as pe  # reuse assemble_panel, PRICE_FEATS, DB, rank_ic

log = logging.getLogger("diag")


def train_get_preds(panel, feats, label, split_mode="symbol"):
    """split_mode='symbol' = cross-sectional (matches round-32 baseline: panel sorted
    by (symbol,ym) then iloc 80/20 -> holdout = unseen symbols, same period).
    split_mode='time' = temporal: sort by trade_date -> holdout = latest 20% period
    (honest out-of-sample-in-time; limited by 240d forward target + data end)."""
    import lightgbm as lgb
    p = panel.copy()
    if split_mode == "time":
        p = p.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    X = p[feats].copy().fillna(p[feats].median()).fillna(0.0)
    y = p["excess_240d"].astype(float)
    cut = int(len(X) * 0.8)
    X_tr, X_va = X.iloc[:cut], X.iloc[cut:]
    y_tr, y_va = y.iloc[:cut], y.iloc[cut:]
    meta = p.iloc[cut:][["symbol", "trade_date", "excess_240d"]].copy()
    m = lgb.LGBMRegressor(objective="regression", n_estimators=200, learning_rate=0.05,
                          num_leaves=31, min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
                          random_state=42, verbose=-1, n_jobs=4)
    m.fit(X_tr, y_tr)
    pred = m.predict(X_va)
    meta["pred"] = pred
    meta["y"] = y_va.values
    return meta, pe.rank_ic(y_va.values, pred)


def per_period_ic(df, freq="Q"):
    """rank_ic computed per time period (quarter) -> series for IC IR."""
    df = df.copy()
    df["p"] = df["trade_date"].dt.to_period(freq)
    out = []
    for _, g in df.groupby("p"):
        if len(g) >= 5:
            out.append({"period": str(_), "n": len(g), "rank_ic": pe.rank_ic(g["y"].values, g["pred"].values)})
    return pd.DataFrame(out)


def decile_diagnostics(df):
    """per-period decile long-short spread, top-decile hit, monotonicity."""
    df = df.copy()
    df["p"] = df["trade_date"].dt.to_period("Q")
    spreads, hits, monos, n_periods = [], [], [], 0
    for _, g in df.groupby("p"):
        if len(g) < 20:
            continue
        n_periods += 1
        g = g.sort_values("pred")
        g["dec"] = pd.qcut(g["pred"].rank(method="first"), 10, labels=False)
        dmean = g.groupby("dec")["y"].mean()
        spread = dmean.iloc[-1] - dmean.iloc[0]  # top - bottom
        spreads.append(spread)
        hits.append(1 if dmean.iloc[-1] > 0 else 0)
        monos.append(float(pd.Series(dmean.values).rank().corr(pd.Series(dmean.index.values).rank())))
    return {
        "n_periods": n_periods,
        "mean_decile_spread": round(float(np.mean(spreads)), 4) if spreads else None,
        "top_decile_hit_rate": round(float(np.mean(hits)), 3) if hits else None,
        "mean_monotonicity": round(float(np.mean(monos)), 3) if monos else None,
    }


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    conn = sqlite3.connect(str(pe.DB), timeout=60.0)
    panel, blocks = pe.assemble_panel(conn, None, 0)
    conn.close()
    print(f"[diag] panel rows={len(panel)} symbols={panel['symbol'].nunique()} blocks={ {k:len(v) for k,v in blocks.items()} }", flush=True)

    feats_opt = blocks["price"] + blocks.get("fund_rich", []) + blocks.get("event", [])
    feats_base = blocks["price"]
    res = {}
    for split_mode in ("symbol", "time"):
        for label, feats in (("price_baseline", feats_base), ("optimized_price_fund_rich_event", feats_opt)):
            hold, overall_ic = train_get_preds(panel, feats, label, split_mode)
            perq = per_period_ic(hold, "Q")
            dec = decile_diagnostics(hold)
            hold["year"] = hold["trade_date"].dt.year
            pery = []
            for y, g in hold.groupby("year"):
                if len(g) >= 5:
                    pery.append({"year": int(y), "n": len(g), "rank_ic": round(pe.rank_ic(g["y"].values, g["pred"].values), 4)})
            ic_mean = float(perq["rank_ic"].mean()) if len(perq) else float("nan")
            ic_std = float(perq["rank_ic"].std()) if len(perq) else float("nan")
            key = f"{label}__split_{split_mode}"
            res[key] = {
                "split": split_mode, "n_holdout": len(hold), "overall_rank_ic": round(overall_ic, 4),
                "ic_ir_quarterly": round(ic_mean / ic_std, 3) if ic_std else None,
                "quarterly_ic_mean": round(ic_mean, 4), "quarterly_ic_std": round(ic_std, 4),
                "quarterly_n_periods": len(perq),
                "quarterly_ic_min": round(float(perq["rank_ic"].min()), 4) if len(perq) else None,
                "quarterly_ic_max": round(float(perq["rank_ic"].max()), 4) if len(perq) else None,
                "decile_ls_spread": dec["mean_decile_spread"],
                "top_decile_hit_rate": dec["top_decile_hit_rate"],
                "decile_monotonicity": dec["mean_monotonicity"],
                "holdout_date_range": [str(hold["trade_date"].min().date()), str(hold["trade_date"].max().date())],
                "per_year_rank_ic": pery,
            }
    out = {"status": "ok", "models": res}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    outdir = pe.PROJECT / "artifacts/model_performance"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "panel_eval_diagnostics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
