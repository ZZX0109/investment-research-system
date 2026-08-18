#!/usr/bin/env python3
"""Join CNINFO financial-report announcement dates to report-period keys."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

PROJECT = Path(__file__).resolve().parents[1]
ETF = {"159915", "510050", "510300", "510500", "512100"}
YEAR = re.compile(r"(19|20)\d{2}")


def main() -> int:
    target = {
        str(x).zfill(6)
        for x in json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text())["cn"]
        if str(x).zfill(6) not in ETF
    }
    con = sqlite3.connect(PROJECT / "var/cn-research/catalog.db")
    rows = con.execute(
        "SELECT dataset,payload_json FROM raw_data_batches "
        "WHERE dataset IN ('cn_fundamentals_research','cn_financial_ratios_akshare_research','cn_financial_disclosures_cninfo_research')"
    ).fetchall()
    con.close()
    raw_root = PROJECT / "var/cn-research/raw"
    expected: set[tuple[str, str]] = set()
    primary_expected: set[tuple[str, str]] = set()
    candidates: dict[tuple[str, str], list[dict]] = {}
    for dataset, metadata_json in rows:
        metadata = json.loads(metadata_json)
        reference = str(metadata.get("payload_ref") or "")
        payload = json.loads((raw_root / reference.removeprefix("file-object://")).read_text())
        records = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
        if not isinstance(records, list):
            continue
        if dataset in {"cn_fundamentals_research", "cn_financial_ratios_akshare_research"}:
            for record in records:
                symbol = _symbol(record.get("code") or metadata.get("symbol"))
                period = str(record.get("statDate") or "")[:10]
                if symbol in target and period:
                    expected.add((symbol, period))
                    if dataset == "cn_fundamentals_research":
                        primary_expected.add((symbol, period))
        else:
            for record in records:
                symbol = _symbol(record.get("symbol"))
                if symbol not in target:
                    continue
                year_match = YEAR.search(str(record.get("title") or ""))
                if not year_match or not record.get("published_at"):
                    continue
                year = int(year_match.group(0))
                category = str(record.get("category") or "")
                month_day = {"年报": "12-31", "半年报": "06-30", "一季报": "03-31", "三季报": "09-30"}.get(category)
                if month_day:
                    key = (symbol, f"{year:04d}-{month_day}")
                    candidates.setdefault(key, []).append(record)
    matched = {}
    for key, items in candidates.items():
        # Prefer the full report over the abstract, then the earliest timestamp.
        items = sorted(items, key=lambda x: ("摘要" in str(x.get("title") or ""), str(x.get("published_at"))))
        selected = items[0]
        matched[f"{key[0]}::{key[1]}"] = {
            "symbol": key[0],
            "report_period": key[1],
            "published_at": selected["published_at"],
            "title": selected.get("title"),
            "category": selected.get("category"),
            "announcement_id": selected.get("announcement_id"),
            "source_provider": "cninfo",
        }
    matched_keys = {(item["symbol"], item["report_period"]) for item in matched.values()}
    report = {
        "schema_version": "cn-financial-publication-map-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_symbol_count": len(target),
        "expected_symbol_period_count": len(expected),
        "primary_expected_symbol_period_count": len(primary_expected),
        "mapped_symbol_period_count": len(matched_keys),
        "matched_expected_count": len(expected & matched_keys),
        "expected_join_coverage": len(expected & matched_keys) / len(expected) if expected else 0.0,
        "unmatched_expected_count": len(expected - matched_keys),
        "primary_mapped_symbol_period_count": len(primary_expected & matched_keys),
        "primary_expected_join_coverage": len(primary_expected & matched_keys) / len(primary_expected) if primary_expected else 0.0,
        "primary_unmatched_expected_count": len(primary_expected - matched_keys),
        "status": "evidence_only",
        "pit_verified": False,
        "missing_reason": "announcement date is mapped by title/category; statement-level available_at and revision reconciliation remains unverified",
        "rows": sorted(matched.values(), key=lambda x: (x["symbol"], x["report_period"])),
    }
    out = PROJECT / "artifacts/cn_financial_disclosures_cninfo/publication-map.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("expected_symbol_period_count", "mapped_symbol_period_count", "matched_expected_count", "expected_join_coverage", "unmatched_expected_count")}, ensure_ascii=False))
    return 0


def _symbol(value: object) -> str:
    return str(value or "").strip().upper().rsplit(".", 1)[-1].zfill(6)


if __name__ == "__main__":
    raise SystemExit(main())
