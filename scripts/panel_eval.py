#!/usr/bin/env python3
"""Standalone enriched panel builder + rank_ic evaluator (event + sentiment).

Self-contained (sqlite3 + pandas + lightgbm only — no investment_research
package import) so it runs on the GPU pod with the synced DB.  It replicates the
round-32 ``retrain_long_term_enriched`` panel EXACTLY for the price + legacy-fund
blocks (so the baseline rank_ic is comparable), then layers new blocks:

  price        : ret_1d/5d/20d/60d, vol_20d, vol_ratio_5d, ma_5_ratio, ma_20_ratio
  fund_legacy  : roe/roa/net_margin/operating_margin/gross_margin  (financial_line_items, static per symbol — the round-32 enriched block)
  fund_rich    : PIT-asof fundamentals from event_financial_actual (162 symbols × 11 metrics back to 1989): roe, net_margin, gross_margin, eps, np_yoy, rev_yoy, np_level
  event        : earnings surprise (actual annual EPS − consensus EPS snapshot; caveat: consensus is current-snapshot, aligned at annual-report disclosure), eps_yoy, notice-type counts + intensity in trailing 30/90d (增减持/回购/问询函/...)
  sentiment    : BERT [CLS] daily mean-pool per symbol, most-recent-past at decision date (added later)

Target: 240-trading-day forward EXCESS return (= symbol fwd return − equal-weight
universe fwd return).  Monthly decision dates, 80/20 time split, LightGBM,
rank_ic = Spearman rank corr on holdout.

Usage:
    python3 scripts/panel_eval.py                       # baseline + all blocks available
    python3 scripts/panel_eval.py --blocks price fund_rich event
    python3 scripts/panel_eval.py --sentiment-vectors <parquet>
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
DB = Path(PROJECT / "var/investment_research.db")
HORIZON = 240
log = logging.getLogger("panel_eval")


# ---------------- data loading ----------------

def load_bars(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT symbol, trade_date,
                  json_extract(payload_json,'$.close') AS close,
                  json_extract(payload_json,'$.volume') AS volume
           FROM versioned_market_bars
           WHERE active=1 AND interval='1d'
           ORDER BY symbol, trade_date""",
        conn,
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    for c in ("close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"])
    return df


def load_fund_legacy(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per symbol (latest line_items, the round-32 enriched block)."""
    try:
        fis = pd.read_sql_query(
            """SELECT symbol, metric,
                      json_extract(payload_json,'$.value') AS value
               FROM financial_line_items WHERE status='active'""",
            conn,
        )
    except Exception:
        return pd.DataFrame()
    if fis.empty:
        return pd.DataFrame()
    fis["value"] = pd.to_numeric(fis["value"], errors="coerce")
    fi = fis.groupby(["symbol", "metric"])["value"].mean().unstack("metric").reset_index()
    return fi


def load_fund_rich_actuals(conn: sqlite3.Connection) -> pd.DataFrame:
    """PIT-correct fundamentals: a report period YYYYMMDD is knowable at
    period_end + 120 days (conservative A-share disclosure lag; annual reports
    by Apr 30 = +120d from Dec 31).  Returns long-form (symbol, knowable_date,
    metric, value) for asof-merge."""
    try:
        df = pd.read_sql_query(
            "SELECT symbol, report_period AS period, metric, value FROM event_financial_actual",
            conn,
        )
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df = df.dropna(subset=["value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    # knowable date = period end (YYYYMMDD) + 120 calendar days
    pe = pd.to_datetime(df["period"], format="%Y%m%d", errors="coerce")
    df["knowable_date"] = (pe + pd.Timedelta(days=120)).dt.tz_localize(None)
    df = df.dropna(subset=["knowable_date"])
    return df[["symbol", "period", "knowable_date", "metric", "value"]].sort_values(["symbol", "knowable_date"])


def load_consensus(conn: sqlite3.Connection) -> pd.DataFrame:
    try:
        return pd.read_sql_query(
            "SELECT symbol, fiscal_year, metric, mean AS consensus FROM event_consensus_forecast",
            conn,
        )
    except Exception:
        return pd.DataFrame()


def load_notices(conn: sqlite3.Connection) -> pd.DataFrame:
    try:
        df = pd.read_sql_query(
            "SELECT symbol, notice_date, title, notice_type FROM event_notice", conn
        )
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["notice_date"] = pd.to_datetime(df["notice_date"], errors="coerce").dt.tz_localize(None)
    return df.dropna(subset=["notice_date"])


def load_research_reports(conn: sqlite3.Connection) -> pd.DataFrame:
    """Dated analyst research reports (rating + coverage), 2017-2026, PIT-honest."""
    try:
        df = pd.read_sql_query(
            "SELECT symbol, report_date, rating_score, report_count_1m FROM event_research_report",
            conn,
        )
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.tz_localize(None)
    df["rating_score"] = pd.to_numeric(df["rating_score"], errors="coerce")
    df["report_count_1m"] = pd.to_numeric(df["report_count_1m"], errors="coerce")
    return df.dropna(subset=["report_date"]).sort_values(["symbol", "report_date"])


# ---------------- event classification ----------------

# keyword rules for announcement event types (the user's 增减持/回购/问询函/...)
NOTICE_RULES = [
    ("increase_hold", ["增持", "增持股份", "股东增持"]),
    ("decrease_hold", ["减持", "股东减持", "董监高减持"]),
    ("buyback", ["回购", "回购股份", "回购报告书"]),
    ("inquiry", ["问询函", "监管问询", "关注函", "问询"]),
    ("punish", ["处罚", "警示", "监管措施", "立案"]),
    ("pledge", ["质押", "解除质押"]),
    ("guidance_up", ["预增", "续盈", "扭亏", "业绩预增"]),
    ("guidance_down", ["预减", "续亏", "首亏", "亏损", "业绩预减"]),
    ("equity_offer", ["非公开发行", "定增", "增发", "配股"]),
    ("dividend", ["分红", "派息", "利润分配"]),
]


def classify_notice(title: str) -> str:
    t = title or ""
    for label, needles in NOTICE_RULES:
        if any(n in t for n in needles):
            return label
    return "other"


def asof_by_symbol(left: pd.DataFrame, right: pd.DataFrame, *, left_on: str, right_on: str, direction: str = "backward") -> pd.DataFrame:
    """Per-symbol merge_asof (robust across pandas versions — avoids the global
    'left keys must be sorted' failure when concatenating many symbols)."""
    left = left.sort_values(["symbol", left_on])
    right = right.sort_values(["symbol", right_on])
    parts = []
    for s, sub in left.groupby("symbol", sort=False):
        rsub = right[right["symbol"] == s].drop(columns=["symbol"])
        if rsub.empty:
            parts.append(sub)
            continue
        merged = pd.merge_asof(sub, rsub, left_on=left_on, right_on=right_on, direction=direction, suffixes=("", "_y"))
        merged = merged[[c for c in merged.columns if not c.endswith("_y")]]
        parts.append(merged)
    return pd.concat(parts, ignore_index=True) if parts else left


def build_event_features(bars: pd.DataFrame, actuals: pd.DataFrame, consensus: pd.DataFrame, notices: pd.DataFrame, reports: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per (symbol, trade_date) event features, PIT-correct.

    Returns columns: symbol, trade_date,
        eps_yoy, np_yoy, rev_yoy, eps_level, np_level, roe_rich, net_margin_rich, gross_margin_rich,
        surprise_eps, surprise_pct, beat, consensus_fwd_eps,
        n_notices_30d, n_notices_90d, + one per notice-type trailing 90d count,
        rating_score_latest, coverage_1m_latest, rating_mean_90d, n_reports_90d (analyst, PIT).
    """
    out = bars.copy()  # preserve price features + excess_240d target from the caller
    if not actuals.empty:
        # compute eps_yoy in LONG form keyed by period (4 quarterly lags = YoY), BEFORE
        # the asof forward-fill (which would make consecutive daily rows identical -> pct_change=0).
        eps = actuals[actuals["metric"] == "基本每股收益"].sort_values(["symbol", "knowable_date"]).copy()
        if not eps.empty:
            eps["yoy"] = eps.groupby("symbol")["value"].pct_change(4)
            eps_yoy = eps[["symbol", "knowable_date"]].assign(metric="eps_yoy", value=eps["yoy"].values)
            actuals = pd.concat([actuals, eps_yoy], ignore_index=True)
        # pivot metrics wide per (symbol, knowable_date), then asof-merge to bars
        aw = actuals.pivot_table(index=["symbol", "knowable_date"], columns="metric", values="value", aggfunc="last").reset_index()
        aw = aw.sort_values(["symbol", "knowable_date"])
        rename = {
            "基本每股收益": "eps_actual", "归母净利润": "np_actual", "营业总收入": "rev_actual",
            "净利润": "np2_actual", "扣非净利润": "np_recurring", "净资产收益率(ROE)": "roe_rich",
            "销售净利率": "net_margin_rich", "毛利率": "gross_margin_rich", "每股净资产": "bvps",
            "归属母公司净利润增长率": "np_yoy_raw", "营业总收入增长率": "rev_yoy_raw", "eps_yoy": "eps_yoy",
        }
        aw = aw.rename(columns={c: rename[c] for c in aw.columns if c in rename})
        out = out.sort_values(["symbol", "trade_date"])
        out = asof_by_symbol(out, aw, left_on="trade_date", right_on="knowable_date")
        if "np_yoy_raw" in out.columns:
            out["np_yoy"] = out["np_yoy_raw"]
        if "rev_yoy_raw" in out.columns:
            out["rev_yoy"] = out["rev_yoy_raw"]
    # surprise: actual annual EPS (period YYYY1231) − consensus EPS for that fiscal_year, at disclosure (period+120d)
    if not consensus.empty and not actuals.empty:
        ann = actuals[actuals["period"].astype(str).str.endswith("1231")].copy()
        if not ann.empty:
            ann["fiscal_year"] = ann["period"].astype(str).str[:4]
            ann_eps = ann[ann["metric"] == "基本每股收益"][["symbol", "fiscal_year", "value", "knowable_date"]].rename(columns={"value": "eps_actual_ann"})
            ce = consensus[consensus["metric"] == "预测年报每股收益"][["symbol", "fiscal_year", "consensus"]].drop_duplicates(["symbol", "fiscal_year"])
            sur = ann_eps.merge(ce, on=["symbol", "fiscal_year"], how="inner")
            if not sur.empty:
                sur["surprise_eps"] = sur["eps_actual_ann"] - sur["consensus"]
                sur["surprise_pct"] = np.where(sur["consensus"].abs() > 1e-9, sur["surprise_eps"] / sur["consensus"].abs(), np.nan)
                sur["beat"] = (sur["surprise_eps"] > 0).astype(int)
                sur = sur.rename(columns={"knowable_date": "trade_date"})[["symbol", "trade_date", "surprise_eps", "surprise_pct", "beat"]]
                out = out.sort_values(["symbol", "trade_date"])
                # asof-merge surprise (event known at disclosure)
                out = asof_by_symbol(out, sur, left_on="trade_date", right_on="trade_date")
        # forward consensus EPS for latest unreported year (forward-looking, recent tail)
        if not ce.empty:
            fwd = ce.sort_values(["symbol", "fiscal_year"]).groupby("symbol").last().reset_index()[["symbol", "consensus"]].rename(columns={"consensus": "consensus_fwd_eps"})
            out = out.merge(fwd, on="symbol", how="left")
    # notice features (vectorized trailing-window counts)
    if not notices.empty:
        nc = notices.copy()
        nc["type_kw"] = nc["title"].apply(classify_notice)
        out = _add_notice_counts(out, nc)
    # analyst rating features (PIT: report rating known on report_date)
    if reports is not None and not reports.empty:
        rp = reports.dropna(subset=["rating_score"]).copy()
        rp = rp.sort_values(["symbol", "report_date"])
        out = out.sort_values(["symbol", "trade_date"])
        # latest rating + latest coverage via asof
        rp_latest = rp.drop_duplicates(["symbol", "report_date"], keep="last")
        rp_latest = rp_latest.rename(columns={"report_date": "rd", "rating_score": "rating_score_latest", "report_count_1m": "coverage_1m_latest"})
        out = asof_by_symbol(out, rp_latest[["symbol", "rd", "rating_score_latest", "coverage_1m_latest"]], left_on="trade_date", right_on="rd")
        # trailing 90d mean rating + report count (vectorized)
        out = _trailing_count(out, rp[["symbol", "report_date"]].drop_duplicates(), "report_date", 90, "n_reports_90d")
        out = _trailing_mean(out, rp[["symbol", "report_date", "rating_score"]], "report_date", "rating_score", 90, "rating_mean_90d")
    return out


def _trailing_mean(panel: pd.DataFrame, events: pd.DataFrame, ev_date_col: str, val_col: str, window: int, col: str) -> pd.DataFrame:
    """Vectorized trailing-window mean of val_col per (symbol, trade_date)."""
    events = events.dropna(subset=[ev_date_col, val_col])
    if events.empty:
        panel[col] = np.nan
        return panel
    events = events.sort_values(["symbol", ev_date_col])
    panel = panel.sort_values(["symbol", "trade_date"]).copy()
    dates = panel["trade_date"].values
    syms = panel["symbol"].values
    lo = dates - np.timedelta64(window, "D")
    vals = np.full(len(panel), np.nan, dtype=np.float64)
    ev_idx: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for s, gg in events.groupby("symbol"):
        ev_idx[s] = (gg[ev_date_col].values, gg[val_col].values)
    for s, (evd, evv) in ev_idx.items():
        mask = syms == s
        if not mask.any():
            continue
        dsub = dates[mask]
        losub = lo[mask]
        right = np.searchsorted(evd, dsub, side="right")
        left = np.searchsorted(evd, losub, side="left")
        out_v = np.zeros(mask.sum(), dtype=np.float64)
        for i in range(len(dsub)):
            if right[i] > left[i]:
                out_v[i] = np.mean(evv[left[i]:right[i]])
        vals[mask] = out_v
    panel[col] = vals
    return panel


def _trailing_count(panel: pd.DataFrame, events: pd.DataFrame, ev_date_col: str, window: int, col: str) -> pd.DataFrame:
    """Vectorized trailing-window event count per (symbol, trade_date) using searchsorted.

    Counts events with ev_date in (trade_date - window, trade_date]."""
    events = events.dropna(subset=[ev_date_col])
    if events.empty:
        panel[col] = 0
        return panel
    events = events.sort_values(["symbol", ev_date_col])
    ev_idx: dict[str, np.ndarray] = {}
    for s, gg in events.groupby("symbol"):
        ev_idx[s] = gg[ev_date_col].values
    panel = panel.sort_values(["symbol", "trade_date"]).copy()
    dates = panel["trade_date"].values
    syms = panel["symbol"].values
    vals = np.zeros(len(panel), dtype=np.float64)
    # vectorize per-symbol: group panel rows by symbol
    lo = dates - np.timedelta64(window, "D")
    for s, idx in ev_idx.items():
        mask = syms == s
        if not mask.any():
            continue
        dsub = dates[mask]
        losub = lo[mask]
        # searchsorted: count events with ev <= d and ev > d-window
        right = np.searchsorted(idx, dsub, side="right")
        left = np.searchsorted(idx, losub, side="left")
        vals[mask] = right - left
    panel[col] = vals
    return panel


def _add_notice_counts(panel: pd.DataFrame, nc: pd.DataFrame) -> pd.DataFrame:
    """Add n_notices_30d, n_notices_90d, and per-type 90d counts."""
    panel = panel.sort_values(["symbol", "trade_date"]).copy()
    all_e = nc[["symbol", "notice_date"]].drop_duplicates()
    panel = _trailing_count(panel, all_e, "notice_date", 30, "n_notices_30d")
    panel = _trailing_count(panel, all_e, "notice_date", 90, "n_notices_90d")
    for label in [r[0] for r in NOTICE_RULES] + ["other"]:
        sub = nc[nc["type_kw"] == label][["symbol", "notice_date"]].drop_duplicates()
        panel = _trailing_count(panel, sub, "notice_date", 90, "n_notice_" + label + "_90d")
    return panel


# ---------------- price features + target (replicates retrain) ----------------

def build_price_features(bars: pd.DataFrame) -> pd.DataFrame:
    g = bars.sort_values(["symbol", "trade_date"]).copy()
    g["ret_1d"] = g.groupby("symbol")["close"].pct_change(1)
    g["ret_5d"] = g.groupby("symbol")["close"].pct_change(5)
    g["ret_20d"] = g.groupby("symbol")["close"].pct_change(20)
    g["ret_60d"] = g.groupby("symbol")["close"].pct_change(60)
    g["vol_20d"] = g.groupby("symbol")["ret_1d"].transform(lambda s: s.rolling(20).std())
    g["vol_ratio_5d"] = g["volume"] / g.groupby("symbol")["volume"].transform(lambda s: s.rolling(5).mean())
    g["ma_5_ratio"] = g["close"] / g.groupby("symbol")["close"].transform(lambda s: s.rolling(5).mean())
    g["ma_20_ratio"] = g["close"] / g.groupby("symbol")["close"].transform(lambda s: s.rolling(20).mean())
    g["fwd_240d"] = g.groupby("symbol")["close"].pct_change(HORIZON).shift(-HORIZON)
    uni = g.groupby("trade_date")["ret_1d"].mean()
    g["uni_fwd_240d"] = g["trade_date"].map(uni).rolling(HORIZON).sum().shift(-HORIZON)
    g["excess_240d"] = g["fwd_240d"] - g["uni_fwd_240d"]
    # ---- fortune Top10 price alpha features (mirrors feature_v4._add_fortune_price_features) ----
    # ret_120d (longer momentum), Bollinger width (#4), support/resistance distance (#7), MA250 slope/distance (#2)
    grp = g.groupby("symbol")["close"]
    g["ret_120d"] = grp.pct_change(120)
    roll20_mean = grp.transform(lambda s: s.rolling(20).mean())
    roll20_std = grp.transform(lambda s: s.rolling(20).std())
    roll20_max = grp.transform(lambda s: s.rolling(20).max())
    roll20_min = grp.transform(lambda s: s.rolling(20).min())
    span20 = (roll20_max - roll20_min).replace(0.0, np.nan)
    g["bb_width_20d"] = (4.0 * roll20_std) / roll20_mean.replace(0.0, np.nan)
    g["distance_support_20d"] = (g["close"] - roll20_min) / span20
    g["distance_resistance_20d"] = (roll20_max - g["close"]) / span20
    ma250 = grp.transform(lambda s: s.rolling(250).mean())
    ma250_prev = ma250.groupby(g["symbol"]).shift(1)
    g["ma250_slope"] = (ma250 - ma250_prev) / ma250_prev.replace(0.0, np.nan)
    g["distance_ma250"] = (g["close"] / ma250).replace(0.0, np.nan) - 1.0
    return g


PRICE_FEATS = ["ret_1d", "ret_5d", "ret_20d", "ret_60d", "vol_20d", "vol_ratio_5d", "ma_5_ratio", "ma_20_ratio"]
FORTUNE_FEATS = ["ret_120d", "bb_width_20d", "distance_support_20d", "distance_resistance_20d", "ma250_slope", "distance_ma250"]


# ---------------- panel assembly ----------------

def assemble_panel(conn: sqlite3.Connection, sentiment_path: Path | None, sentiment_pca: int = 0) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    import time as _t
    _ck = lambda m: print(f"[ckpt] {m} {round(_t.time()-_t0,1)}s", flush=True)
    _t0 = _t.time()
    bars = load_bars(conn)
    _ck("load_bars")
    g = build_price_features(bars)
    _ck("build_price_features")
    blocks: dict[str, list[str]] = {"price": list(PRICE_FEATS), "fortune": list(FORTUNE_FEATS)}

    # legacy fundamentals (static per symbol)
    fl = load_fund_legacy(conn)
    if not fl.empty:
        if "operating_profit" in fl.columns and "revenue" in fl.columns:
            fl["operating_margin"] = np.where(fl["revenue"] > 0, fl["operating_profit"] / fl["revenue"], np.nan)
        g = g.merge(fl, on="symbol", how="left")
        fund_legacy_cols = [c for c in ("roe", "roa", "net_margin", "operating_margin", "gross_margin") if c in g.columns]
        blocks["fund_legacy"] = fund_legacy_cols

    # rich PIT fundamentals + event features
    actuals = load_fund_rich_actuals(conn)
    consensus = load_consensus(conn)
    notices = load_notices(conn)
    reports = load_research_reports(conn) if getattr(assemble_panel, "_with_ratings", False) else None
    if not actuals.empty:
        ev = build_event_features(g, actuals, consensus, notices, reports)
        _ck("build_event_features")
        # carry forward event/rich-fund values to monthly decision rows
        g = ev
        rich_cols = [c for c in ("roe_rich", "net_margin_rich", "gross_margin_rich", "eps_actual", "np_actual", "rev_actual", "eps_yoy", "np_yoy", "rev_yoy") if c in g.columns]
        if rich_cols:
            blocks["fund_rich"] = rich_cols
        # PIT-honest event block: notice counts/types (+ analyst ratings if enabled, real dates) — no consensus
        ev_cols = [c for c in g.columns if c.startswith("n_notices") or c.startswith("n_notice_") or c.startswith("rating_") or c.startswith("coverage_") or c.startswith("n_reports")]
        if ev_cols:
            blocks["event"] = ev_cols
        # CAVEATED consensus block: surprise/beat use the CURRENT consensus snapshot
        # (akshare free tier gives no historical consensus), so it leaks the future
        # for past fiscal years (consensus converges to actual post-report). Reported
        # only as an UPPER BOUND, NOT deployable.
        cons_cols = [c for c in ("surprise_eps", "surprise_pct", "beat") if c in g.columns]
        if cons_cols:
            blocks["consensus_caveated"] = cons_cols
        if "consensus_fwd_eps" in g.columns:
            blocks["consensus_fwd_caveated"] = ["consensus_fwd_eps"]

    # sentiment vectors (parquet: columns symbol, trade_date, s_0..s_767)
    if sentiment_path and Path(sentiment_path).exists():
        sv = pd.read_parquet(sentiment_path)
        sv["trade_date"] = pd.to_datetime(sv["trade_date"])
        _ck("load_sentiment")
        g = asof_by_symbol(g, sv, left_on="trade_date", right_on="trade_date")
        _ck("merge_sentiment_asof")
        sent_cols = [c for c in sv.columns if c.startswith("s_")]
        if sent_cols:
            if sentiment_pca and sentiment_pca > 0:
                # PCA-reduce to give the dense text embedding a fair chance against
                # the small structured feature set (avoids 768-dim overfit dilution).
                from sklearn.decomposition import PCA
                mat = g[sent_cols].fillna(0.0).values
                n_comp = min(sentiment_pca, mat.shape[1], mat.shape[0])
                pca = PCA(n_components=n_comp, random_state=42)
                red = pca.fit_transform(mat)
                pca_cols = ["sp_" + str(i) for i in range(n_comp)]
                g = g.drop(columns=sent_cols)
                g[pca_cols] = red
                blocks["sentiment"] = pca_cols
                log.info("sentiment PCA: 768 -> %d (explained_var=%.3f)", n_comp, float(np.sum(pca.explained_variance_ratio_)))
            else:
                blocks["sentiment"] = sent_cols

    # drop rows without target + price feats, sample one per symbol per MONTH
    g = g.dropna(subset=["excess_240d"] + PRICE_FEATS)
    g["ym"] = g["trade_date"].dt.to_period("M")
    panel = g.groupby(["symbol", "ym"]).last().reset_index()
    _ck("monthly_sample")
    return panel, blocks


# ---------------- eval ----------------

def rank_ic(y_true, y_pred) -> float:
    s = pd.Series(y_pred).rank()
    t = pd.Series(y_true).rank()
    return float(s.corr(t))


def train_eval(panel: pd.DataFrame, feats: list[str], label: str) -> dict:
    import lightgbm as lgb
    X = panel[feats].copy()
    X = X.fillna(X.median())
    # if any col all-nan, fill 0
    X = X.fillna(0.0)
    y = panel["excess_240d"].astype(float)
    if len(X) < 200:
        return {"label": label, "status": "no_data", "n": len(X)}
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
    ric = rank_ic(y_va.values, pred_va)
    fi = dict(zip(X.columns, model.feature_importances_))
    top = sorted(fi.items(), key=lambda kv: -kv[1])[:8]
    return {
        "label": label, "status": "ok", "n_train": len(X_tr), "n_val": len(X_va),
        "rank_ic": round(ric, 4), "passes_0.10": bool(ric > 0.10),
        "top_features": [{"name": n, "importance": int(i)} for n, i in top],
    }


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--blocks", nargs="*", default=None, help="subset of blocks to include; default runs canonical combos")
    p.add_argument("--sentiment-vectors", type=Path, default=None)
    p.add_argument("--sentiment-pca", type=int, default=0, help="PCA-reduce sentiment vectors to N dims (0 = use raw 768)")
    p.add_argument("--with-ratings", action="store_true", help="add analyst rating features (experiment; default OFF — dilutes)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    assemble_panel._with_ratings = args.with_ratings
    conn = sqlite3.connect(str(DB), timeout=60.0)
    panel, blocks = assemble_panel(conn, args.sentiment_vectors, args.sentiment_pca)
    conn.close()
    log.info("panel: %d rows, %d symbols, blocks=%s", len(panel), panel["symbol"].nunique(), {k: len(v) for k, v in blocks.items()})
    if len(panel) < 200:
        print(json.dumps({"status": "no_data", "n": len(panel)}))
        return 1
    # canonical comparison of block combos
    if args.blocks:
        feats = []
        for b in args.blocks:
            feats += blocks.get(b, [])
        r = train_eval(panel, feats, "+".join(args.blocks))
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    combos = []
    base = ["price"]
    if "fund_legacy" in blocks:
        combos.append(base + ["fund_legacy"])
    if "fund_rich" in blocks:
        combos.append(base + ["fund_rich"])
    # PIT-honest event block (YoY + levels + notices — no consensus): deployable
    if "fund_rich" in blocks and "event" in blocks:
        combos.append(base + ["fund_rich", "event"])
    # fortune Top10 price-alpha features (ret_120d, bb_width, support/resist, ma250) — the
    # intended fix for the negative OOF IC on excess_return in the fortune candidate-suite.
    if "fortune" in blocks:
        combos.append(base + ["fortune"])
    if "fund_rich" in blocks and "fortune" in blocks:
        combos.append(base + ["fund_rich", "fortune"])
    if "fund_rich" in blocks and "event" in blocks and "fortune" in blocks:
        combos.append(base + ["fund_rich", "event", "fortune"])
    # sentiment (added later via --sentiment-vectors)
    if "sentiment" in blocks:
        combos.append(base + ["fund_rich", "event", "sentiment"])
    # CAVEATED upper bounds (consensus current-snapshot = look-ahead; NOT deployable)
    if "consensus_caveated" in blocks:
        combos.append(base + ["fund_rich", "event", "consensus_caveated"])
    if "consensus_fwd_caveated" in blocks:
        combos.append(base + ["fund_rich", "event", "consensus_fwd_caveated"])
    results = {}
    # always run price baseline
    results["price"] = train_eval(panel, blocks["price"], "price")
    for c in combos:
        feats = []
        for b in c:
            feats += blocks[b]
        results["+".join(c)] = train_eval(panel, feats, "+".join(c))
    # deltas vs price baseline
    base_ric = results["price"].get("rank_ic")
    for k, v in results.items():
        if k != "price" and base_ric is not None and v.get("rank_ic") is not None:
            v["delta_vs_price"] = round(v["rank_ic"] - base_ric, 4)
    out = {
        "status": "ok", "horizon_days": HORIZON, "n_symbols": int(panel["symbol"].nunique()),
        "n_panel_rows": len(panel), "blocks": {k: len(v) for k, v in blocks.items()},
        "results": results,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    outdir = PROJECT / "artifacts/model_performance"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "panel_eval_event_sentiment.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
