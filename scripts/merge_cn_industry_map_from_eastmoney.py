#!/usr/bin/env python3
"""Merge current industry labels from audited Eastmoney performance landing.

Baostock's industry endpoint does not cover every current BSE 920 symbol.  The
Eastmoney quarterly performance landing already contains an industry label for
many of those securities.  This utility merges only the missing symbols and
keeps the resulting map explicitly current/research-only; it does not create
historical effective intervals.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map",
        type=Path,
        default=PROJECT / "config/cn_industry_map_full.json",
        dest="map_path",
    )
    parser.add_argument(
        "--landing-root",
        type=Path,
        default=PROJECT / "artifacts/cn_financial_reports_eastmoney/landing",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--universe",
        type=Path,
        default=PROJECT / "artifacts/cn_security_master_universe/security_master_current.json",
    )
    args = parser.parse_args()
    output = args.output or args.map_path
    payload = _read(args.map_path)
    universe_data = json.loads(args.universe.read_text(encoding="utf-8"))
    universe = {
        str(item.get("code") if isinstance(item, dict) else item).rsplit(".", 1)[-1].zfill(6)
        for item in universe_data
        if (item.get("code") if isinstance(item, dict) else item)
        and str(item.get("instrument_type", "equity") if isinstance(item, dict) else "equity") != "etf"
    }
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else {}
    symbols = {str(key).zfill(6): str(value) for key, value in symbols.items() if value}
    before = len(symbols)
    candidates: dict[str, tuple[str, str]] = {}
    files = sorted(args.landing_root.glob("eastmoney-performance-*/**/page-*.json"))
    for path in files:
        try:
            document = _read(path)
            rows = document.get("payload", {}).get("result", {}).get("data", [])
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("SECURITY_CODE") or "").strip().zfill(6)
            industry = str(row.get("PUBLISHNAME") or row.get("BOARD_NAME") or "").strip()
            if not symbol or symbol not in universe or not industry or symbol in symbols:
                continue
            period = str(row.get("REPORTDATE") or row.get("UPDATE_DATE") or "")
            previous = candidates.get(symbol)
            if previous is None or period > previous[1]:
                candidates[symbol] = (industry, period)

    for symbol, (industry, _) in candidates.items():
        symbols.setdefault(symbol, industry)
    symbols = {symbol: value for symbol, value in symbols.items() if symbol in universe}
    missing = sorted(universe - set(symbols))
    result = {
        **payload,
        "symbols": dict(sorted(symbols.items())),
        "mapped": len(symbols),
        "missing": missing,
        "universe_size": len(universe),
        "source": "baostock_query_stock_industry+eastmoney_performance_landing",
        "current_label_sources": {
            "baostock": before,
            "eastmoney_performance_landing": len(set(symbols) - set(payload.get("symbols", {}))),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "historical_intervals_proven": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"before": before, "eastmoney_candidates": len(candidates), "mapped": len(symbols), "missing": len(missing), "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
