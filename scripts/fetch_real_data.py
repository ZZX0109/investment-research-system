#!/usr/bin/env python3
"""Priority 1: Real market data pipeline — fetch daily OHLCV from yfinance.

Features:
- Rate-limited (1.0s per ticker, 2s per market pause)
- Checkpoint/retry: intermediate CSV per market, skip completed tickers
- Retry: 3 attempts with 2^n backoff
- Date range: 2020-01-01 through the current Asia/Shanghai trading date
- Output: bundle_{us,cn,hk,jp}.pkl (CanonicalDatasetBundle-compatible)
- Validation: symbol count, trading days, NaN checks
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import time
import csv
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = Path(os.environ.get("INVESTMENT_RESEARCH_OUTPUT_DIR", PROJECT / "output"))
SCRIPTS = PROJECT / "scripts"
TEMP = Path(os.environ.get("INVESTMENT_RESEARCH_TEMP_DIR", PROJECT / "temp"))
INTERMEDIATE = TEMP / "fetch_intermediate"

sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.catalog import (
    TARGET_MARKET_TYPE_COUNTS,
    UNIVERSE_PRESETS,
    iter_market_presets,
    market_symbols,
)
from investment_research.training.real_data import AksharePriceFetcher
from investment_research.training.sources import normalize_yfinance_rows, normalize_akshare_rows

MARKET_SYMBOLS: dict[str, list[str]] = {
    market.value: market_symbols(market)
    for market in TARGET_MARKET_TYPE_COUNTS
}

START_DATE = os.environ.get("INVESTMENT_RESEARCH_FETCH_START_DATE", "2020-01-01")
END_DATE = os.environ.get(
    "INVESTMENT_RESEARCH_FETCH_END_DATE",
    (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)).isoformat(),
)
TICKER_DELAY = 1.0
MARKET_DELAY = 2.0
MAX_RETRIES = 3


def fetch_ticker(symbol: str, *, market: str) -> tuple[list[dict], str]:
    """Fetch OHLCV for a single ticker with retry and backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if market == "cn":
                return _fetch_akshare_ticker(symbol), "akshare"
            return _fetch_yfinance_ticker(symbol), "yfinance"
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [{symbol}] attempt {attempt}/{MAX_RETRIES} failed: {e} — waiting {wait}s")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    if market == "cn":
        print(f"  [{symbol}] akshare exhausted; trying yfinance fallback...")
        return _fetch_cn_yfinance_fallback(symbol), "yfinance_fallback"
    return [], "unavailable"


def _fetch_yfinance_ticker(symbol: str) -> list[dict]:
    import yfinance as yf

    tk = yf.Ticker(symbol)
    df = tk.history(start=START_DATE, end=END_DATE, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"Empty dataframe for {symbol}")
    rows = []
    for idx, row in df.iterrows():
        dt = idx.date() if hasattr(idx, "date") else idx
        adj_close = row["Adj Close"] if "Adj Close" in row else row["Close"]
        rows.append({
            "date": dt,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "adj_close": float(adj_close),
            "adjusted_close": float(adj_close),
            "volume": float(row.get("Volume", 0)),
            "published_at": datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc),
        })
    return rows


def _fetch_cn_yfinance_fallback(symbol: str) -> list[dict]:
    yahoo_symbol = _to_yfinance_cn_symbol(symbol)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            rows = _fetch_yfinance_ticker(yahoo_symbol)
            if rows:
                print(f"  [{symbol}] yfinance fallback OK via {yahoo_symbol}: {len(rows)} rows")
                return rows
        except Exception as e:
            wait = 2 ** attempt
            print(f"  [{symbol}] yfinance fallback attempt {attempt}/{MAX_RETRIES} failed: {e} — waiting {wait}s")
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    return []


def _to_yfinance_cn_symbol(symbol: str) -> str:
    if symbol.endswith(".SH"):
        return f"{symbol[:-3]}.SS"
    if symbol.endswith(".SZ"):
        return symbol
    return symbol


def _fetch_akshare_ticker(symbol: str) -> list[dict]:
    fetcher = AksharePriceFetcher()
    raw_rows = fetcher.fetch_price_rows(
        symbol,
        start=date.fromisoformat(START_DATE),
        end=date.fromisoformat(END_DATE),
    )
    if not raw_rows:
        raise RuntimeError(f"Empty dataframe for {symbol}")
    rows = []
    for row in raw_rows:
        trade_date = _coerce_date(row.trade_date)
        rows.append({
            "date": trade_date,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "adj_close": float(row.adjusted_close if row.adjusted_close is not None else row.close),
            "adjusted_close": float(row.adjusted_close if row.adjusted_close is not None else row.close),
            "volume": float(row.volume or 0),
            "published_at": _coerce_datetime(row.published_at or trade_date),
        })
    return rows


def _coerce_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise ValueError(f"Unsupported date value: {value!r}")


def _coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise ValueError(f"Unsupported datetime value: {value!r}")


def load_checkpoint(market: str, expected_symbols: list[str]) -> tuple[dict[str, list[dict]], set[str]]:
    """Load intermediate CSV and return {symbol: rows} and set of completed symbols."""
    csv_path = INTERMEDIATE / f"market_{market}.csv"
    if not csv_path.exists():
        return {}, set()
    allowed_symbols = set(expected_symbols)
    completed = set()
    data: dict[str, list[dict]] = {}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = row["symbol"]
                if sym not in allowed_symbols:
                    continue
                completed.add(sym)
                if sym not in data:
                    data[sym] = []
                data[sym].append({
                    "date": date.fromisoformat(row["trade_date"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "adj_close": float(row["adj_close"]),
                    "adjusted_close": float(row["adj_close"]),
                    "volume": float(row["volume"]),
                    "published_at": datetime.combine(date.fromisoformat(row["trade_date"]), datetime.min.time(), tzinfo=timezone.utc),
                })
        print(f"  Checkpoint loaded: {len(completed)} symbols, {sum(len(v) for v in data.values())} rows")
    except Exception as e:
        print(f"  Checkpoint load failed: {e}, starting fresh")
        return {}, set()
    return data, completed


def save_checkpoint(market: str, all_data: dict[str, list[dict]]):
    """Save intermediate CSV for resumability."""
    csv_path = INTERMEDIATE / f"market_{market}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "trade_date", "open", "high", "low", "close", "adj_close", "volume"])
        for sym in sorted(all_data):
            for row in all_data[sym]:
                writer.writerow([
                    sym, row["date"].isoformat(),
                    row["open"], row["high"], row["low"], row["close"],
                    row["adj_close"], row["volume"],
                ])


def validate_bundle(
    market: str,
    symbols: list[str],
    all_data: dict[str, list[dict]],
    provider_by_symbol: dict[str, str],
) -> dict:
    """Validate the fetched bundle."""
    fetched_syms = sorted(all_data)
    missing = [s for s in symbols if s not in fetched_syms]
    expected_distribution = {
        instrument_type.value: count
        for instrument_type, count in TARGET_MARKET_TYPE_COUNTS[iter_market_presets(market)[0].market].items()
    }
    actual_distribution_counter = Counter(
        UNIVERSE_PRESETS[symbol].instrument_type.value for symbol in fetched_syms if symbol in UNIVERSE_PRESETS
    )
    actual_distribution = dict(actual_distribution_counter)
    report = {
        "market": market,
        "expected_symbols": len(symbols),
        "fetched_symbols": len(fetched_syms),
        "missing_symbols": missing,
        "total_rows": sum(len(v) for v in all_data.values()),
        "expected_distribution": expected_distribution,
        "actual_distribution": actual_distribution,
        "quota_complete": len(missing) == 0 and actual_distribution == expected_distribution,
        "provider_by_symbol": provider_by_symbol,
        "provider_usage": dict(Counter(provider_by_symbol.values())),
        "per_symbol": {},
        "nan_issues": [],
    }
    for sym in sorted(all_data):
        rows = all_data[sym]
        trading_days = len(rows)
        nan_count = 0
        for r in rows:
            for field in ["open", "high", "low", "close", "adj_close", "volume"]:
                v = r[field]
                if v is None or (isinstance(v, float) and (v != v)):
                    nan_count += 1
        report["per_symbol"][sym] = {"trading_days": trading_days, "nan_count": nan_count}
        if nan_count > 0:
            report["nan_issues"].append({"symbol": sym, "nan_count": nan_count})
    return report


def build_bundle_pkl(market: str, all_data: dict[str, list[dict]], provider_by_symbol: dict[str, str]):
    """Normalize and save as CanonicalDatasetBundle."""
    all_instruments = []
    all_bars = []
    all_events = []

    for sym in sorted(all_data):
        rows = all_data[sym]
        is_cn = market == "cn"
        normalizer = normalize_akshare_rows if is_cn else normalize_yfinance_rows
        try:
            bundle = normalizer(symbol=sym, rows=rows)
        except Exception as e:
            print(f"  Normalize FAIL {sym}: {e}")
            continue
        for bar in bundle.price_bars:
            bar.data_version = f"bundle_{market}"
            bar.provider = provider_by_symbol.get(sym, bar.provider)
            bar.as_of = bar.published_at
            if bar.raw_hash is None:
                bar.raw_hash = _hash_payload(
                    {
                        "symbol": bar.symbol,
                        "trade_date": bar.trade_date.isoformat(),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "adjusted_close": bar.adjusted_close,
                        "volume": bar.volume,
                    }
                )
            if bar.normalized_hash is None:
                bar.normalized_hash = _hash_payload(
                    {
                        "symbol": bar.symbol,
                        "trade_date": bar.trade_date.isoformat(),
                        "close": bar.close,
                        "adjusted_close": bar.adjusted_close,
                        "currency": bar.currency,
                        "provider": bar.provider,
                    }
                )
        all_instruments.append(bundle.instrument)
        all_bars.extend(bundle.price_bars)
        all_events.extend(bundle.events)

    data = {
        "market": market,
        "instruments": all_instruments,
        "price_bars": all_bars,
        "events": all_events,
        "created_at": datetime.now(timezone.utc),
        "source": "real:yfinance+akshare",
        "source_meta": {
            "mode": "real",
            "provider": "real:yfinance+akshare",
            "synthetic_ratio": 0.0,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "overrides": [],
            "provider_by_symbol": provider_by_symbol,
            "provider_usage": dict(Counter(provider_by_symbol.values())),
        },
    }
    pkl_path = OUTPUT / f"bundle_{market}.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(data, f)
    print(f"  Bundle saved: {pkl_path} ({len(all_instruments)} instruments, {len(all_bars)} bars)")


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch real market OHLCV bundles with checkpoints.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit successfully even if some expected symbols are still missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    import yfinance
    print(f"yfinance version: {yfinance.__version__}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    INTERMEDIATE.mkdir(parents=True, exist_ok=True)

    validation_report: dict[str, dict] = {}

    selected_markets = set(filter(None, os.environ.get("INVESTMENT_RESEARCH_MARKETS", "").split(",")))
    for market, symbols in MARKET_SYMBOLS.items():
        if selected_markets and market not in selected_markets:
            continue
        print(f"\n{'='*50}")
        print(f" Market: {market.upper()} ({len(symbols)} symbols)")
        print(f"{'='*50}")

        existing_data, completed = load_checkpoint(market, symbols)
        provider_by_symbol: dict[str, str] = {}
        remaining = [s for s in symbols if s not in completed]

        if not remaining:
            print(f"  All {len(symbols)} symbols already fetched from checkpoint.")
        else:
            print(f"  {len(completed)} cached, {len(remaining)} to fetch: {remaining}")
            for i, sym in enumerate(remaining):
                print(f"  [{i+1}/{len(remaining)}] Fetching {sym}...")
                rows, provider_name = fetch_ticker(sym, market=market)
                if rows:
                    existing_data[sym] = rows
                    provider_by_symbol[sym] = provider_name
                    print(f"    OK: {len(rows)} rows")
                else:
                    provider_by_symbol[sym] = provider_name
                    print(f"    FAIL: no data after {MAX_RETRIES} retries")
                save_checkpoint(market, existing_data)
                if i < len(remaining) - 1:
                    time.sleep(TICKER_DELAY)
            time.sleep(MARKET_DELAY)

        for sym in completed:
            provider_by_symbol.setdefault(sym, "checkpoint")

        validation = validate_bundle(market, symbols, existing_data, provider_by_symbol)
        validation_report[market] = validation
        print(json.dumps(validation, indent=2, default=str))

        build_bundle_pkl(market, existing_data, provider_by_symbol)

    # Write validation report
    report_path = TEMP / "fetch_validation.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(validation_report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nValidation report: {report_path}")

    # Summary
    total_symbols = sum(len(v) for v in MARKET_SYMBOLS.values())
    fetched = sum(r["fetched_symbols"] for r in validation_report.values())
    print(f"\nDone: {fetched}/{total_symbols} symbols fetched across 4 markets.")
    missing_by_market = {
        market: report["missing_symbols"]
        for market, report in validation_report.items()
        if report.get("missing_symbols")
    }
    if missing_by_market and not args.allow_partial:
        print(f"ERROR: missing symbols after fetch: {missing_by_market}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
