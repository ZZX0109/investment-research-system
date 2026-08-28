#!/usr/bin/env python3
"""Build config/cn_industry_map.json from Baostock (CSRC industry).

The training pipeline (rebuild_cn_research_pit._load_industry_mapping) reads this
optional static map to assign an industry to every symbol, eliminating the
missing-industry gap that previously left ~9.26% of the universe unmapped and
caused single-member industries to be skipped by build_industry_reference_bars.

The training universe is taken from the existing full-v4 rebuild index so the
map covers exactly the symbols the demo trains on.
"""
from __future__ import annotations

import json
import argparse
from pathlib import Path

import baostock as bs

PROJECT = Path(__file__).resolve().parent.parent
REBUILD = PROJECT / "artifacts/free_research_rebuild/full-v4/rebuild-2026-08-10-d8aa4828963c.json"
OUT = PROJECT / "config" / "cn_industry_map.json"


def load_universe(rebuild: Path) -> list[str]:
    data = json.loads(Path(rebuild).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return sorted({
            str(item.get("code") if isinstance(item, dict) else item).rsplit(".", 1)[-1].zfill(6)
            for item in data
            if (item.get("code") if isinstance(item, dict) else item)
            and str(item.get("instrument_type", "equity") if isinstance(item, dict) else "equity") != "etf"
        })
    if isinstance(data, dict) and isinstance(data.get("symbols"), list):
        return sorted({str(item).rsplit(".", 1)[-1].zfill(6) for item in data["symbols"]})
    symbols = set()
    for qr in data.get("quality_reports", []):
        sym = qr.get("symbol")
        if sym:
            symbols.add(str(sym))
    return sorted(symbols)


def to_baostock_code(symbol: str, bse_mapping: dict[str, str] | None = None) -> str:
    s = symbol.strip()
    if bse_mapping and s in bse_mapping:
        s = bse_mapping[s]
    if s.startswith(("sh.", "sz.", "bj.")):
        return s
    if s.startswith("6"):
        return "sh." + s
    if s.startswith(("0", "3")):
        return "sz." + s
    if s.startswith(("8", "4")):
        return "bj." + s
    return "sh." + s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=REBUILD, help="JSON rebuild index or current security-master universe")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--resume", action="store_true", help="resume from <output>.progress.json")
    parser.add_argument(
        "--bse-mapping",
        type=Path,
        default=PROJECT / "artifacts/cn_bse_code_mapping/mapping.json",
        help="map current BSE 920 codes to legacy 8/4 codes before querying Baostock",
    )
    parser.add_argument("--request-interval-seconds", type=float, default=0.05)
    args = parser.parse_args()
    if args.request_interval_seconds < 0:
        raise SystemExit("request interval cannot be negative")
    symbols = load_universe(args.universe)
    print(f"universe size: {len(symbols)}")
    login = bs.login()
    print("baostock login:", login.error_code, login.error_msg)

    progress_path = args.output.with_name(args.output.name + ".progress.json")
    progress = {}
    if args.resume and progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            progress = {}
    mapping: dict[str, str] = dict(progress.get("mapping", {}))
    missing: list[str] = list(progress.get("missing", []))
    try:
        bse_rows = json.loads(args.bse_mapping.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        bse_rows = []
    bse_mapping = {
        str(row.get("new_code")).zfill(6): str(row.get("old_code")).zfill(6)
        for row in bse_rows
        if isinstance(row, dict) and row.get("new_code") and row.get("old_code")
    }
    # A failed request remains pending on resume; this makes a later run with
    # a repaired source mapping (for example BSE 920->legacy) effective.
    completed = set(mapping)
    for index, sym in enumerate(symbols, start=1):
        if sym in completed:
            continue
        code = to_baostock_code(sym, bse_mapping)
        try:
            rs = bs.query_stock_industry(code)
            row = None
            while (rs.error_code == "0") & rs.next():
                row = dict(zip(rs.fields, rs.get_row_data()))
            industry = (row or {}).get("industry")
            if industry:
                mapping[sym] = str(industry)
            else:
                missing.append(sym)
        except Exception as exc:  # noqa: BLE001
            missing.append(sym)
            print(f"  ERR {sym}: {type(exc).__name__}: {exc}")
        completed.add(sym)
        progress_path.write_text(json.dumps({"mapping": mapping, "missing": missing}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.request_interval_seconds:
            import time
            time.sleep(args.request_interval_seconds)
        if index % 25 == 0:
            print(f"  {index}/{len(symbols)} mapped={len(mapping)} missing={len(missing)}")

    bs.logout()

    payload = {
        "symbols": mapping,
        "source": "baostock_query_stock_industry",
        "classification": "证监会行业分类",
        "generated_at": "2026-08-13",
        "universe_size": len(symbols),
        "mapped": len(mapping),
        "missing": missing,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output}: mapped={len(mapping)}/{len(symbols)} missing={len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
