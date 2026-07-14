#!/usr/bin/env python3
"""Enhanced retraining with synthetic or real point-in-time data.

Generates synthetic data with momentum persistence, volatility clustering,
and regime-switching dynamics, or reuses validated real-data bundles produced
by fetch_real_data.py/fetch_real_events.py. Then re-runs Phase B-E.

Run: source .venv/bin/activate && python scripts/run_retraining.py
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import pickle
import random
import subprocess
import sys
import time
import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = Path(os.environ.get("INVESTMENT_RESEARCH_OUTPUT_DIR", PROJECT / "output"))
AUDITS = Path(os.environ.get("INVESTMENT_RESEARCH_AUDIT_DIR", PROJECT / "audits"))
TEMP = Path(os.environ.get("INVESTMENT_RESEARCH_TEMP_DIR", PROJECT / "temp"))
RUNS = Path(os.environ.get("INVESTMENT_RESEARCH_RUNS_DIR", PROJECT / "runs"))

sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.catalog import UNIVERSE_PRESETS, market_symbols
from investment_research.training.models import (
    AdjustmentPolicy,
    CurrencyHandlingPolicy,
    DataQualityRuleSet,
    PreparedPriceBar,
)
from investment_research.training.dataset import TrainingDatasetBuilder
from investment_research.training.data_quality import prepare_price_bars
from investment_research.training.trainers import default_trainer_specs
from investment_research.training.deep_trainers import DEFAULT_DEEP_MAX_EPOCHS
from investment_research.training.deep_trainers import DEFAULT_DEEP_MAX_SAMPLES
from investment_research.training.deep_trainers import DEFAULT_DEEP_PATIENCE
from investment_research.training.deep_trainers import deep_trainer_specs
from investment_research.feature_contract import FEATURE_CONTRACT_VERSION
from investment_research.training.evaluation import evaluate_risk_bucket_usefulness
from investment_research.training.experiments import TrainingExperimentRunner
from investment_research.training.models import RiskBucketObservation
from investment_research.training.trust_framework import (
    TRUST_FRAMEWORK_VERSION,
    sample_snapshot_hash,
)

RANDOM_SEED = 42

MARKET_SYMBOLS = {
    "us": market_symbols("us"),
    "cn": market_symbols("cn"),
    "hk": market_symbols("hk"),
    "jp": market_symbols("jp"),
}
TRAINING_KEEP_RATIO = {
    "equity": 1.0,
    "etf": 0.75,
    "index": 0.35,
}
EVENTFUL_SYMBOL_MIN_RATIO = 0.10
PRIMARY_TASK = "future_max_drawdown_20d"
AUXILIARY_TASKS = [
    "future_return_20d",
    "risk_adjusted_return_20d",
    "volatility_spike_10d",
    "event_drawdown_5d",
]
EVENT_CONDITIONED_TASKS = {
    "event_drawdown_5d",
    "post_earnings_abnormal_move_5d",
    "news_event_shock_3d",
}
MIN_TASK_UNIQUE_DATES = 240
APPROVABLE_PRIMARY_TRAINERS = {
    "linear-baseline",
    "random-forest",
    "lightgbm",
    "xgboost",
}
REFERENCE_FALLBACKS = {
    "us": {
        "benchmark": ["^GSPC", "SPY", "QQQ"],
        "sector": ["SPY", "XLK", "QQQ"],
        "style": ["QQQ", "SPY"],
    },
    "cn": {
        "benchmark": ["000300.SH", "510300.SH", "000001.SH"],
        "sector": ["510300.SH", "510050.SH", "159919.SZ"],
        "style": ["399006.SZ", "000300.SH", "510300.SH"],
    },
    "hk": {
        "benchmark": ["^HSI", "2800.HK", "2828.HK"],
        "sector": ["2800.HK", "2828.HK"],
        "style": ["2828.HK", "2800.HK"],
    },
    "jp": {
        "benchmark": ["^N225", "1306.T", "1321.T"],
        "sector": ["1306.T", "1321.T"],
        "style": ["1321.T", "1306.T"],
    },
}
REFERENCE_FEATURE_THRESHOLDS = {
    "benchmark_ret_20d": 0.02,
    "relative_strength_20d": 0.02,
    "style_ret_20d": 0.05,
    "style_relative_strength_20d": 0.05,
}

warnings.filterwarnings(
    "ignore",
    message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
)
warnings.filterwarnings(
    "ignore",
    message="Converting a tensor with requires_grad=True to a scalar may lead to unexpected behavior.",
)
warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    module=r"sklearn\.linear_model\._linear_loss",
)
warnings.filterwarnings(
    "ignore",
    message=".*encountered in matmul",
    category=RuntimeWarning,
    module=r"sklearn\.utils\.extmath",
)


class PackageRenameUnpickler(pickle.Unpickler):
    """Read training artifacts pickled before the package rename."""

    def find_class(self, module: str, name: str):
        if module.startswith("investment_workbuddy"):
            module = module.replace("investment_workbuddy", "investment_research", 1)
        return super().find_class(module, name)


def load_pickle(path: Path):
    with open(path, "rb") as f:
        return PackageRenameUnpickler(f).load()


def dump_pickle(path: Path, data) -> None:
    with open(path, "wb") as f:
        pickle.dump(data, f)


def _run_label(*, data_source: str, profile: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{data_source}-{profile}"


def _artifact_root(*, authoritative: bool, run_label: str) -> Path:
    if authoritative:
        return OUTPUT
    run_dir = RUNS / run_label
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _authoritative_run(*, data_source: str, profile: str) -> bool:
    return data_source == "real" and profile == "full"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _event_counts(events: list) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        event_type = getattr(
            getattr(event, "event_type", None),
            "value",
            getattr(event, "event_type", "unknown"),
        )
        counts[str(event_type)] += 1
    return dict(counts)


def _provider_failures() -> dict:
    report = _load_json(TEMP / "fetch_events_validation.json")
    failures: dict[str, object] = {}
    for market, market_report in report.items():
        if isinstance(market_report, dict):
            failures[market] = market_report.get("provider_failures", [])
    return failures


def assess_market_eligibility(
    *, bundles: dict[str, Path], data_source: str
) -> dict[str, dict]:
    if data_source != "real":
        return {
            market: {
                "included": True,
                "reason": [],
                "price_complete": True,
                "event_coverage_ok": True,
                "eventful_symbol_ratio": 1.0,
                "event_type_counts": {},
                "expected_symbols": len(expected_symbols),
            }
            for market, expected_symbols in MARKET_SYMBOLS.items()
        }

    price_report = _load_json(TEMP / "fetch_validation.json")
    event_report = _load_json(TEMP / "fetch_events_validation.json")
    eligibility: dict[str, dict] = {}
    for market, bundle_path in bundles.items():
        bundle_data = load_pickle(bundle_path)
        events = list(bundle_data.get("events", []))
        expected_symbols = MARKET_SYMBOLS.get(market, [])
        eventful_symbols = {
            getattr(event, "symbol", "")
            for event in events
            if getattr(event, "symbol", "")
        }
        event_type_counts = dict(
            event_report.get(market, {}).get("event_type_counts", {})
            or _event_counts(events)
        )
        price_market_report = price_report.get(market, {})
        missing_symbols = price_market_report.get("missing_symbols", [])
        price_complete = len(missing_symbols) == 0 and price_market_report.get(
            "fetched_symbols", len(expected_symbols)
        ) == len(expected_symbols)
        event_coverage_ok = any(
            event_type_counts.get(key, 0) > 0
            for key in ("news", "filing", "announcement", "earnings")
        )
        eventful_ratio = (
            len(eventful_symbols) / len(expected_symbols) if expected_symbols else 0.0
        )

        reasons: list[str] = []
        if not price_complete:
            reasons.append("price coverage below 100%")
        if not event_coverage_ok:
            reasons.append("event coverage is zero")
        elif eventful_ratio < EVENTFUL_SYMBOL_MIN_RATIO:
            reasons.append(
                f"eventful symbol ratio {eventful_ratio:.2f} below threshold {EVENTFUL_SYMBOL_MIN_RATIO:.2f}"
            )

        eligibility[market] = {
            "included": not reasons,
            "reason": reasons,
            "price_complete": price_complete,
            "event_coverage_ok": event_coverage_ok,
            "eventful_symbol_ratio": round(eventful_ratio, 4),
            "event_type_counts": event_type_counts,
            "expected_symbols": len(expected_symbols),
            "provider_failures": event_report.get(market, {}).get(
                "provider_failures", []
            ),
        }
    return eligibility


def _empty_reference_stats() -> dict[str, dict]:
    return {
        reference_type: {
            "configured_count": 0,
            "direct_count": 0,
            "fallback_count": 0,
            "missing_count": 0,
            "fallback_pairs": defaultdict(int),
            "missing_symbols": defaultdict(int),
        }
        for reference_type in ("benchmark", "sector", "style")
    }


def _resolve_reference_bars(
    *,
    instrument,
    reference_type: str,
    prepared_by_symbol: dict[str, list[PreparedPriceBar]],
    reference_stats: dict[str, dict],
) -> list[PreparedPriceBar]:
    configured_symbol = _configured_reference_symbol(instrument, reference_type)
    stats = reference_stats[reference_type]
    if configured_symbol:
        stats["configured_count"] += 1

    candidates = _reference_candidate_symbols(instrument, reference_type)
    direct_bars = prepared_by_symbol.get(configured_symbol or "", [])
    merged_by_date = {bar.trade_date: bar for bar in direct_bars}
    if _reference_has_minimum_history(direct_bars):
        stats["direct_count"] += 1
    fallback_used = False
    for candidate in candidates:
        if candidate == configured_symbol:
            continue
        added = 0
        for bar in prepared_by_symbol.get(candidate, []):
            if bar.trade_date not in merged_by_date:
                merged_by_date[bar.trade_date] = bar
                added += 1
        if added:
            fallback_used = True
            stats["fallback_pairs"][f"{configured_symbol or 'none'}->{candidate}"] += 1
    if fallback_used:
        stats["fallback_count"] += 1
    merged = sorted(
        merged_by_date.values(), key=lambda bar: (bar.trade_date, bar.published_at)
    )
    if _reference_has_minimum_history(merged):
        return merged

    stats["missing_count"] += 1
    stats["missing_symbols"][configured_symbol or "none"] += 1
    return []


def _configured_reference_symbol(instrument, reference_type: str) -> str | None:
    field_name = {
        "benchmark": "benchmark_symbol",
        "sector": "sector_reference_symbol",
        "style": "style_reference_symbol",
    }[reference_type]
    value = getattr(instrument, field_name, None)
    return str(value).upper() if value else None


def _reference_candidate_symbols(instrument, reference_type: str) -> list[str]:
    market = instrument.market.value
    configured = _configured_reference_symbol(instrument, reference_type)
    fallbacks = REFERENCE_FALLBACKS.get(market, {}).get(reference_type, [])
    candidates: list[str] = []
    for symbol in [configured, *fallbacks]:
        if not symbol:
            continue
        normalized = str(symbol).upper()
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _reference_has_minimum_history(bars: list[PreparedPriceBar]) -> bool:
    return len({bar.trade_date for bar in bars}) >= 20


def _finalize_reference_preflight(
    reference_stats: dict[str, dict], samples: list
) -> dict:
    missing_rates = _reference_missing_rates(samples)
    stats: dict[str, dict] = {}
    for reference_type, payload in reference_stats.items():
        configured_count = int(payload["configured_count"])
        direct_count = int(payload["direct_count"])
        fallback_count = int(payload["fallback_count"])
        missing_count = int(payload["missing_count"])
        stats[reference_type] = {
            "configured_count": configured_count,
            "direct_count": direct_count,
            "fallback_count": fallback_count,
            "missing_count": missing_count,
            "direct_ratio": round(direct_count / configured_count, 4)
            if configured_count
            else 0.0,
            "fallback_ratio": round(fallback_count / configured_count, 4)
            if configured_count
            else 0.0,
            "missing_ratio": round(missing_count / configured_count, 4)
            if configured_count
            else 0.0,
            "fallback_pairs": dict(sorted(payload["fallback_pairs"].items())),
            "missing_symbols": dict(sorted(payload["missing_symbols"].items())),
        }
    threshold_checks = {}
    for feature_name, max_missing_ratio in REFERENCE_FEATURE_THRESHOLDS.items():
        actual = float(missing_rates.get(feature_name, {}).get("missing_ratio", 0.0))
        threshold_checks[feature_name] = {
            "missing_ratio": actual,
            "max_missing_ratio": max_missing_ratio,
            "status": "passed" if actual <= max_missing_ratio else "risk_flag",
        }
    return {
        "reference_resolution": stats,
        "reference_missing_rates": missing_rates,
        "threshold_checks": threshold_checks,
        "risk_flag": any(
            item["status"] != "passed" for item in threshold_checks.values()
        ),
    }


def _training_weight(symbol: str) -> float:
    preset = UNIVERSE_PRESETS[symbol]
    return TRAINING_KEEP_RATIO[preset.instrument_type.value]


def _keep_sample(symbol: str, as_of_date: date) -> bool:
    ratio = _training_weight(symbol)
    if ratio >= 1.0:
        return True
    digest = hashlib.sha256(
        f"{symbol}:{as_of_date.isoformat()}".encode("utf-8")
    ).hexdigest()[:8]
    bucket = int(digest, 16) / 0xFFFFFFFF
    return bucket <= ratio


def _serialize_models(
    *,
    artifact_root: Path,
    samples_path: Path,
    results_path: Path,
    invest_config_path: Path,
    report_path: Path,
) -> None:
    cmd = [
        sys.executable,
        str(PROJECT / "scripts" / "serialize_models.py"),
        "--report",
        str(report_path),
        "--results",
        str(results_path),
        "--invest-config",
        str(invest_config_path),
        "--samples",
        str(samples_path),
        "--output-dir",
        str(artifact_root / "models"),
    ]
    subprocess.run(cmd, cwd=PROJECT, check=True)


def _run_audits() -> None:
    subprocess.run(
        [sys.executable, str(PROJECT / "scripts" / "run_audits.py")],
        cwd=PROJECT,
        check=True,
    )


def _write_training_status(
    *,
    run_label: str,
    data_source: str,
    profile: str,
    authoritative: bool,
    included_markets: list[str],
    excluded_markets: list[str],
    excluded_market_reasons: dict[str, list[str]],
    market_eligibility: dict[str, dict],
    duration_seconds: float,
) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "state": "succeeded",
        "run_label": run_label,
        "generated_at": completed_at,
        "completed_at": completed_at,
        "data_source": data_source,
        "training_profile": profile,
        "authoritative": authoritative,
        "planned_markets": sorted(MARKET_SYMBOLS),
        "planned_market_count": len(MARKET_SYMBOLS),
        "included_markets": included_markets,
        "included_market_count": len(included_markets),
        "excluded_markets": excluded_markets,
        "excluded_market_reasons": excluded_market_reasons,
        "event_coverage_status": market_eligibility,
        "provider_failure_summary": _provider_failures(),
        "full_training_duration_seconds": round(duration_seconds, 3),
    }
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "training-status.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    run_dir = RUNS / run_label
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "training-status.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# =========================================================================
#  Enhanced Synthetic Data Generator
# =========================================================================


def _synthetic_bars_enhanced(sym: str, market: str) -> list[dict]:
    """Generate synthetic price rows with momentum, vol clustering, regime switching."""
    seed = int(hashlib.sha256(f"{sym}:{market}".encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    n = 504
    close = 100.0 + rng.uniform(0, 400)
    vol = rng.uniform(0.008, 0.02)
    regime = rng.choice(["bull", "bear", "range"])
    regime_days = rng.randint(40, 80)

    rows = []
    start = date(2024, 1, 1)
    bar_count = 0
    day_offset = 0

    while bar_count < n:
        d = start + timedelta(days=day_offset)
        day_offset += 1
        if d.weekday() >= 5:
            continue

        regime_days -= 1
        if regime_days <= 0:
            if regime == "bull":
                regime = rng.choice(["bear", "range"])
            elif regime == "bear":
                regime = rng.choice(["bull", "range"])
            else:
                regime = rng.choice(["bull", "bear"])
            regime_days = rng.randint(30, 90)

        drift_map = {"bull": 0.0006, "bear": -0.0004, "range": 0.0001}
        vol_map = {"bull": 1.1, "bear": 1.4, "range": 0.9}
        drift = drift_map[regime] + rng.uniform(-0.0002, 0.0002)
        vol_mult = vol_map[regime]

        if bar_count >= 20:
            recent = [r["close"] for r in rows[-20:]]
            ma20 = sum(recent) / 20
            drift += ((close / ma20) - 1.0) * 0.03

        vol = 0.85 * vol + 0.15 * (vol_mult * rng.uniform(0.006, 0.025))
        ret = rng.gauss(drift, vol)
        close_prev = close
        close = close * (1 + ret)
        close = max(close, 0.5)

        open_price = close_prev * (1 + rng.uniform(-vol * 0.3, vol * 0.3))
        high_add = abs(open_price - close) + rng.uniform(0.001, 0.008) * close
        low_sub = abs(open_price - close) + rng.uniform(0.001, 0.008) * close
        high_price = max(open_price, close) + high_add
        low_price = min(open_price, close) - low_sub

        if regime == "bear" and rng.random() < 0.08:
            close = close * (1 - rng.uniform(0.02, 0.06))
            high_price = max(high_price, close * 1.01)
            low_price = close * (1 - rng.uniform(0.005, 0.015))

        # Keep synthetic OHLC valid after shock adjustments and rounding.
        high_price = max(high_price, open_price, close)
        low_price = min(low_price, open_price, close)

        rows.append(
            {
                "date": d,
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close, 2),
                "adj_close": round(close, 2),
                "volume": int(rng.uniform(100000, 50000000)),
            }
        )
        bar_count += 1

    return rows


# =========================================================================
#  Phase A: Build enhanced bundles
# =========================================================================


def phase_a(*, data_source: str) -> dict[str, Path]:
    if data_source == "synthetic":
        return _build_synthetic_bundles()
    if data_source == "real":
        return _load_real_bundles(strict=True)
    if data_source == "auto":
        try:
            return _load_real_bundles(strict=True)
        except RuntimeError as exc:
            print(f"  Real bundle unavailable for auto mode: {exc}")
            print("  Falling back to synthetic training data.")
            return _build_synthetic_bundles()
    raise ValueError(f"Unsupported data source: {data_source}")


def _build_synthetic_bundles() -> dict[str, Path]:
    from investment_research.training.sources import (
        normalize_yfinance_rows,
        normalize_akshare_rows,
    )

    print("Phase A: Building enhanced structured bundles...")
    bundles = {}

    market_configs = [
        ("us", MARKET_SYMBOLS["us"], normalize_yfinance_rows),
        ("cn", MARKET_SYMBOLS["cn"], normalize_akshare_rows),
        ("hk", MARKET_SYMBOLS["hk"], normalize_yfinance_rows),
        ("jp", MARKET_SYMBOLS["jp"], normalize_yfinance_rows),
    ]

    for mkt_label, symbols, normalizer in market_configs:
        all_instruments = []
        all_bars = []
        all_events = []

        for sym in symbols:
            price_rows = _synthetic_bars_enhanced(sym, mkt_label)
            try:
                bundle = normalizer(symbol=sym, rows=price_rows)
            except Exception as exc:
                print(f"  Normalize FAIL {sym}: {exc}")
                continue
            all_instruments.append(bundle.instrument)
            all_bars.extend(bundle.price_bars)
            all_events.extend(bundle.events)

        data = {
            "market": mkt_label,
            "instruments": all_instruments,
            "price_bars": all_bars,
            "events": all_events,
            "created_at": datetime.now(timezone.utc),
            "source": "synthetic_enhanced",
            "source_meta": {
                "mode": "sandbox",
                "provider": "synthetic_enhanced",
                "synthetic_ratio": 1.0,
                "event_count": len(all_events),
            },
        }
        path = OUTPUT / f"bundle_{mkt_label}.pkl"
        dump_pickle(path, data)
        bundles[mkt_label] = path
        print(
            f"  {mkt_label}: {len(all_instruments)} instruments, {len(all_bars)} bars, {len(all_events)} events"
        )

    return bundles


def _load_real_bundles(*, strict: bool) -> dict[str, Path]:
    print("Phase A: Loading real-data bundles...")
    bundles: dict[str, Path] = {}
    for market_label, expected_symbols in MARKET_SYMBOLS.items():
        path = OUTPUT / f"bundle_{market_label}.pkl"
        if not path.exists():
            raise RuntimeError(f"missing {path}; run scripts/fetch_real_data.py first")

        bundle_data = load_pickle(path)

        if strict and not _looks_like_real_bundle(bundle_data):
            source = (
                bundle_data.get("source") if isinstance(bundle_data, dict) else None
            )
            raise RuntimeError(
                f"{path.name} source={source!r} is not marked as real; "
                "run scripts/fetch_real_data.py or use --data-source synthetic"
            )

        _merge_event_file(market_label, bundle_data)
        _validate_loaded_bundle(market_label, bundle_data, expected_symbols)
        bundle_data["source_meta"] = {
            "mode": "real",
            "provider": bundle_data.get("source", "real_bundle"),
            "synthetic_ratio": 0.0,
            "event_count": len(bundle_data.get("events", [])),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
        dump_pickle(path, bundle_data)

        bundles[market_label] = path
        print(
            f"  {market_label}: {len(bundle_data.get('instruments', []))} instruments, "
            f"{len(bundle_data.get('price_bars', []))} bars, "
            f"{len(bundle_data.get('events', []))} events"
        )
    return bundles


def _looks_like_real_bundle(bundle_data: object) -> bool:
    if not isinstance(bundle_data, dict):
        return False
    source = str(bundle_data.get("source", "")).lower()
    provider = str((bundle_data.get("source_meta") or {}).get("provider", "")).lower()
    return any(
        token in source or token in provider
        for token in ("real", "yfinance", "akshare")
    )


def _merge_event_file(market_label: str, bundle_data: dict) -> None:
    event_path = OUTPUT / f"events_{market_label}.pkl"
    if not event_path.exists():
        return
    external_events = load_pickle(event_path)
    events = list(bundle_data.get("events", []))
    seen = {_event_key(event) for event in events}
    added = 0
    for event in external_events:
        key = _event_key(event)
        if key in seen:
            continue
        events.append(event)
        seen.add(key)
        added += 1
    bundle_data["events"] = events
    bundle_data["events_source"] = str(event_path)
    if added:
        print(
            f"  {market_label}: merged {added} external events from {event_path.name}"
        )


def _event_key(event) -> tuple[str, str, str, str]:
    event_type = getattr(
        getattr(event, "event_type", None), "value", getattr(event, "event_type", "")
    )
    published_at = getattr(event, "published_at", "")
    if hasattr(published_at, "isoformat"):
        published_at = published_at.isoformat()
    return (
        str(getattr(event, "symbol", "")),
        str(event_type),
        str(published_at),
        str(
            getattr(event, "payload_ref", None)
            or getattr(event, "source_url", None)
            or getattr(event, "headline", "")
        ),
    )


def _validate_loaded_bundle(
    market_label: str, bundle_data: dict, expected_symbols: list[str]
) -> None:
    instruments = bundle_data.get("instruments", [])
    price_bars = bundle_data.get("price_bars", [])
    if not instruments or not price_bars:
        raise RuntimeError(f"{market_label} bundle is empty")
    actual_symbols = {getattr(bar, "symbol", "") for bar in price_bars}
    if not actual_symbols.intersection(expected_symbols):
        raise RuntimeError(
            f"{market_label} bundle does not contain any expected symbols"
        )


# =========================================================================
#  Phase B: Labels
# =========================================================================


def phase_b(
    bundles: dict[str, Path],
    *,
    authoritative: bool,
    artifact_root: Path,
    market_eligibility: dict[str, dict],
) -> Path:
    """Generate multi-task labels — mirrors original run_full_pipeline.py Phase B exactly."""
    print("\nPhase B: Generating multi-task labels...")

    rules = DataQualityRuleSet(
        adjustment_policy=AdjustmentPolicy.RAW_CLOSE,
        currency_policy=CurrencyHandlingPolicy.NATIVE,
    )
    all_samples = []
    all_prepared: list[PreparedPriceBar] = []
    prepared_by_symbol: dict[str, list[PreparedPriceBar]] = {}
    reference_stats = _empty_reference_stats()

    included_markets = [
        market
        for market, report in market_eligibility.items()
        if report.get("included")
    ]
    filtered_bundles = {
        market: path for market, path in bundles.items() if market in included_markets
    }
    cache_manifest_path = TEMP / "sample_cache_manifest.json"
    samples_cache_path = TEMP / "all_samples.pkl"
    cache_fingerprint = _sample_cache_fingerprint(filtered_bundles)
    if (
        authoritative
        and samples_cache_path.exists()
        and (artifact_root / "labels.csv").exists()
        and cache_manifest_path.exists()
    ):
        cached_manifest = _load_json(cache_manifest_path)
        if cached_manifest.get("fingerprint") == cache_fingerprint:
            print(f"  Reusing trusted PIT sample cache: {samples_cache_path}")
            return samples_cache_path

    for mkt_label, bundle_path in filtered_bundles.items():
        bd = load_pickle(bundle_path)

        instruments = bd["instruments"]
        price_bars = bd["price_bars"]
        events = bd["events"]

        print(f"  {mkt_label}: {len(instruments)} instruments, {len(price_bars)} bars")

        bars_by_sym: dict[str, list] = {}
        for bar in price_bars:
            bars_by_sym.setdefault(bar.symbol, []).append(bar)

        events_by_sym: dict[str, list] = {}
        for evt in events:
            events_by_sym.setdefault(evt.symbol, []).append(evt)

        inst_map = {inst.symbol: inst for inst in instruments}

        bundle_prepared_by_symbol: dict[str, list[PreparedPriceBar]] = {}
        for sym, raw_bars in bars_by_sym.items():
            prepared, _ = prepare_price_bars(raw_bars, rules=rules)
            if not prepared:
                continue
            bundle_prepared_by_symbol[sym] = prepared
            prepared_by_symbol[sym] = prepared
            all_prepared.extend(prepared)

        for sym, prepared in bundle_prepared_by_symbol.items():
            inst = inst_map.get(sym)
            if inst is None:
                continue

            benchmark_bars = _resolve_reference_bars(
                instrument=inst,
                reference_type="benchmark",
                prepared_by_symbol=prepared_by_symbol,
                reference_stats=reference_stats,
            )
            sector_bars = _resolve_reference_bars(
                instrument=inst,
                reference_type="sector",
                prepared_by_symbol=prepared_by_symbol,
                reference_stats=reference_stats,
            )
            style_bars = _resolve_reference_bars(
                instrument=inst,
                reference_type="style",
                prepared_by_symbol=prepared_by_symbol,
                reference_stats=reference_stats,
            )
            sym_events = events_by_sym.get(sym, [])

            builder = TrainingDatasetBuilder(
                feature_version="v2.0-trust", data_version=f"bundle_{mkt_label}"
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

        print(f"  {mkt_label}: {len(all_samples)} cumulative samples")

    if not all_samples:
        print("  WARNING: zero samples generated")
        sp = TEMP / "all_samples.pkl"
        dump_pickle(
            sp,
            {
                "samples": [],
                "raw_samples": [],
                "price_bars": [],
                "market_eligibility": market_eligibility,
                "reference_preflight": _finalize_reference_preflight(
                    reference_stats, []
                ),
            },
        )
        return sp

    training_samples = [
        sample
        for sample in all_samples
        if _keep_sample(sample.symbol, sample.as_of_date)
    ]
    reference_preflight = _finalize_reference_preflight(
        reference_stats, training_samples
    )

    label_path = artifact_root / "labels.csv"
    label_fields = sorted(
        set().union(*(s.labels.model_dump().keys() for s in all_samples))
    )
    # Filter out fields that are already separate columns
    label_fields = [lf for lf in label_fields if lf not in ("symbol", "as_of_date")]
    with open(label_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "symbol",
                "market",
                "instrument_type",
                "as_of_date",
                "training_weight",
                "selected_for_training",
            ]
            + label_fields
        )
        for s in all_samples:
            d = s.labels.model_dump()
            writer.writerow(
                [
                    s.symbol,
                    s.market.value,
                    s.instrument_type.value,
                    s.as_of_date.isoformat(),
                    _training_weight(s.symbol),
                    int(_keep_sample(s.symbol, s.as_of_date)),
                ]
                + [d.get(lf, "") for lf in label_fields]
            )

    print(f"  labels.csv saved: {label_path} ({len(all_samples)} samples)")

    sp = TEMP / "all_samples.pkl"
    dump_pickle(
        sp,
        {
            "samples": training_samples,
            "raw_samples": all_samples,
            "price_bars": all_prepared,
            "market_eligibility": market_eligibility,
            "reference_preflight": reference_preflight,
            "selection_summary": {
                "raw_sample_count": len(all_samples),
                "training_sample_count": len(training_samples),
                "samples_removed_by_weighting": len(all_samples)
                - len(training_samples),
            },
        },
    )
    cache_manifest_path.write_text(
        json.dumps(
            {
                "fingerprint": cache_fingerprint,
                "feature_contract_version": FEATURE_CONTRACT_VERSION,
                "label_pipeline_version": "multitask-v2",
                "reference_resolver_version": "market-fallback-merge-v2",
                "sample_count": len(training_samples),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return sp


def _sample_cache_fingerprint(bundles: dict[str, Path]) -> str:
    artifacts = []
    for market, path in sorted(bundles.items()):
        bundle = load_pickle(path)
        latest_by_symbol: dict[str, tuple[str, str]] = {}
        for bar in bundle.get("price_bars", []):
            key = (
                bar.trade_date.isoformat(),
                bar.normalized_hash or bar.raw_hash or "",
            )
            if key > latest_by_symbol.get(bar.symbol, ("", "")):
                latest_by_symbol[bar.symbol] = key
        events = bundle.get("events", [])
        artifacts.append(
            {
                "market": market,
                "price_count": len(bundle.get("price_bars", [])),
                "latest_by_symbol": sorted(latest_by_symbol.items()),
                "event_count": len(events),
                "event_tail": sorted(
                    (
                        event.symbol,
                        event.published_at.isoformat(),
                        event.normalized_hash
                        or event.raw_hash
                        or event.payload_ref
                        or "",
                    )
                    for event in events
                )[-256:],
            }
        )
    payload = {
        "artifacts": artifacts,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "label_pipeline_version": "multitask-v2",
        "reference_resolver_version": "market-fallback-merge-v2",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


# =========================================================================
#  Phase C-E
# =========================================================================


def phase_c_e(
    samples_path: Path,
    *,
    profile: str,
    data_source: str,
    authoritative: bool,
    artifact_root: Path,
    run_label: str,
) -> dict:
    print("\nPhase C: Walk-forward training matrix...")
    data = load_pickle(samples_path)
    samples = data["samples"]
    raw_samples = data.get("raw_samples", samples)
    market_eligibility = data.get("market_eligibility", {})
    reference_preflight = data.get("reference_preflight", {})
    if not samples:
        print("  No samples — skipping")
        return {}
    print(f"  {len(samples)} samples across {len({s.symbol for s in samples})} symbols")
    samples.sort(key=lambda s: s.as_of_date)

    task_reports: dict[str, object] = {}
    task_results_matrix: dict[str, dict] = {}
    all_model_cards: list[dict] = []
    all_specs_primary = list(default_trainer_specs())
    if profile == "full":
        all_specs_primary += deep_trainer_specs()
    all_specs_aux = list(default_trainer_specs())
    task_order = [PRIMARY_TASK, *AUXILIARY_TASKS]

    for task_name in task_order:
        specs = all_specs_primary if task_name == PRIMARY_TASK else all_specs_aux
        task_samples = _samples_for_task(samples, task_name)
        task_sample_summary = _task_sample_summary(task_samples, task_name)
        if not _has_min_task_span(task_samples):
            task_results_matrix[task_name] = {
                "target_name": task_name,
                "baseline_model_id": None,
                "models": [],
                "regime_breakdown": {},
                "recent_window_breakdown": {},
                "approval_scope": "primary"
                if task_name == PRIMARY_TASK
                else "research_only",
                "task_sample_summary": task_sample_summary,
                "skipped": True,
                "skip_reason": "insufficient_unique_dates_for_walk_forward",
            }
            print(
                f"  task={task_name} skipped: insufficient unique dates ({task_sample_summary})"
            )
            continue
        print(f"  task={task_name} profile={profile} trainers={len(specs)}")
        report = TrainingExperimentRunner(
            target_name=task_name,
            trainer_specs=specs,
            drawdown_threshold=-0.08,
        ).run(
            samples=task_samples,
            train_window_days=180,
            validation_window_days=60,
            step_days=30,
            regime_reference=data.get("price_bars"),
        )
        task_reports[task_name] = report
        task_results = _report_to_model_summary(report)
        if task_name == PRIMARY_TASK:
            _force_non_approvable_primary_models_research_only(task_results)
            _force_deep_models_research_only(task_results)
        task_results_matrix[task_name] = {
            "target_name": report.target_name,
            "baseline_model_id": report.baseline_model_id,
            "models": task_results,
            "regime_breakdown": _report_regime_breakdown(report),
            "recent_window_breakdown": _recent_window_breakdown(report),
            "approval_scope": "primary"
            if task_name == PRIMARY_TASK
            else "research_only",
            "task_sample_summary": task_sample_summary,
        }
        for result in report.results:
            card = result.model_card.model_dump()
            card["trainer_name"] = result.trainer_name
            eligible_for_approval = (
                task_name == PRIMARY_TASK
                and result.eligible_for_approval
                and _is_approvable_primary_trainer(result.trainer_name)
                and not _is_deep_research_only(
                    result.trainer_name, result.algorithm_family
                )
            )
            card["eligible_for_approval"] = eligible_for_approval
            card["deployment_status"] = (
                "approved" if eligible_for_approval else "research_only"
            )
            card["approval_role"] = (
                "champion"
                if task_name == PRIMARY_TASK
                and result.trainer_name == "linear-baseline"
                else "challenger"
            )
            all_model_cards.append(card)

    _write_oof_predictions(
        task_reports,
        AUDITS / "oof_predictions.jsonl.gz",
        samples=samples,
    )

    report = task_reports[PRIMARY_TASK]

    included_markets = sorted(
        market
        for market, record in market_eligibility.items()
        if record.get("included")
    )
    excluded_markets = sorted(
        market
        for market, record in market_eligibility.items()
        if not record.get("included")
    )
    excluded_market_reasons = {
        market: list(record.get("reason", []))
        for market, record in market_eligibility.items()
        if not record.get("included")
    }

    results_data: dict = {
        "target_name": report.target_name,
        "baseline_model_id": report.baseline_model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "label_set_version": "multitask-v2",
        "task_matrix": task_results_matrix,
        "data_source": data_source,
        "training_profile": profile,
        "authoritative": authoritative,
        "run_label": run_label,
        "sample_snapshot_hash": sample_snapshot_hash(samples),
        "trust_framework_version": TRUST_FRAMEWORK_VERSION,
        "sample_count": len(samples),
        "raw_sample_count": len(raw_samples),
        "symbol_count": len({s.symbol for s in raw_samples}),
        "samples_with_events": sum(
            1 for s in samples if s.point_in_time_event_count > 0
        ),
        "included_markets": included_markets,
        "excluded_markets": excluded_markets,
        "excluded_market_reasons": excluded_market_reasons,
        "coverage_group_distribution": _coverage_group_distribution(raw_samples),
        "universe_distribution": _universe_distribution(),
        "reference_missing_rates": _reference_missing_rates(samples),
        "reference_preflight": reference_preflight,
        "reference_risk_flag": bool(reference_preflight.get("risk_flag"))
        if isinstance(reference_preflight, dict)
        else False,
        "event_task_sample_counts": {
            task_name: payload.get("task_sample_summary", {})
            for task_name, payload in task_results_matrix.items()
            if task_name in EVENT_CONDITIONED_TASKS
        },
        "event_feature_coverage": _event_feature_coverage(samples),
        "regime_breakdown": _report_regime_breakdown(report),
        "recent_window_breakdown": _recent_window_breakdown(report),
        "samples_removed_by_weighting": max(0, len(raw_samples) - len(samples)),
        "weighting_policy": TRAINING_KEEP_RATIO,
        "training_budget": _training_budget(profile=profile),
        "models": [],
    }
    results_data["models"] = task_results_matrix[PRIMARY_TASK]["models"]

    approved_models = [
        model for model in results_data["models"] if model.get("eligible_for_approval")
    ]
    approved_challengers = [
        model
        for model in approved_models
        if model.get("trainer_name") != "linear-baseline"
    ]
    deployment_roles = _deployment_roles_for_results(results_data)
    results_data["deployment_roles"] = deployment_roles
    results_data["approval_summary"] = {
        "champion": "linear-baseline",
        "primary_model": deployment_roles["primary_model"],
        "champion_fallback": deployment_roles["champion_fallback"],
        "approved_model_count": len(approved_models),
        "approved_challenger_count": len(approved_challengers),
        "message": "0 approved challengers"
        if not approved_challengers
        else f"{len(approved_challengers)} approved challengers",
    }

    for card in all_model_cards:
        card["feature_contract_version"] = FEATURE_CONTRACT_VERSION
        card["data_source"] = data_source
        card["training_profile"] = profile
        if card.get("task_name") != PRIMARY_TASK:
            card["deployment_role"] = "research_only"
        elif card.get("trainer_name") == deployment_roles["primary_model"]:
            card["deployment_role"] = "primary"
        elif card.get("trainer_name") == deployment_roles["champion_fallback"]:
            card["deployment_role"] = "champion_fallback"
        elif card.get("trainer_name") in deployment_roles["approved_challengers"]:
            card["deployment_role"] = "approved_challenger"
        else:
            card["deployment_role"] = "research_only"

    artifact_root.mkdir(parents=True, exist_ok=True)
    with open(artifact_root / "results.json", "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2, ensure_ascii=False, default=str)

    print("\nPhase D: Post-training evaluation...")
    evaluation = _compute_evaluation(results_data)
    with open(artifact_root / "evaluation.json", "w", encoding="utf-8") as f:
        json.dump(evaluation, f, indent=2, ensure_ascii=False, default=str)

    print("Phase E: Model cards + invest agent config...")
    _write_model_cards(all_model_cards, artifact_root=artifact_root)
    _write_invest_config(results_data, artifact_root=artifact_root)
    report_path = TEMP / "experiment_report.pkl"
    dump_pickle(report_path, report)
    if authoritative:
        _serialize_models(
            artifact_root=artifact_root,
            samples_path=samples_path,
            results_path=artifact_root / "results.json",
            invest_config_path=artifact_root / "invest_agent_models.json",
            report_path=report_path,
        )

    return results_data


def _write_oof_predictions(
    task_reports: dict[str, object],
    path: Path,
    *,
    samples: list,
) -> None:
    """Persist row-level OOF predictions needed for abstention and paper studies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    sample_index = {
        (sample.symbol, sample.as_of_date.isoformat()): sample for sample in samples
    }
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        for task_name, report in task_reports.items():
            for result in report.results:
                for fold_result in result.fold_results:
                    for prediction in fold_result.predictions:
                        sample = sample_index.get(
                            (prediction.symbol, prediction.as_of_date.isoformat())
                        )
                        handle.write(
                            json.dumps(
                                {
                                    "task_name": task_name,
                                    "trainer_name": result.trainer_name,
                                    "fold_id": fold_result.fold.fold_id,
                                    "regime": fold_result.fold.regime,
                                    "sample_feature_coverage": (
                                        None if sample is None else sample.feature_coverage
                                    ),
                                    "missing_features": (
                                        [] if sample is None else sample.missing_features
                                    ),
                                    **prediction.model_dump(mode="json"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
    temporary.replace(path)


def _report_to_model_summary(report) -> list[dict]:
    models: list[dict] = []
    higher_is_risk = "drawdown" not in str(getattr(report, "target_name", ""))
    for result in report.results:
        model_entry: dict = {
            "trainer_name": result.trainer_name,
            "algorithm_family": result.algorithm_family,
            "eligible_for_approval": result.eligible_for_approval,
            "model_id": result.model_card.model_id,
            "status": result.model_card.status.value,
            "market_breakdown": _prediction_breakdown_from_folds(
                result.fold_results, "market", higher_is_risk=higher_is_risk
            ),
            "coverage_group_breakdown": _prediction_breakdown_from_folds(
                result.fold_results,
                "coverage_group",
                higher_is_risk=higher_is_risk,
            ),
            "folds": [],
        }
        for fr in result.fold_results:
            model_entry["folds"].append(
                {
                    "fold_id": fr.fold.fold_id,
                    "train_start": fr.fold.train_start.isoformat(),
                    "train_end": fr.fold.train_end.isoformat(),
                    "val_start": fr.fold.validation_start.isoformat(),
                    "val_end": fr.fold.validation_end.isoformat(),
                    "regime": fr.fold.regime,
                    "n_predictions": len(fr.predictions),
                    "market_breakdown": _prediction_breakdown(
                        fr.predictions, "market", higher_is_risk=higher_is_risk
                    ),
                    "coverage_group_breakdown": _prediction_breakdown(
                        fr.predictions,
                        "coverage_group",
                        higher_is_risk=higher_is_risk,
                    ),
                    "metrics": {
                        metric.metric_name: metric.metric_value for metric in fr.metrics
                    },
                }
            )
        models.append(model_entry)
    return models


def _prediction_breakdown_from_folds(
    fold_results: list, dimension: str, *, higher_is_risk: bool
) -> dict[str, dict]:
    predictions = []
    for fold_result in fold_results:
        predictions.extend(fold_result.predictions)
    return _prediction_breakdown(predictions, dimension, higher_is_risk=higher_is_risk)


def _prediction_breakdown(
    predictions: list, dimension: str, *, higher_is_risk: bool
) -> dict[str, dict]:
    grouped: dict[str, list] = defaultdict(list)
    for prediction in predictions:
        key = getattr(prediction, dimension, None) or "unknown"
        if prediction.actual_label is None or prediction.actual_value is None:
            continue
        grouped[str(key)].append(prediction)
    return {
        key: _prediction_metric_summary(items, higher_is_risk=higher_is_risk)
        for key, items in sorted(grouped.items())
        if items
    }


def _prediction_metric_summary(predictions: list, *, higher_is_risk: bool) -> dict:
    observations = [
        RiskBucketObservation(
            symbol=prediction.symbol,
            score=prediction.calibrated_score,
            future_max_drawdown_20d=float(prediction.actual_value),
        )
        for prediction in predictions
        if prediction.actual_value is not None
    ]
    if len(observations) < 2:
        return {"n_predictions": len(observations)}
    try:
        evaluation = evaluate_risk_bucket_usefulness(
            observations,
            top_fraction=0.2,
            event_drawdown_threshold=-0.08,
            higher_is_risk=higher_is_risk,
        )
    except ValueError:
        return {"n_predictions": len(observations)}
    return {
        "n_predictions": len(observations),
        "auc_mean": None
        if evaluation.auc_roc is None
        else round(evaluation.auc_roc, 6),
        "ece_mean": None
        if evaluation.expected_calibration_error is None
        else round(evaluation.expected_calibration_error, 6),
        "brier_mean": None
        if evaluation.brier_score is None
        else round(evaluation.brier_score, 6),
        "alert_precision_mean": None
        if evaluation.alert_precision is None
        else round(evaluation.alert_precision, 6),
        "drawdown_lift_mean": round(evaluation.drawdown_lift, 6),
    }


def _compute_evaluation(results_data: dict) -> dict:
    eval_out: dict = {
        "training_run_id": results_data.get("run_label"),
        "sample_snapshot_hash": results_data.get("sample_snapshot_hash"),
        "generated_at": results_data.get("generated_at"),
        "target_name": results_data.get("target_name"),
        "data_source": results_data.get("data_source"),
        "training_profile": results_data.get("training_profile"),
        "feature_contract_version": results_data.get("feature_contract_version"),
        "label_set_version": results_data.get("label_set_version"),
        "included_markets": results_data.get("included_markets", []),
        "excluded_markets": results_data.get("excluded_markets", []),
        "deployment_roles": results_data.get("deployment_roles", {}),
        "models": {},
        "regime_deltas": {},
        "task_matrix": {},
    }
    for model in results_data.get("models", []):
        mn = model["trainer_name"]
        ece, brier, auc, prec, dl = [], [], [], [], []
        for fold in model.get("folds", []):
            m = fold.get("metrics", {})
            if "expected_calibration_error" in m:
                ece.append(m["expected_calibration_error"])
            if "brier_score" in m:
                brier.append(m["brier_score"])
            if "auc_roc" in m:
                auc.append(m["auc_roc"])
            if "top_bucket_alert_precision" in m:
                prec.append(m["top_bucket_alert_precision"])
            if "top_bucket_drawdown_lift" in m:
                dl.append(m["top_bucket_drawdown_lift"])
        eval_out["models"][mn] = {
            "ece_mean": round(sum(ece) / len(ece), 4) if ece else None,
            "brier_mean": round(sum(brier) / len(brier), 4) if brier else None,
            "auc_mean": round(sum(auc) / len(auc), 4) if auc else None,
            "alert_precision_mean": round(sum(prec) / len(prec), 4) if prec else None,
            "drawdown_lift_mean": round(sum(dl) / len(dl), 4) if dl else None,
            "eligible": model["eligible_for_approval"],
        }

    table_models = [
        m
        for m in results_data["models"]
        if m["algorithm_family"].lower()
        not in ("patchtst", "tcn", "itransformer", "linear_baseline", "deep_mlp")
    ]
    best_table = max(
        table_models,
        key=lambda m: eval_out["models"].get(m["trainer_name"], {}).get("auc_mean", 0),
        default=None,
    )
    best_name = best_table["trainer_name"] if best_table else None
    eval_out["best_table_model"] = best_name

    if best_table:
        best_fold_map = {f["fold_id"]: f for f in best_table.get("folds", [])}
        for model in results_data["models"]:
            af = model["algorithm_family"].lower()
            if af in ("patchtst", "tcn", "itransformer"):
                wins = 0
                for dfold in model.get("folds", []):
                    tfold = best_fold_map.get(dfold["fold_id"])
                    if tfold:
                        da = dfold.get("metrics", {}).get("auc_roc", 0)
                        ta = tfold.get("metrics", {}).get("auc_roc", 0)
                        if da - ta >= 0.03:
                            wins += 1
                eval_out["regime_deltas"][model["trainer_name"]] = {
                    "regime_wins_vs_table": wins,
                    "eligible_deep": wins >= 2,
                }

    for task_name, task_payload in results_data.get("task_matrix", {}).items():
        eval_out["task_matrix"][task_name] = {
            "models": _evaluate_model_list(task_payload.get("models", [])),
            "regime_breakdown": task_payload.get("regime_breakdown", {}),
            "recent_window_breakdown": task_payload.get("recent_window_breakdown", {}),
        }

    return eval_out


def _evaluate_model_list(models: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for model in models:
        mn = model["trainer_name"]
        ece: list[float] = []
        brier: list[float] = []
        auc: list[float] = []
        precision: list[float] = []
        drawdown_lift: list[float] = []
        for fold in model.get("folds", []):
            metrics = fold.get("metrics", {})
            if "expected_calibration_error" in metrics:
                ece.append(metrics["expected_calibration_error"])
            if "brier_score" in metrics:
                brier.append(metrics["brier_score"])
            if "auc_roc" in metrics:
                auc.append(metrics["auc_roc"])
            if "top_bucket_alert_precision" in metrics:
                precision.append(metrics["top_bucket_alert_precision"])
            if "top_bucket_drawdown_lift" in metrics:
                drawdown_lift.append(metrics["top_bucket_drawdown_lift"])
        out[mn] = {
            "ece_mean": round(sum(ece) / len(ece), 4) if ece else None,
            "brier_mean": round(sum(brier) / len(brier), 4) if brier else None,
            "auc_mean": round(sum(auc) / len(auc), 4) if auc else None,
            "alert_precision_mean": round(sum(precision) / len(precision), 4)
            if precision
            else None,
            "drawdown_lift_mean": round(sum(drawdown_lift) / len(drawdown_lift), 4)
            if drawdown_lift
            else None,
            "eligible": model.get("eligible_for_approval", False),
        }
    return out


def _coverage_group_distribution(samples: list) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        counts[sample.coverage_group.value] += 1
    return dict(sorted(counts.items()))


def _universe_distribution() -> dict[str, dict[str, dict[str, int] | int]]:
    out: dict[str, dict[str, dict[str, int] | int]] = {}
    for preset in UNIVERSE_PRESETS.values():
        market = preset.market.value
        current = out.setdefault(
            market, {"symbol_count": 0, "instrument_type": {}, "coverage_group": {}}
        )
        current["symbol_count"] = int(current["symbol_count"]) + 1
        instrument_type = current["instrument_type"]
        coverage_group = current["coverage_group"]
        assert isinstance(instrument_type, dict)
        assert isinstance(coverage_group, dict)
        instrument_type[preset.instrument_type.value] = (
            instrument_type.get(preset.instrument_type.value, 0) + 1
        )
        coverage_group[preset.coverage_group.value] = (
            coverage_group.get(preset.coverage_group.value, 0) + 1
        )
    return dict(sorted(out.items()))


def _reference_missing_rates(samples: list) -> dict[str, dict[str, int | float]]:
    feature_names = [
        "benchmark_ret_20d",
        "relative_strength_20d",
        "sector_ret_20d",
        "sector_relative_strength_20d",
        "style_ret_20d",
        "style_relative_strength_20d",
    ]
    total = len(samples)
    out: dict[str, dict[str, int | float]] = {}
    for feature_name in feature_names:
        missing = sum(
            1
            for sample in samples
            if feature_name in getattr(sample, "missing_features", [])
        )
        out[feature_name] = {
            "missing_count": missing,
            "missing_ratio": round(missing / total, 4) if total else 0.0,
        }
    return out


def _samples_for_task(samples: list, task_name: str) -> list:
    if task_name not in EVENT_CONDITIONED_TASKS:
        return samples
    return [
        sample
        for sample in samples
        if getattr(sample.labels, task_name, None) is not None
    ]


def _task_sample_summary(samples: list, task_name: str) -> dict[str, int | float | str]:
    unique_dates = {sample.as_of_date for sample in samples}
    symbols = {sample.symbol for sample in samples}
    return {
        "task_name": task_name,
        "sample_count": len(samples),
        "symbol_count": len(symbols),
        "unique_date_count": len(unique_dates),
        "event_conditioned": task_name in EVENT_CONDITIONED_TASKS,
    }


def _has_min_task_span(samples: list) -> bool:
    return len({sample.as_of_date for sample in samples}) >= MIN_TASK_UNIQUE_DATES


def _force_deep_models_research_only(models: list[dict]) -> None:
    for model in models:
        if not _is_deep_research_only(
            model.get("trainer_name", ""), model.get("algorithm_family", "")
        ):
            continue
        model["eligible_for_approval"] = False
        model["deployment_status"] = "research_only"
        model["approval_override_reason"] = (
            "deep_models_research_only_until_event_and_regime_governance_stabilizes"
        )


def _force_non_approvable_primary_models_research_only(models: list[dict]) -> None:
    for model in models:
        if _is_approvable_primary_trainer(model.get("trainer_name", "")):
            continue
        model["eligible_for_approval"] = False
        model["deployment_status"] = "research_only"
        model["approval_override_reason"] = "trainer_not_in_primary_approval_queue"


def _is_approvable_primary_trainer(trainer_name: str) -> bool:
    return trainer_name.lower() in APPROVABLE_PRIMARY_TRAINERS


def _is_deep_research_only(trainer_name: str, algorithm_family: str) -> bool:
    normalized_name = trainer_name.lower()
    normalized_family = algorithm_family.lower()
    return normalized_family in {
        "deep_learning",
        "patchtst",
        "tcn",
        "itransformer",
    } or normalized_name in {
        "deep-mlp",
        "patchtst",
        "tcn",
        "itransformer",
    }


def _event_feature_coverage(samples: list) -> dict[str, float]:
    if not samples:
        return {}
    feature_names = [
        "event_score_1d",
        "event_score_7d",
        "event_score_30d",
        "negative_event_score_7d",
        "official_event_score_30d",
        "earnings_surprise_score_30d",
        "guidance_cut_flag_30d",
        "regulatory_risk_score_30d",
        "mna_event_flag_30d",
        "filing_8k_count_30d",
    ]
    coverage: dict[str, float] = {}
    for feature_name in feature_names:
        non_zero = sum(
            1
            for sample in samples
            if abs(sample.features.get(feature_name, 0.0)) > 1e-12
        )
        coverage[feature_name] = round(non_zero / len(samples), 4)
    return coverage


def _report_regime_breakdown(report) -> dict[str, dict]:
    audit = getattr(report, "audit", None)
    if audit is None:
        return {}
    return {
        item.regime: {
            "fold_count": item.fold_count,
            "validation_prediction_count": item.validation_prediction_count,
            "validation_start": None
            if item.validation_start is None
            else item.validation_start.isoformat(),
            "validation_end": None
            if item.validation_end is None
            else item.validation_end.isoformat(),
        }
        for item in audit.regime_coverage
    }


def _recent_window_breakdown(report, *, window_count: int = 2) -> dict[str, list[dict]]:
    breakdown: dict[str, list[dict]] = {}
    for result in report.results:
        recent_folds = sorted(
            result.fold_results, key=lambda fold_result: fold_result.fold.validation_end
        )[-window_count:]
        breakdown[result.trainer_name] = [
            {
                "fold_id": fold_result.fold.fold_id,
                "validation_end": fold_result.fold.validation_end.isoformat(),
                "regime": fold_result.fold.regime,
                "metrics": {
                    metric.metric_name: metric.metric_value
                    for metric in fold_result.metrics
                },
            }
            for fold_result in recent_folds
        ]
    return breakdown


def _write_model_cards(cards: list[dict], *, artifact_root: Path):
    active_filenames = {
        f"model_card_{card['task_name']}__{card['trainer_name']}.json" for card in cards
    }
    _archive_stale_model_cards(active_filenames, artifact_root=artifact_root)
    for card in cards:
        card_path = (
            artifact_root
            / f"model_card_{card['task_name']}__{card['trainer_name']}.json"
        )
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2, ensure_ascii=False, default=str)
    with open(artifact_root / "model_cards.json", "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False, default=str)


def _archive_stale_model_cards(
    active_filenames: set[str], *, artifact_root: Path
) -> None:
    stale_paths = [
        path
        for path in artifact_root.glob("model_card_*.json")
        if path.name not in active_filenames
    ]
    if not stale_paths:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = artifact_root / "archive" / f"stale_model_cards_{stamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in stale_paths:
        path.replace(archive_dir / path.name)


def _deployment_roles_for_results(results_data: dict) -> dict:
    approved = [
        model
        for model in results_data.get("models", [])
        if model.get("eligible_for_approval")
    ]
    champion = next(
        (model for model in approved if model.get("trainer_name") == "linear-baseline"),
        None,
    )
    metric_eligible_challengers = [
        model for model in approved if model.get("trainer_name") != "linear-baseline"
    ]
    challenger_allowed = not bool(
        results_data.get("reference_risk_flag")
    ) and _required_regimes_present(results_data.get("regime_breakdown", {}))
    approved_challengers = (
        metric_eligible_challengers if challenger_allowed else []
    )
    primary = _select_primary_model(
        champion=champion,
        approved_challengers=approved_challengers,
    )
    return {
        "primary_model": None if primary is None else primary.get("trainer_name"),
        "champion_fallback": None
        if champion is None
        else champion.get("trainer_name"),
        "approved_challengers": [
            model.get("trainer_name") for model in approved_challengers
        ],
        "conditional_models": [
            model.get("trainer_name")
            for model in metric_eligible_challengers
            if model not in approved_challengers
        ],
        "research_only_models": [
            model.get("trainer_name")
            for model in results_data.get("models", [])
            if not model.get("eligible_for_approval")
        ],
        "primary_challenger_allowed": challenger_allowed,
    }


def _write_invest_config(results_data: dict, *, artifact_root: Path):
    approved = [
        m for m in results_data.get("models", []) if m.get("eligible_for_approval")
    ]
    champion = next(
        (m for m in approved if m.get("trainer_name") == "linear-baseline"), None
    )
    metric_eligible_challengers = [
        m for m in approved if m.get("trainer_name") != "linear-baseline"
    ]
    allow_primary_challenger = not bool(
        results_data.get("reference_risk_flag")
    ) and _required_regimes_present(results_data.get("regime_breakdown", {}))
    approved_challengers = (
        metric_eligible_challengers if allow_primary_challenger else []
    )
    conditional_challengers = (
        [] if allow_primary_challenger else metric_eligible_challengers
    )
    deployable_approved = (
        [champion] if champion is not None else []
    ) + approved_challengers
    primary = _select_primary_model(
        champion=champion,
        approved_challengers=approved_challengers,
    )
    research_only = [
        m for m in results_data.get("models", []) if not m.get("eligible_for_approval")
    ]
    config = {
        "primary_model": None
        if primary is None
        else _model_config_entry(primary, results_data, role="primary"),
        "champion_fallback": None
        if champion is None
        else _model_config_entry(champion, results_data, role="champion_fallback"),
        "champion_model": None
        if champion is None
        else _model_config_entry(champion, results_data, role="champion"),
        "approved_challengers": [
            _model_config_entry(m, results_data, role="approved_challenger")
            for m in approved_challengers
        ],
        "conditional_models": [
            {
                **_model_config_entry(m, results_data, role="conditional"),
                "status": "conditional",
                "condition": "blocked_by_reference_or_regime_guardrail",
            }
            for m in conditional_challengers
        ],
        "research_only_models": [
            {
                "model_id": m.get("model_id"),
                "trainer_name": m.get("trainer_name"),
                "algorithm_family": m.get("algorithm_family"),
                "target": results_data.get("target_name", ""),
                "n_folds": len(m.get("folds", [])),
                "status": "research_only",
            }
            for m in research_only
        ],
        "approved_models": [
            _model_config_entry(
                m,
                results_data,
                role=(
                    "champion"
                    if m.get("trainer_name") == "linear-baseline"
                    else "approved_challenger"
                ),
            )
            for m in deployable_approved
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "approval_summary": {
            "primary_model": None if primary is None else primary.get("trainer_name"),
            "primary_challenger_allowed": allow_primary_challenger,
            "approved_model_count": len(deployable_approved),
            "approved_challenger_count": len(approved_challengers),
            "metric_eligible_challenger_count": len(metric_eligible_challengers),
            "conditional_model_count": len(conditional_challengers),
            "message": (
                "0 approved challengers"
                if not approved_challengers
                else f"{len(approved_challengers)} approved challengers"
            ),
        },
    }
    with open(artifact_root / "invest_agent_models.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False, default=str)
    print(
        f"  Approved deployable models: {len(deployable_approved)} (challengers={len(approved_challengers)})"
    )


def _select_primary_model(
    *, champion: dict | None, approved_challengers: list[dict]
) -> dict | None:
    random_forest = next(
        (
            model
            for model in approved_challengers
            if model.get("trainer_name") == "random-forest"
        ),
        None,
    )
    if random_forest is not None:
        return random_forest
    return approved_challengers[0] if approved_challengers else champion


def _model_config_entry(model: dict, results_data: dict, *, role: str) -> dict:
    return {
        "model_id": model["model_id"],
        "trainer_name": model["trainer_name"],
        "algorithm_family": model["algorithm_family"],
        "target": results_data.get("target_name", ""),
        "n_folds": len(model.get("folds", [])),
        "status": "approved",
        "deployment_role": role,
    }


def _required_regimes_present(regime_breakdown: dict) -> bool:
    required = {"bull", "bear", "range", "high_vol"}
    return required.issubset(set(regime_breakdown))


def write_tuning_log(
    *, profile: str, data_source: str, authoritative: bool, run_label: str
):
    tuning = {
        "version": 2,
        "data": data_source,
        "data_description": (
            "Real bundles from fetch_real_data.py/fetch_real_events.py"
            if data_source == "real"
            else "Synthetic: momentum(0.03), GARCH vol(0.85α), Markov regime switching(bull/bear/range)"
        ),
        "profile": profile,
        "training_budget": _training_budget(profile=profile),
        "models_trained": 9 if profile == "full" else len(default_trainer_specs()),
        "promotion_gate_config": {
            "minimum_alert_precision": 0.50,
            "primary_metric": "top_bucket_drawdown_lift",
        },
        "deep_model_gate": "beat best table AUROC ≥0.03 in ≥2 regimes",
    }
    target_dir = AUDITS if authoritative else RUNS / run_label
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(target_dir / "tuning_log.json", "w", encoding="utf-8") as f:
        json.dump(tuning, f, indent=2, ensure_ascii=False, default=str)


def _training_budget(*, profile: str) -> dict:
    budget = {
        "walk_forward": {
            "train_window_days": 180,
            "validation_window_days": 60,
            "step_days": 30,
        },
        "profile": profile,
    }
    if profile == "full":
        budget["deep_models"] = {
            "max_epochs": int(
                os.environ.get(
                    "INVESTMENT_RESEARCH_DEEP_MAX_EPOCHS", DEFAULT_DEEP_MAX_EPOCHS
                )
            ),
            "patience": int(
                os.environ.get(
                    "INVESTMENT_RESEARCH_DEEP_PATIENCE", DEFAULT_DEEP_PATIENCE
                )
            ),
            "max_samples": int(
                os.environ.get(
                    "INVESTMENT_RESEARCH_DEEP_MAX_SAMPLES", DEFAULT_DEEP_MAX_SAMPLES
                )
            ),
        }
    return budget


# =========================================================================
#  Main
# =========================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run enhanced retraining.")
    parser.add_argument(
        "--data-source",
        choices=("synthetic", "real", "auto"),
        default=os.environ.get("INVESTMENT_RESEARCH_TRAINING_DATA_SOURCE", "real"),
        help="synthetic builds deterministic sandbox bundles; real reuses fetched real bundles; auto prefers real then falls back.",
    )
    parser.add_argument(
        "--profile",
        choices=("quick", "full"),
        default=os.environ.get("INVESTMENT_RESEARCH_TRAINING_PROFILE", "quick"),
        help="quick trains table/baseline models; full also trains deep time-series models.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    random.seed(RANDOM_SEED)
    for d in [OUTPUT, TEMP, AUDITS, RUNS]:
        d.mkdir(parents=True, exist_ok=True)
    run_label = _run_label(data_source=args.data_source, profile=args.profile)
    authoritative = _authoritative_run(
        data_source=args.data_source, profile=args.profile
    )
    artifact_root = _artifact_root(authoritative=authoritative, run_label=run_label)
    started_at = time.time()

    print("=" * 60)
    print(" Task 7: Enhanced retraining + promotion gate tuning")
    print(f" Profile: {args.profile}")
    print(f" Data source: {args.data_source}")
    print(f" Authoritative artifacts: {authoritative}")
    print(f" Artifact root: {artifact_root}")
    print("=" * 60)

    bundles = phase_a(data_source=args.data_source)
    market_eligibility = assess_market_eligibility(
        bundles=bundles, data_source=args.data_source
    )
    included_markets = sorted(
        market
        for market, record in market_eligibility.items()
        if record.get("included")
    )
    excluded_markets = sorted(
        market
        for market, record in market_eligibility.items()
        if not record.get("included")
    )
    excluded_market_reasons = {
        market: list(record.get("reason", []))
        for market, record in market_eligibility.items()
        if not record.get("included")
    }
    print(f" Included markets: {included_markets}")
    if excluded_markets:
        print(f" Excluded markets: {excluded_market_reasons}")

    samples_path = phase_b(
        bundles,
        authoritative=authoritative,
        artifact_root=artifact_root,
        market_eligibility=market_eligibility,
    )
    results_data = phase_c_e(
        samples_path,
        profile=args.profile,
        data_source=args.data_source,
        authoritative=authoritative,
        artifact_root=artifact_root,
        run_label=run_label,
    )
    write_tuning_log(
        profile=args.profile,
        data_source=args.data_source,
        authoritative=authoritative,
        run_label=run_label,
    )
    _write_training_status(
        run_label=run_label,
        data_source=args.data_source,
        profile=args.profile,
        authoritative=authoritative,
        included_markets=included_markets,
        excluded_markets=excluded_markets,
        excluded_market_reasons=excluded_market_reasons,
        market_eligibility=market_eligibility,
        duration_seconds=time.time() - started_at,
    )
    if authoritative:
        _run_audits()

    print("\n" + "=" * 60)
    print(" RETRAINING COMPLETE")
    print("=" * 60)

    if results_data:
        for model in results_data.get("models", []):
            status = "ELIGIBLE" if model["eligible_for_approval"] else "not eligible"
            print(f"  {model['trainer_name']:25s} folds={len(model['folds'])} {status}")

    print("\nOutput files:")
    for p in sorted(artifact_root.glob("*")):
        print(f"  {p}")
    print("\nAudit files:")
    for p in sorted(AUDITS.glob("*")):
        print(f"  {p}")
