#!/usr/bin/env python3
"""Backfill CN financial ratios from Eastmoney's public indicator endpoint.

The endpoint returns one compact, paged-by-symbol table and exposes current,
quick and cash ratios for many more historical quarters than the older Sina
HTML collector.  Records are appended to the existing research indicator
dataset; provider values already present are never overwritten.  This source
does not prove first-publication or revision availability, so every record
remains ``research_pit`` and cannot activate a formal snapshot.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

import akshare as ak

from fetch_financial_analysis_indicator import _find_missing_symbols, _persist


INDUSTRY_MAP = PROJECT / "config/cn_industry_map_full.json"


def _financial_symbols() -> set[str]:
    """Return CSRC financial-sector symbols for candidate prioritisation.

    This is only a scheduling hint.  It never changes the coverage
    denominator and never marks a missing ratio as not-applicable.
    """
    try:
        payload = json.loads(INDUSTRY_MAP.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    symbols = payload.get("symbols", {}) if isinstance(payload, dict) else {}
    if not isinstance(symbols, dict):
        return set()
    return {
        str(symbol).zfill(6)
        for symbol, industry in symbols.items()
        if str(industry).startswith(("J66", "J67", "J68", "J69"))
    }


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _exchange(symbol: str) -> str:
    return "SH" if str(symbol).startswith(("5", "6", "688", "689")) else "SZ"


def fetch_symbol(symbol: str, start_year: int = 2010) -> list[dict]:
    """Return normalized balance-ratio rows from the EM endpoint."""
    try:
        frame = ak.stock_financial_analysis_indicator_em(
            symbol=f"{symbol}.{_exchange(symbol)}", indicator="按报告期"
        )
    except Exception as exc:
        print(f"  {symbol} FAIL: {str(exc)[:100]}", file=sys.stderr)
        return []
    records: list[dict] = []
    for _, row in frame.iterrows():
        raw_date = row.get("REPORT_DATE")
        period = str(raw_date)[:10]
        if not period or period[:4].isdigit() is False or int(period[:4]) < start_year:
            continue
        values = {
            "currentRatio": _number(row.get("LD")),
            "quickRatio": _number(row.get("SD")),
            # EM already expresses CASH_RATIO as a decimal ratio (for
            # example 0.1087 = 10.87%).  Keep that unit consistent with the
            # canonical feature contract; do not multiply by 100.
            "cashRatio": _number(row.get("CASH_RATIO")),
        }
        if not any(value is not None for value in values.values()):
            continue
        records.append({
            "code": f"{_exchange(symbol).lower()}.{symbol}",
            "symbol": symbol,
            "statDate": period,
            "feature_family": "balance",
            "source_provider": "akshare_fai_em",
            "source_metric_label": "eastmoney_main_financial_data",
            **values,
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument(
        "--skip-financial",
        action="store_true",
        help="Prioritise non-financial symbols; financial symbols remain missing and are not reclassified.",
    )
    args = parser.parse_args()
    if args.limit <= 0 or args.start_year < 1990 or args.sleep_seconds < 0:
        raise SystemExit("invalid arguments")
    candidates = _find_missing_symbols(args.limit * 2 if args.skip_financial else args.limit)
    if args.skip_financial:
        financial = _financial_symbols()
        symbols = [symbol for symbol, _ in candidates if symbol not in financial][: args.limit]
    else:
        symbols = [symbol for symbol, _ in candidates]
    print(f"[fai-em] fetching {len(symbols)} symbols")
    total = 0
    for index, symbol in enumerate(symbols, start=1):
        records = fetch_symbol(symbol, args.start_year)
        if records:
            total += _persist(
                symbol,
                records,
                provider="akshare_fai_em",
                request_prefix="fai-em",
            )
        print(f"[fai-em] {index}/{len(symbols)} {symbol} rows={len(records)} persisted_total={total}", flush=True)
        if index < len(symbols):
            time.sleep(args.sleep_seconds)
    print(f"[fai-em] done: {total} new records from {len(symbols)} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
