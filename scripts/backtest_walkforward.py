#!/usr/bin/env python3
"""Production validation gate: purged walk-forward + cost-adjusted top-k backtest.

rank_ic != strategy return. This turns the rank_ic=0.1533 model into a realistic
monthly long-only top-k strategy and tests it out-of-sample-in-time with:
  * PURGED walk-forward: retrain quarterly on an expanding window; the train cutoff is
    pushed back by the 240d label horizon so a test month's training data never uses a
    label whose 240d forward window overlaps the test month (label-leakage purge).
  * COST-ADJUSTED: each monthly rebalance pays turnover * round-trip cost on changed
    positions (CN ~15bps). Net excess return = gross top-k excess - cost.
  * Metrics: cumulative net excess, annualized, Sharpe, max drawdown, monthly win rate.

Best blocks (price+fund_rich+event) from panel_eval.assemble_panel.

Usage: python3 scripts/backtest_walkforward.py --top-k 10 --cost-bps 15
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

import panel_eval as pe

log = logging.getLogger("bt")
HORIZON = 240


def monthly_excess_returns(bars: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, month-end) 1-month excess return = symbol 1m ret - equal-weight univ 1m ret."""
    g = bars.sort_values(["symbol", "trade_date"]).copy()
    g["ret_1d"] = g.groupby("symbol")["close"].pct_change(1)
    g["ym"] = g["trade_date"].dt.to_period("M")
    # month-end close per symbol
    me = g.groupby(["symbol", "ym"]).agg(close_me=("close", "last"), trade_date=("trade_date", "last")).reset_index()
    me["next_close_me"] = me.groupby("symbol")["close_me"].shift(-1)
    me["ret_1m"] = (me["next_close_me"] / me["close_me"]) - 1.0
    uni_1m = me.groupby("ym")["ret_1m"].mean().rename("uni_1m")
    me = me.join(uni_1m, on="ym")
    me["excess_1m"] = me["ret_1m"] - me["uni_1m"]
    me = me.dropna(subset=["excess_1m"])
    me["trade_date"] = pd.to_datetime(me["trade_date"])
    return me[["symbol", "trade_date", "ym", "excess_1m"]]


def train_predict(train_df, test_df, feats):
    import lightgbm as lgb
    Xtr = train_df[feats].fillna(train_df[feats].median()).fillna(0.0)
    ytr = train_df["excess_240d"].astype(float)
    Xte = test_df[feats].fillna(train_df[feats].median()).fillna(0.0)
    m = lgb.LGBMRegressor(objective="regression", n_estimators=200, learning_rate=0.05,
                          num_leaves=31, min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
                          random_state=42, verbose=-1, n_jobs=4)
    m.fit(Xtr, ytr)
    return m.predict(Xte)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--cost-bps", type=float, default=15.0, help="round-trip cost per unit turnover (bps)")
    p.add_argument("--retrain-quarters", type=int, default=1, help="retrain every N months")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    conn = sqlite3.connect(str(pe.DB), timeout=60.0)
    panel, blocks = pe.assemble_panel(conn, None, 0)
    bars = pe.load_bars(conn)
    conn.close()
    feats = blocks["price"] + blocks.get("fund_rich", []) + blocks.get("event", [])
    mer = monthly_excess_returns(bars)
    # merge monthly excess onto panel decision rows by (symbol, month) — use the month-end date
    panel = panel.sort_values("trade_date").reset_index(drop=True)
    panel["ym"] = panel["trade_date"].dt.to_period("M")
    panel = panel.merge(mer[["symbol", "ym", "excess_1m"]], on=["symbol", "ym"], how="left")
    panel = panel.dropna(subset=["excess_1m"] + feats + ["excess_240d"])
    panel = panel.sort_values("trade_date").reset_index(drop=True)
    # walk-forward: for each test month, train on rows with trade_date <= test_start - 240 trading days
    dates = panel["trade_date"].drop_duplicates().sort_values().reset_index(drop=True)
    purge_td = pd.Timedelta(days=int(HORIZON * 1.5))  # 240 trading days ~ 360 calendar days, pad
    months = sorted(panel["ym"].unique())
    cost = args.cost_bps / 1e4
    test_ys = [m for m in months if str(m) >= "2021"]  # start OOS from 2021 (need prior train)
    log.info("test months=%d top-k=%d cost=%.4f", len(test_ys), args.top_k, cost)
    rows = []
    prev_top = set()
    train_cache = {}
    for i, ym in enumerate(test_ys):
        test = panel[panel["ym"] == ym].sort_values("trade_date")
        if test.empty:
            continue
        t_start = test["trade_date"].min()
        train_cutoff = t_start - purge_td
        train = panel[panel["trade_date"] <= train_cutoff]
        if len(train) < 300:
            continue
        if i % args.retrain_quarters == 0 or "pred" not in test.columns:
            pred = train_predict(train, test, feats)
            test = test.copy()
            test["pred"] = pred
        else:
            # reuse last model predictions if available (skip); simpler: retrain each
            pred = train_predict(train, test, feats)
            test = test.copy()
            test["pred"] = pred
        # rank, pick top-k by pred
        test = test.sort_values("pred", ascending=False)
        top = test.head(args.top_k)
        if len(top) < args.top_k:
            continue
        gross_excess = top["excess_1m"].mean()
        cur_top = set(top["symbol"])
        turnover = len(cur_top - prev_top) / args.top_k if prev_top else 1.0
        net_excess = gross_excess - turnover * cost
        rows.append({"ym": str(ym), "n": len(top), "gross_excess": gross_excess,
                     "turnover": turnover, "net_excess": net_excess,
                     "top_avg_pred": float(top["pred"].mean())})
        prev_top = cur_top
    if not rows:
        print(json.dumps({"status": "no_test"})); return 1
    r = pd.DataFrame(rows)
    cum = (1 + r["net_excess"]).cumprod().iloc[-1] - 1
    n_months = len(r)
    ann = (1 + cum) ** (12 / n_months) - 1 if n_months else 0
    sharpe = float(r["net_excess"].mean() / r["net_excess"].std() * (12 ** 0.5)) if r["net_excess"].std() else 0
    # max drawdown on cumulative net excess series
    eq = (1 + r["net_excess"]).cumprod()
    mdd = float((eq / eq.cummax() - 1).min())
    out = {
        "status": "ok", "top_k": args.top_k, "cost_bps": args.cost_bps,
        "n_test_months": n_months, "test_range": [r["ym"].iloc[0], r["ym"].iloc[-1]],
        "cumulative_net_excess": round(float(cum), 4),
        "annualized_net_excess": round(float(ann), 4),
        "monthly_sharpe": round(sharpe, 3),
        "max_drawdown": round(mdd, 4),
        "monthly_win_rate": round(float((r["net_excess"] > 0).mean()), 3),
        "mean_turnover": round(float(r["turnover"].mean()), 3),
        "mean_gross_excess": round(float(r["gross_excess"].mean()), 4),
        "per_month": rows,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    outdir = pe.PROJECT / "artifacts/model_performance"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "backtest_walkforward.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
