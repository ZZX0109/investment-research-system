#!/usr/bin/env python3
"""Priority 1: Fetch real benchmark data (sector ETFs, style indices).

- US: XLK(tech)/XLF(financial)/XLE(energy) → sector benchmarks; QQQ/SPY → style
- CN: CSI sector indices via akshare
- HK: HK sector ETFs
- JP: TSE sector indices
Output: benchmarks.pkl (dict[market][symbol] → list[CanonicalPriceBar])
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "output"
TEMP = PROJECT / "temp"

sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.catalog import (
    UNIVERSE_PRESETS,
    benchmark_reference_symbols,
    iter_market_presets,
)
from investment_research.training.sources import (
    normalize_yfinance_rows,
    normalize_akshare_rows,
)

START_DATE = "2020-01-01"
END_DATE = os.environ.get(
    "INVESTMENT_RESEARCH_FETCH_END_DATE",
    (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)).isoformat(),
)
TICKER_DELAY = 1.0
MAX_RETRIES = 3

BENCHMARK_MAP = {
    market: sorted(
        symbol
        for symbol in benchmark_reference_symbols()
        if any(preset.symbol == symbol for preset in iter_market_presets(market))
    )
    for market in ("us", "cn", "hk", "jp")
}


def fetch_benchmark_rows(symbol: str, *, market: str) -> list[dict]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if market == "cn":
                import akshare as ak

                code = symbol.replace(".SH", "").replace(".SZ", "")
                preset = UNIVERSE_PRESETS[symbol]
                if preset.instrument_type.value == "etf":
                    frame = ak.fund_etf_hist_em(
                        symbol=code,
                        period="daily",
                        start_date=datetime.fromisoformat(START_DATE).strftime(
                            "%Y%m%d"
                        ),
                        end_date=datetime.fromisoformat(END_DATE).strftime("%Y%m%d"),
                        adjust="",
                    )
                else:
                    frame = ak.index_zh_a_hist(
                        symbol=code,
                        period="daily",
                        start_date=datetime.fromisoformat(START_DATE).strftime(
                            "%Y%m%d"
                        ),
                        end_date=datetime.fromisoformat(END_DATE).strftime("%Y%m%d"),
                    )
                rows = []
                for _, row in frame.iterrows():
                    rows.append(
                        {
                            "日期": str(row.get("日期")),
                            "开盘": float(row.get("开盘")),
                            "最高": float(row.get("最高")),
                            "最低": float(row.get("最低")),
                            "收盘": float(row.get("收盘")),
                            "复权收盘": float(row.get("收盘")),
                            "成交量": float(row.get("成交量", 0)),
                            "更新时间": f"{row.get('日期')}T15:00:00+08:00",
                        }
                    )
                return rows
            import yfinance as yf

            tk = yf.Ticker(symbol)
            df = tk.history(start=START_DATE, end=END_DATE, auto_adjust=False)
            if df.empty:
                raise RuntimeError(f"Empty dataframe for {symbol}")
            rows = []
            for idx, row in df.iterrows():
                dt = idx if isinstance(idx, date) else idx.date()
                rows.append(
                    {
                        "date": dt,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "adj_close": float(row.get("Close", row["Close"])),
                        "volume": float(row.get("Volume", 0)),
                        "published_at": datetime.combine(
                            dt, datetime.min.time(), tzinfo=timezone.utc
                        ),
                    }
                )
            return rows
        except Exception as e:
            wait = 2**attempt
            print(
                f"  [{symbol}] attempt {attempt}/{MAX_RETRIES} failed: {e} — waiting {wait}s"
            )
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    return []


def main():
    import yfinance

    print(f"yfinance version: {yfinance.__version__}")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    all_benchmarks: dict[str, dict[str, list]] = {}
    provider_usage: dict[str, dict[str, str]] = {}
    failures: list[dict[str, str]] = []

    for market, benchmark_symbols in BENCHMARK_MAP.items():
        print(f"\n{'=' * 50}")
        print(f" Benchmarks: {market.upper()}")
        print(f"{'=' * 50}")
        all_benchmarks[market] = {}
        provider_usage[market] = {}
        cached_references = _load_bundle_references(market)
        online_provider_available = True

        for bench_sym in sorted(benchmark_symbols):
            print(f"  Fetching benchmark {bench_sym}...")
            rows = (
                fetch_benchmark_rows(bench_sym, market=market)
                if online_provider_available
                else []
            )
            if not rows:
                online_provider_available = False
                cached = cached_references.get(bench_sym, [])
                if cached:
                    all_benchmarks[market][bench_sym] = cached
                    provider_usage[market][bench_sym] = "authoritative_bundle_cache"
                    failures.append(
                        {
                            "market": market,
                            "symbol": bench_sym,
                            "reason": "online fetch failed; used authoritative real bundle cache",
                        }
                    )
                    print(
                        f"    FALLBACK: {len(cached)} bars from authoritative real bundle"
                    )
                    continue
                provider_usage[market][bench_sym] = "unavailable"
                failures.append(
                    {
                        "market": market,
                        "symbol": bench_sym,
                        "reason": "online fetch failed and real bundle cache missing",
                    }
                )
                print(
                    f"    FAIL: no data after {MAX_RETRIES} retries and no real cache"
                )
                continue
            print(f"    OK: {len(rows)} rows")

            is_cn = market == "cn"
            normalizer = normalize_akshare_rows if is_cn else normalize_yfinance_rows
            try:
                bundle = normalizer(symbol=bench_sym, rows=rows)
                all_benchmarks[market][bench_sym] = bundle.price_bars
                provider_usage[market][bench_sym] = "akshare" if is_cn else "yfinance"
                print(f"    Normalized: {len(bundle.price_bars)} CanonicalPriceBars")
            except Exception as e:
                print(f"    Normalize FAIL: {e}")
                all_benchmarks[market][bench_sym] = []
                provider_usage[market][bench_sym] = "normalization_failed"

            time.sleep(TICKER_DELAY)

    # Save
    bench_path = OUTPUT / "benchmarks.pkl"
    with open(bench_path, "wb") as f:
        pickle.dump(all_benchmarks, f)
    print(f"\nBenchmarks saved: {bench_path}")

    # Summary
    total = sum(len(v) for v in all_benchmarks.values())
    print(f"Total benchmark series: {total} across {len(all_benchmarks)} markets.")
    TEMP.mkdir(parents=True, exist_ok=True)
    validation = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "real",
        "provider_by_symbol": provider_usage,
        "failures": failures,
        "market_counts": {
            market: {
                "expected": len(BENCHMARK_MAP[market]),
                "available": sum(bool(rows) for rows in values.values()),
            }
            for market, values in all_benchmarks.items()
        },
    }
    (TEMP / "fetch_benchmarks_validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8"
    )


def _load_bundle_references(market: str) -> dict[str, list]:
    path = OUTPUT / f"bundle_{market}.pkl"
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        bundle = pickle.load(handle)
    by_symbol: dict[str, list] = {}
    for bar in bundle.get("price_bars", []):
        by_symbol.setdefault(bar.symbol, []).append(bar)
    return by_symbol


if __name__ == "__main__":
    main()
