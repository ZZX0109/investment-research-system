#!/usr/bin/env python3
"""Full pipeline: Phase A → B → C → D → E.

Orchestrates real data snapshots, multi-task labels, walk-forward training,
post-training evaluation, model cards, and invest agent config.
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import traceback
from datetime import date, datetime, time, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
#  Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMP_DIR = PROJECT_ROOT / "temp"
LOG_PATH = OUTPUT_DIR / "pipeline_log.txt"

for d in (OUTPUT_DIR, TEMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(SRC_DIR))


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------------------
#  Phase A — Real data snapshots
# ---------------------------------------------------------------------------

def phase_a() -> dict[str, Path]:
    """Build real data bundles for all four markets.

    Public sources are research-only. Synthetic fallback is disabled unless the
    operator explicitly sets INVESTMENT_RESEARCH_ALLOW_SYNTHETIC_SANDBOX=true.
    """
    from investment_research.training.catalog import UNIVERSE_PRESETS
    from investment_research.training.models import (
        CanonicalInstrument,
        CoveragePreset,
        InstrumentType,
        Market,
        PointInTimeEvent,
        PreparedPriceBar,
    )
    from investment_research.training.sources import (
        CanonicalDatasetBundle,
        normalize_akshare_rows,
        normalize_yfinance_rows,
        resolve_coverage_preset,
    )

    US_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "SPY", "QQQ", "XLK"]
    CN_SYMBOLS = ["000858.SZ", "300750.SZ", "601318.SH", "510050.SH", "159915.SZ", "000300.SH"]
    HK_SYMBOLS = ["0700.HK", "9988.HK", "2823.HK", "^HSI"]
    JP_SYMBOLS = ["7203.T", "9984.T", "^N225"]

    bundles: dict[str, Path] = {}

    def _fetch_yfinance(symbols: list[str], market_label: str) -> dict[str, list[dict]]:
        """Fetch via yfinance; return {symbol: [row_dict, ...]}."""
        import yfinance as yf

        data: dict[str, list[dict]] = {}
        for sym in symbols:
            try:
                ticker = yf.Ticker(sym)
                df = ticker.history(period="2y")
                if df.empty:
                    log(f"  yfinance empty for {sym}, using synthetic")
                    data[sym] = _synthetic_bars(sym, market_label)
                    continue
                rows = []
                for idx, row in df.iterrows():
                    rows.append(
                        {
                            "date": idx.date(),
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "adj_close": float(row.get("Close", row["Close"])),
                            "volume": int(row["Volume"]),
                        }
                    )
                data[sym] = rows
                log(f"  yfinance OK {sym}: {len(rows)} bars")
            except Exception as exc:
                log(f"  yfinance FAIL {sym}: {exc}")
                data[sym] = _synthetic_bars(sym, market_label)
        return data

    def _fetch_akshare(symbols: list[str]) -> dict[str, list[dict]]:
        import akshare as ak

        data: dict[str, list[dict]] = {}
        for sym in symbols:
            try:
                if sym.endswith(".SH"):
                    code = sym.replace(".SH", "")
                    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20230601", end_date="20260701", adjust="qfq")
                elif sym.endswith(".SZ"):
                    code = sym.replace(".SZ", "")
                    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20230601", end_date="20260701", adjust="qfq")
                else:
                    df = None

                if df is None or df.empty:
                    log(f"  akshare empty for {sym}, using synthetic")
                    data[sym] = _synthetic_bars(sym, "cn")
                    continue

                # Normalize akshare column names
                date_col = "日期" if "日期" in df.columns else df.columns[0]
                rows = []
                for _, row in df.iterrows():
                    rows.append(
                        {
                            "date": pd.Timestamp(row[date_col]).date() if hasattr(pd, "Timestamp") else date.today(),
                            "open": float(row.get("开盘", row.iloc[1])),
                            "high": float(row.get("最高", row.iloc[2])),
                            "low": float(row.get("最低", row.iloc[3])),
                            "close": float(row.get("收盘", row.iloc[4])),
                            "volume": int(row.get("成交量", 0)),
                        }
                    )
                data[sym] = rows
                log(f"  akshare OK {sym}: {len(rows)} bars")
            except Exception as exc:
                log(f"  akshare FAIL {sym}: {exc}")
                data[sym] = _synthetic_bars(sym, "cn")
        return data

    def _synthetic_bars(sym: str, market: str) -> list[dict]:
        """Generate synthetic price bars for fallback with valid OHLC ordering."""
        if os.environ.get("INVESTMENT_RESEARCH_ALLOW_SYNTHETIC_SANDBOX", "").lower() not in {"1", "true", "yes"}:
            raise RuntimeError("Synthetic fallback is disabled; use the explicit sandbox flag for non-formal experiments")
        import math
        import random

        random.seed(hash(sym) % (2**31))
        n = 252 * 2
        close = 100.0 + random.uniform(0, 400)
        rows = []
        start = date(2024, 1, 1)
        bar_count = 0
        day_offset = 0
        while bar_count < n:
            d = start + __import__("datetime", fromlist=["timedelta"]).timedelta(days=day_offset)
            day_offset += 1
            if d.weekday() >= 5:
                continue
            ret = random.gauss(0.0003, 0.015)
            close = close * (1 + ret)
            # Build OHLC with guaranteed low <= min(open,close) <= max(open,close) <= high
            # Generate open as a random value within a range around close
            move = close * 0.005
            open_price = close + random.uniform(-move, move)
            # high >= max(open, close)
            high_add = abs(open_price - close) + random.uniform(0.001, 0.008) * close
            high_price = max(open_price, close) + high_add
            # low <= min(open, close)
            low_sub = abs(open_price - close) + random.uniform(0.001, 0.008) * close
            low_price = min(open_price, close) - low_sub

            rows.append(
                {
                    "date": d,
                    "open": round(open_price, 2),
                    "high": round(high_price, 2),
                    "low": round(low_price, 2),
                    "close": round(close, 2),
                    "adj_close": round(close, 2),
                    "volume": random.randint(10000, 10000000),
                }
            )
            bar_count += 1
        return rows

    # Fetch all data
    log("Phase A: Fetching real/synthetic data...")

    import pandas as pd

    try:
        us_raw = _fetch_yfinance(US_SYMBOLS, "us")
    except Exception as exc:
        log(f"US yfinance raised: {exc}, falling back to synthetic")
        us_raw = {sym: _synthetic_bars(sym, "us") for sym in US_SYMBOLS}

    try:
        cn_raw = _fetch_akshare(CN_SYMBOLS)
    except Exception as exc:
        log(f"CN akshare raised: {exc}, falling back to synthetic")
        cn_raw = {sym: _synthetic_bars(sym, "cn") for sym in CN_SYMBOLS}

    try:
        hk_raw = _fetch_yfinance(HK_SYMBOLS, "hk")
    except Exception as exc:
        log(f"HK yfinance raised: {exc}, falling back to synthetic")
        hk_raw = {sym: _synthetic_bars(sym, "hk") for sym in HK_SYMBOLS}

    try:
        jp_raw = _fetch_yfinance(JP_SYMBOLS, "jp")
    except Exception as exc:
        log(f"JP yfinance raised: {exc}, falling back to synthetic")
        jp_raw = {sym: _synthetic_bars(sym, "jp") for sym in JP_SYMBOLS}

    # Build bundles — aggregate per-symbol bundles into a market-level aggregate
    def _build_market_bundle(symbols, raw_data, market_label) -> dict:
        """Aggregate normalize results for a market. Returns dict for pickling."""
        from investment_research.training.sources import (
            normalize_yfinance_rows,
            normalize_akshare_rows,
        )

        all_instruments: list = []
        all_bars: list = []
        all_events: list = []

        for sym in symbols:
            preset = UNIVERSE_PRESETS.get(sym)
            if preset is None:
                log(f"  WARNING: no preset for {sym}")
                continue

            price_rows = raw_data.get(sym, [])

            # Normalize
            try:
                if preset.market in (Market.US, Market.HK, Market.JP):
                    bundle = normalize_yfinance_rows(symbol=sym, rows=price_rows)
                else:
                    bundle = normalize_akshare_rows(symbol=sym, rows=price_rows)
            except Exception as exc:
                log(f"  Normalize FAIL {sym}: {exc}")
                continue

            all_instruments.append(bundle.instrument)
            all_bars.extend(bundle.price_bars)
            all_events.extend(bundle.events)

        return {
            "market": market_label,
            "instruments": all_instruments,
            "price_bars": all_bars,
            "events": all_events,
            "created_at": datetime.now(timezone.utc),
        }

    us_bundle_data = _build_market_bundle(US_SYMBOLS, us_raw, "us")
    cn_bundle_data = _build_market_bundle(CN_SYMBOLS, cn_raw, "cn")
    hk_bundle_data = _build_market_bundle(HK_SYMBOLS, hk_raw, "hk")
    jp_bundle_data = _build_market_bundle(JP_SYMBOLS, jp_raw, "jp")

    # Save
    for label, data in [("us", us_bundle_data), ("cn", cn_bundle_data), ("hk", hk_bundle_data), ("jp", jp_bundle_data)]:
        path = OUTPUT_DIR / f"bundle_{label}.pkl"
        with open(path, "wb") as fh:
            pickle.dump(data, fh)
        bundles[label] = path
        log(f"  Saved {label} bundle: {path} ({len(data['price_bars'])} bars)")

    return bundles


# ---------------------------------------------------------------------------
#  Phase B — Multi-task labels
# ---------------------------------------------------------------------------

def phase_b(bundles: dict[str, Path]) -> Path:
    """Generate multi-task labels from Phase A bundles."""
    from investment_research.training.data_quality import prepare_price_bars
    from investment_research.training.dataset import TrainingDatasetBuilder
    from investment_research.training.models import (
        DataQualityRuleSet,
        PreparedPriceBar,
    )

    log("Phase B: Generating multi-task labels...")

    rules = DataQualityRuleSet()
    all_samples: list = []
    prepared_by_symbol: dict[str, list[PreparedPriceBar]] = {}
    all_prepared: list[PreparedPriceBar] = []

    for market_label, bundle_path in bundles.items():
        with open(bundle_path, "rb") as fh:
            bundle_data = pickle.load(fh)

        instruments = bundle_data["instruments"]
        price_bars = bundle_data["price_bars"]
        events = bundle_data["events"]

        log(f"  {market_label}: {len(instruments)} instruments, {len(price_bars)} bars")

        # Group bars by symbol
        bars_by_sym: dict[str, list] = {}
        for bar in price_bars:
            bars_by_sym.setdefault(bar.symbol, []).append(bar)

        # Group events by symbol
        events_by_sym: dict[str, list] = {}
        for evt in events:
            events_by_sym.setdefault(evt.symbol, []).append(evt)

        inst_map = {inst.symbol: inst for inst in instruments}

        for sym, raw_bars in bars_by_sym.items():
            inst = inst_map.get(sym)
            if inst is None:
                continue

            # Convert CanonicalPriceBar → PreparedPriceBar
            prepared, _issues = prepare_price_bars(raw_bars, rules=rules)
            if not prepared:
                continue
            prepared_by_symbol[sym] = prepared
            all_prepared.extend(prepared)

            benchmark_symbol = inst.benchmark_symbol
            sector_sym = inst.sector_reference_symbol
            style_sym = inst.style_reference_symbol

            benchmark_bars = prepared_by_symbol.get(benchmark_symbol, []) if benchmark_symbol else []
            sector_bars = prepared_by_symbol.get(sector_sym, []) if sector_sym else []
            style_bars = prepared_by_symbol.get(style_sym, []) if style_sym else []
            sym_events = events_by_sym.get(sym, [])

            builder = TrainingDatasetBuilder(
                feature_version="v1.0",
                data_version=f"bundle_{market_label}",
            )
            samples = builder.build_samples(
                instrument=inst,
                price_bars=prepared,
                benchmark_bars=benchmark_bars,
                sector_reference_bars=sector_bars,
                style_reference_bars=style_bars,
                events=sym_events,
            )
            all_samples.extend(samples)

        log(f"  {market_label}: {len(all_samples)} cumulative samples")

    if not all_samples:
        log("  WARNING: zero samples generated")
        samples_path = TEMP_DIR / "all_samples.pkl"
        pickle.dump({"samples": [], "price_bars": []}, open(samples_path, "wb"))
        return samples_path

    # Save labels CSV
    labels_path = OUTPUT_DIR / "labels.csv"
    import csv

    sample_label_fields = sorted(
        set().union(*(s.labels.model_dump().keys() for s in all_samples))
    )
    with open(labels_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["symbol", "as_of_date"] + sample_label_fields)
        for s in all_samples:
            row = [s.symbol, s.as_of_date.isoformat()]
            d = s.labels.model_dump()
            for f in sample_label_fields:
                row.append(d.get(f, ""))
            writer.writerow(row)

    log(f"  labels.csv saved: {labels_path} ({len(all_samples)} samples)")

    # Save samples pickle for Phase C
    samples_path = TEMP_DIR / "all_samples.pkl"
    with open(samples_path, "wb") as fh:
        pickle.dump({"samples": all_samples, "price_bars": all_prepared}, fh)

    return samples_path


# ---------------------------------------------------------------------------
#  Phase C — Walk-forward training matrix
# ---------------------------------------------------------------------------

def phase_c(samples_path: Path) -> Path:
    """Run walk-forward training across all models."""
    from investment_research.training.trainers import default_trainer_specs
    from investment_research.training.deep_trainers import deep_trainer_specs
    from investment_research.training.experiments import TrainingExperimentRunner

    log("Phase C: Walk-forward training matrix...")

    with open(samples_path, "rb") as fh:
        data = pickle.load(fh)

    samples = data["samples"]

    if not samples:
        log("  No samples — skipping training")
        return _write_minimal_results()

    log(f"  {len(samples)} samples across {len({s.symbol for s in samples})} symbols")

    # Sort by date
    samples.sort(key=lambda s: s.as_of_date)

    all_specs = list(default_trainer_specs()) + deep_trainer_specs()
    runner = TrainingExperimentRunner(
        target_name="future_max_drawdown_20d",
        trainer_specs=all_specs,
        drawdown_threshold=-0.08,
    )

    try:
        report = runner.run(
            samples=samples,
            train_window_days=180,
            validation_window_days=60,
            step_days=30,
            regime_reference=data.get("price_bars"),
        )
    except Exception as exc:
        log(f"  Training runner failed: {exc}")
        traceback.print_exc()
        return _write_minimal_results()

    # Gather results
    results_data: dict = {
        "target_name": report.target_name,
        "baseline_model_id": report.baseline_model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": [],
    }

    for result in report.results:
        model_entry: dict = {
            "trainer_name": result.trainer_name,
            "algorithm_family": result.algorithm_family,
            "eligible_for_approval": result.eligible_for_approval,
            "model_id": result.model_card.model_id,
            "status": result.model_card.status.value,
            "folds": [],
        }

        # Extract metrics from list[FoldMetric]; group by fold
        for fold_result in result.fold_results:
            fold_entry: dict = {
                "fold_id": fold_result.fold.fold_id,
                "train_start": fold_result.fold.train_start.isoformat(),
                "train_end": fold_result.fold.train_end.isoformat(),
                "val_start": fold_result.fold.validation_start.isoformat(),
                "val_end": fold_result.fold.validation_end.isoformat(),
                "regime": fold_result.fold.regime,
                "n_predictions": len(fold_result.predictions),
                "metrics": {},
            }
            for m in fold_result.metrics:
                fold_entry["metrics"][m.metric_name] = m.metric_value
            model_entry["folds"].append(fold_entry)

        results_data["models"].append(model_entry)
        log(f"  {result.trainer_name}: eligible={result.eligible_for_approval}, folds={len(result.fold_results)}")

    # Save
    results_path = OUTPUT_DIR / "results.json"
    with open(results_path, "w", encoding="utf-8") as fh:
        json.dump(results_data, fh, indent=2, ensure_ascii=False, default=str)
    log(f"  results.json saved: {results_path}")

    # Save full report for Phase D/E
    report_path = TEMP_DIR / "experiment_report.pkl"
    with open(report_path, "wb") as fh:
        pickle.dump(report, fh)

    return results_path


def _write_minimal_results() -> Path:
    """Write a minimal results.json when training skipped."""
    path = OUTPUT_DIR / "results.json"
    with open(path, "w") as fh:
        json.dump({"status": "skipped", "reason": "no samples or training failed"}, fh)
    return path


# ---------------------------------------------------------------------------
#  Phase D — Post-training evaluation
# ---------------------------------------------------------------------------

def _calibration_curve_wide_bins(y_true: list[int], y_prob: list[float], n_bins: int = 10) -> list[dict]:
    """Equal-width calibration curve."""
    pairs = sorted(zip(y_prob, y_true), key=lambda x: x[0])
    if not pairs:
        return []

    curve: list[dict] = []
    size = len(pairs)
    for i in range(n_bins):
        start = int(i * size / n_bins)
        end = int((i + 1) * size / n_bins)
        if start >= end:
            continue
        bucket = pairs[start:end]
        curve.append({
            "bucket": i,
            "center": round(sum(p[0] for p in bucket) / len(bucket), 3),
            "mean_predicted": round(sum(p[0] for p in bucket) / len(bucket), 4),
            "mean_actual": round(sum(p[1] for p in bucket) / len(bucket), 4),
            "count": len(bucket),
        })
    return curve


def _ece_brier(y_true: list[int], y_prob: list[float], n_bins: int = 10) -> tuple[float, float]:
    """Compute ECE and Brier score."""
    n = len(y_true)
    if n == 0:
        return 0.0, 0.0

    brier = sum((p - t) ** 2 for p, t in zip(y_prob, y_true)) / n

    pairs = sorted(zip(y_prob, y_true), key=lambda x: x[0])
    ece = 0.0
    bin_size = n / n_bins
    for i in range(n_bins):
        start = int(i * bin_size)
        end = int((i + 1) * bin_size)
        if start >= end:
            continue
        bucket = pairs[start:end]
        if not bucket:
            continue
        mean_prob = sum(p[0] for p in bucket) / len(bucket)
        mean_label = sum(p[1] for p in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(mean_prob - mean_label)

    return round(ece, 4), round(brier, 4)


def phase_d() -> None:
    """Post-training evaluation: calibration, regime-aware, stability."""
    log("Phase D: Post-training evaluation...")

    report_path = TEMP_DIR / "experiment_report.pkl"
    if not report_path.exists():
        log("  No experiment report found — skipping Phase D")
        return

    with open(report_path, "rb") as fh:
        report = pickle.load(fh)

    eval_data: dict = {"models": []}

    for result in report.results:
        model_eval: dict = {"trainer": result.trainer_name}

        # Collect all predictions across folds
        all_scores: list[float] = []
        all_labels: list[int] = []
        fold_top_features: dict[str, list[str]] = {}
        regime_metrics: dict[str, dict] = {}

        for fold_result in result.fold_results:
            regime = fold_result.fold.regime
            if regime not in regime_metrics:
                regime_metrics[regime] = {"folds": 0, "n_preds": 0, "scores": [], "labels": []}

            regime_metrics[regime]["folds"] += 1

            for pred in fold_result.predictions:
                score = pred.calibrated_score if pred.calibrated_score > 0 else pred.raw_score
                all_scores.append(score)
                all_labels.append(pred.predicted_label)
                regime_metrics[regime]["scores"].append(score)
                regime_metrics[regime]["labels"].append(pred.predicted_label)
                regime_metrics[regime]["n_preds"] += 1

        if not all_scores:
            log(f"  {result.trainer_name}: no predictions — skipping")
            model_eval["status"] = "no_predictions"
            eval_data["models"].append(model_eval)
            continue

        # Calibration
        ece, brier = _ece_brier(all_labels, all_scores)
        curve = _calibration_curve_wide_bins(all_labels, all_scores)
        model_eval["calibration"] = {
            "ece": ece,
            "brier_score": brier,
            "n_predictions": len(all_scores),
        }
        model_eval["calibration_curve"] = curve

        # Regime-aware: per-regime ECE + score stats
        model_eval["regime_aware"] = {}
        for regime, reg_data in sorted(regime_metrics.items()):
            if reg_data["scores"]:
                r_ece, r_brier = _ece_brier(reg_data["labels"], reg_data["scores"])
                model_eval["regime_aware"][regime] = {
                    "n_folds": reg_data["folds"],
                    "n_predictions": reg_data["n_preds"],
                    "ece": r_ece,
                    "brier_score": r_brier,
                    "mean_score": round(sum(reg_data["scores"]) / len(reg_data["scores"]), 4),
                }
            else:
                model_eval["regime_aware"][regime] = {"n_folds": reg_data["folds"], "n_preds": 0}

        # Fold-level metrics table
        model_eval["fold_metrics"] = []
        for fold_result in result.fold_results:
            fm = {
                "fold_id": fold_result.fold.fold_id,
                "regime": fold_result.fold.regime,
                "n_preds": len(fold_result.predictions),
            }
            for m in fold_result.metrics:
                fm[m.metric_name] = m.metric_value
            if fold_result.predictions:
                fold_scores = [p.calibrated_score or p.raw_score for p in fold_result.predictions]
                fold_labels = [p.predicted_label for p in fold_result.predictions]
                fm["mean_score"] = round(sum(fold_scores) / len(fold_scores), 4)
            model_eval["fold_metrics"].append(fm)

        eval_data["models"].append(model_eval)
        log(f"  {result.trainer_name}: ECE={ece}, Brier={brier}, predictions={len(all_scores)}")

    eval_path = OUTPUT_DIR / "evaluation.json"
    with open(eval_path, "w", encoding="utf-8") as fh:
        json.dump(eval_data, fh, indent=2, ensure_ascii=False, default=str)
    log(f"  evaluation.json saved: {eval_path}")


# ---------------------------------------------------------------------------
#  Phase E — Model cards + invest agent config
# ---------------------------------------------------------------------------

def phase_e() -> None:
    """Generate model cards and invest agent configuration."""
    log("Phase E: Model cards and invest agent config...")

    report_path = TEMP_DIR / "experiment_report.pkl"
    if not report_path.exists():
        log("  No experiment report — writing minimal configs")
        _write_minimal_configs()
        return

    with open(report_path, "rb") as fh:
        report = pickle.load(fh)

    model_cards: dict[str, dict] = {}
    approved_models: list[dict] = []

    for result in report.results:
        card = result.model_card

        # Collect metrics from FoldMetric list
        all_fold_metrics: dict[str, list[float]] = {}
        for fold_result in result.fold_results:
            for m in fold_result.metrics:
                all_fold_metrics.setdefault(m.metric_name, []).append(m.metric_value)

        metrics_summary: dict = {}
        for name, values in all_fold_metrics.items():
            metrics_summary[name] = {
                "mean": round(sum(values) / len(values), 4) if values else None,
                "min": round(min(values), 4) if values else None,
                "max": round(max(values), 4) if values else None,
            }

        # Gate checks (7 promotion checks)
        gate_info: dict = {
            "eligible": result.eligible_for_approval,
            "checks": [],
        }
        if result.promotion_result:
            gate_info["reasons"] = result.promotion_result.reasons
            for check in result.promotion_result.checks:
                gate_info["checks"].append({
                    "name": check.check_name,
                    "status": check.status,
                    "actual": check.actual_value,
                    "threshold": check.threshold_value,
                    "detail": check.detail,
                })

        card_data = {
            "model_id": card.model_id,
            "trainer_name": result.trainer_name,
            "algorithm_family": result.algorithm_family,
            "task_name": card.task_name,
            "status": card.status.value,
            "data_version": card.data_version,
            "feature_version": card.feature_version,
            "label_version": card.label_version,
            "training_window": {
                "start": card.training_window_start.isoformat(),
                "end": card.training_window_end.isoformat(),
            },
            "calibration_method": card.calibration_method,
            "created_at": card.training_created_at.isoformat(),
            "notes": card.notes,
            "fold_metrics": metrics_summary,
            "promotion_gate": gate_info,
            "eligible_for_approval": result.eligible_for_approval,
        }

        # Add regime coverage
        card_data["regime_coverage"] = [
            {"regime": rc.regime, "folds": rc.fold_count, "preds": rc.validation_prediction_count}
            for rc in result.regime_coverage
        ]

        model_cards[result.trainer_name] = card_data

        # Individual model card file
        card_path = OUTPUT_DIR / f"model_card_{result.trainer_name}.json"
        with open(card_path, "w", encoding="utf-8") as fh:
            json.dump(card_data, fh, indent=2, ensure_ascii=False, default=str)
        log(f"  model_card_{result.trainer_name}.json saved")

        # Track approved
        if result.eligible_for_approval:
            approved_models.append({
                "trainer_name": result.trainer_name,
                "model_id": card.model_id,
                "algorithm_family": result.algorithm_family,
                "features": [],
                "threshold": 0.5,
                "applicable_markets": ["us", "cn", "hk", "jp"],
            })

    # Master model_cards.json
    master_path = OUTPUT_DIR / "model_cards.json"
    with open(master_path, "w", encoding="utf-8") as fh:
        json.dump(model_cards, fh, indent=2, ensure_ascii=False, default=str)

    # invest_agent_models.json
    invest_config = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "approved_models": approved_models,
        "feature_version": "v1.0",
        "data_version": "bundle_us_cn_hk_jp",
        "rollback_log": [],
    }
    invest_path = OUTPUT_DIR / "invest_agent_models.json"
    with open(invest_path, "w", encoding="utf-8") as fh:
        json.dump(invest_config, fh, indent=2, ensure_ascii=False, default=str)
    log(f"  invest_agent_models.json saved: {invest_path}")


def _write_minimal_configs() -> None:
    invest_path = OUTPUT_DIR / "invest_agent_models.json"
    with open(invest_path, "w") as fh:
        json.dump({"approved_models": [], "status": "skipped"}, fh)
    master_path = OUTPUT_DIR / "model_cards.json"
    with open(master_path, "w") as fh:
        json.dump({}, fh)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main() -> int:
    log("DEPRECATED: forwarding to scripts/run_formal_pipeline.py")
    import subprocess

    return subprocess.call(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "run_formal_pipeline.py")],
        cwd=PROJECT_ROOT,
    )


if __name__ == "__main__":
    sys.exit(main())
