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
from pathlib import Path

import baostock as bs

PROJECT = Path(__file__).resolve().parent.parent
REBUILD = PROJECT / "artifacts/free_research_rebuild/full-v4/rebuild-2026-08-10-d8aa4828963c.json"
OUT = PROJECT / "config" / "cn_industry_map.json"


def load_universe(rebuild: Path) -> list[str]:
    data = json.loads(Path(rebuild).read_text(encoding="utf-8"))
    symbols = set()
    for qr in data.get("quality_reports", []):
        sym = qr.get("symbol")
        if sym:
            symbols.add(str(sym))
    return sorted(symbols)


def to_baostock_code(symbol: str) -> str:
    s = symbol.strip()
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
    symbols = load_universe(REBUILD)
    print(f"universe size: {len(symbols)}")
    login = bs.login()
    print("baostock login:", login.error_code, login.error_msg)

    mapping: dict[str, str] = {}
    missing: list[str] = []
    for index, sym in enumerate(symbols, start=1):
        code = to_baostock_code(sym)
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
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}: mapped={len(mapping)}/{len(symbols)} missing={len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
