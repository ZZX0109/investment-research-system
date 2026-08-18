#!/usr/bin/env python3
"""Audit CN quarterly fundamentals without modifying the raw object store.

The downloader stores one small JSON object per symbol/family/period.  This
audit turns those objects into an explicit symbol-period-field coverage
report, and separately records whether the source publication date is strong
enough for PIT training.  Collection time is deliberately *not* treated as a
financial publication time.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ETF_SYMBOLS = {"159915", "510050", "510300", "510500", "512100"}

# These are the stable fields consumed by the cn-research-feature-v4 dataset.
# Extra provider fields are still counted and reported, but cannot silently
# become a training requirement.
REQUIRED_FIELDS = {
    "profit": ("roeAvg", "npMargin", "gpMargin", "epsTTM"),
    "growth": ("YOYEquity", "YOYAsset", "YOYNI", "YOYEPSBasic", "YOYPNI"),
    "operation": ("NRTurnRatio", "INVTurnRatio", "AssetTurnRatio"),
    "balance": ("currentRatio", "quickRatio", "cashRatio", "liabilityToAsset"),
    "cash_flow": ("CFOToOR", "CFOToNP", "CFOToGr"),
    "dupont": ("dupontROE", "dupontAssetStoEquity", "dupontAssetTurn"),
}


def _symbol(value: object) -> str:
    text = str(value or "").strip().upper()
    return text.rsplit(".", 1)[-1]


def _present(value: object) -> bool:
    return value not in (None, "", "NA", "N/A", "NULL", "null")


def _target_symbols(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        _symbol(item)
        for item in payload.get("cn", [])
        if _symbol(item) and _symbol(item) not in ETF_SYMBOLS
    }


def audit(database: Path, raw_root: Path, target_path: Path, minimum_coverage: float) -> dict:
    target = _target_symbols(target_path)
    observed_symbols: set[str] = set()
    periods: set[str] = set()
    field_cells: dict[str, set[tuple[str, str]]] = defaultdict(set)
    family_cells: dict[str, set[tuple[str, str]]] = defaultdict(set)
    primary_family_cells: dict[str, set[tuple[str, str]]] = defaultdict(set)
    family_rows: defaultdict[str, int] = defaultdict(int)
    family_publication: defaultdict[str, int] = defaultdict(int)
    family_available: defaultdict[str, int] = defaultdict(int)
    malformed = 0
    payload_count = 0
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT dataset,available_at,payload_json FROM raw_data_batches "
            "WHERE dataset IN ('cn_fundamentals_research','cn_financial_ratios_akshare_research')"
        ).fetchall()
    finally:
        connection.close()

    for dataset_name, catalog_available_at, payload_json in rows:
        try:
            metadata = json.loads(payload_json)
            reference = str(metadata.get("payload_ref") or "")
            path = raw_root / reference.removeprefix("file-object://")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            malformed += 1
            continue
        payload_count += 1
        records = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            malformed += 1
            continue
        for record in records:
            if not isinstance(record, dict):
                malformed += 1
                continue
            symbol = _symbol(record.get("code") or metadata.get("symbol"))
            period = str(record.get("statDate") or "")[:10]
            family = str(record.get("feature_family") or "unknown")
            if not symbol or not period:
                malformed += 1
                continue
            observed_symbols.add(symbol)
            periods.add(period)
            family_rows[family] += 1
            family_cells[family].add((symbol, period))
            if dataset_name == "cn_fundamentals_research":
                primary_family_cells[family].add((symbol, period))
            family_publication[family] += int(_present(record.get("pubDate")))
            # This is the catalog collection timestamp, not an asserted PIT
            # availability time.  It is reported for traceability only.
            family_available[family] += int(_present(catalog_available_at))
            for field in REQUIRED_FIELDS.get(family, ()):
                if _present(record.get(field)):
                    field_cells[f"{family}.{field}"].add((symbol, period))

    # A public fundamentals feed does not publish the same first report date
    # for every company.  Use the union of symbol/report-period keys actually
    # supplied by the six families, rather than pretending every symbol had
    # all global periods.  Missing fields inside that declared universe are
    # still counted; missing historical periods remain an explicit limitation
    # in the report.
    expected_cells_set = set().union(*(cells for family, cells in primary_family_cells.items() if family in REQUIRED_FIELDS))
    if not expected_cells_set:
        expected_cells_set = set().union(*(cells for family, cells in family_cells.items() if family in REQUIRED_FIELDS))
    expected_cells_set = {(symbol, period) for symbol, period in expected_cells_set if symbol in target}
    expected_cells = len(expected_cells_set)
    field_report: dict[str, dict] = {}
    observed_field_count = 0
    target_field_count = expected_cells * sum(len(fields) for fields in REQUIRED_FIELDS.values())
    for family, fields in REQUIRED_FIELDS.items():
        family_expected = expected_cells
        for field in fields:
            key = f"{family}.{field}"
            observed = len(field_cells[key] & expected_cells_set)
            observed_field_count += observed
            field_report[key] = {
                "family": family,
                "field": field,
                "target_cells": family_expected,
                "observed_cells": observed,
                "coverage": observed / family_expected if family_expected else 0.0,
            }

    coverage = observed_field_count / target_field_count if target_field_count else 0.0
    low_coverage_fields = sorted(
        key for key, item in field_report.items() if item["coverage"] < minimum_coverage
    )
    missing_symbols = sorted(target - observed_symbols)
    unexpected_symbols = sorted(observed_symbols - target)
    disclosure_evidence = _audit_disclosure_evidence(connection_path=database, raw_root=raw_root, target=target)
    publication_map = _read_publication_map()
    family_report = {
        family: {
            "rows": family_rows.get(family, 0),
            "symbol_count": len({s for s, _ in family_cells.get(family, set())}),
            "period_count": len({p for _, p in family_cells.get(family, set())}),
            "published_at_coverage": family_publication.get(family, 0) / family_rows[family]
            if family_rows.get(family)
            else 0.0,
            "collection_available_at_coverage": family_available.get(family, 0) / family_rows[family]
            if family_rows.get(family)
            else 0.0,
        }
        for family in REQUIRED_FIELDS
    }
    # pubDate exists in this source, but catalog available_at is collection
    # time.  Until a normalized available_at >= pubDate contract is supplied,
    # this artifact cannot be considered PIT-complete.
    pit_verified = False
    quality_status = "complete" if coverage >= minimum_coverage and pit_verified else "degraded"
    missing_reason = None if quality_status == "complete" else (
        "financial field coverage or PIT publication-to-availability proof is incomplete"
    )
    report = {
        "schema_version": "cn-financial-coverage-v1",
        "dataset": "cn_fundamentals_research",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if quality_status == "complete" else "degraded",
        "quality_status": quality_status,
        "deployment_ready": False,
        "data_tier": "research_pit",
        "provider": "catalog-derived",
        "target_symbol_count": len(target),
        "observed_symbol_count": len(observed_symbols & target),
        "missing_symbols": missing_symbols,
        "unexpected_symbols": unexpected_symbols,
        "period_count": len(periods),
        "period_start": min(periods) if periods else None,
        "period_end": max(periods) if periods else None,
        "period_universe_policy": "union_of_declared_symbol_periods",
        "declared_symbol_period_count": expected_cells,
        "payload_count": payload_count,
        "source_datasets": sorted({str(item[0]) for item in rows}),
        "publication_evidence": disclosure_evidence,
        "publication_period_join": publication_map,
        "malformed_payload_count": malformed,
        "target_field_count": target_field_count,
        "observed_field_count": observed_field_count,
        "coverage": coverage,
        "minimum_coverage": minimum_coverage,
        "low_coverage_fields": low_coverage_fields,
        "published_at_coverage": 1.0 if family_report and all(item["published_at_coverage"] == 1.0 for item in family_report.values()) else 0.0,
        "available_at_coverage": 1.0 if family_report and all(item["collection_available_at_coverage"] == 1.0 for item in family_report.values()) else 0.0,
        "pit_verified": pit_verified,
        "missing_reason": missing_reason,
        "missing_reason_code": "published_time_unverified" if not pit_verified else None,
        "families": family_report,
        "fields": field_report,
    }
    return report


def _audit_disclosure_evidence(connection_path: Path, raw_root: Path, target: set[str]) -> dict:
    """Summarize downloaded CNINFO timestamps without pretending they are joins."""
    connection = sqlite3.connect(connection_path)
    try:
        rows = connection.execute(
            "SELECT payload_json FROM raw_data_batches "
            "WHERE dataset='cn_financial_disclosures_cninfo_research'"
        ).fetchall()
    finally:
        connection.close()
    symbols: set[str] = set()
    unique_rows: dict[str, dict] = {}
    malformed = 0
    for (metadata_json,) in rows:
        try:
            metadata = json.loads(metadata_json)
            reference = str(metadata.get("payload_ref") or "")
            payload = json.loads((raw_root / reference.removeprefix("file-object://")).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            malformed += 1
            continue
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                malformed += 1
                continue
            symbol = _symbol(item.get("symbol"))
            if symbol in target:
                symbols.add(symbol)
                key = str(item.get("announcement_id") or (symbol, item.get("category"), item.get("title"), item.get("published_at")))
                unique_rows[key] = item
    count = len(unique_rows)
    published = sum(int(_present(item.get("published_at"))) for item in unique_rows.values())
    correction_count = sum(str(item.get("category")) == "补充更正" for item in unique_rows.values())
    return {
        "dataset": "cn_financial_disclosures_cninfo_research",
        "symbol_count": len(symbols),
        "target_symbol_count": len(target),
        "row_count": count,
        "published_at_count": published,
        "published_at_coverage": published / count if count else 0.0,
        "correction_announcement_count": correction_count,
        "malformed_payload_count": malformed,
        "join_to_statement_period_verified": False,
        "status": "evidence_downloaded" if symbols else "missing",
    }


def _read_publication_map() -> dict:
    path = PROJECT / "artifacts/cn_financial_disclosures_cninfo/publication-map.json"
    if not path.is_file():
        return {"status": "not_built"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "unreadable"}
    return {
        "status": payload.get("status"),
        "expected_symbol_period_count": payload.get("expected_symbol_period_count"),
        "mapped_symbol_period_count": payload.get("mapped_symbol_period_count"),
        "matched_expected_count": payload.get("matched_expected_count"),
        "expected_join_coverage": payload.get("expected_join_coverage"),
        "unmatched_expected_count": payload.get("unmatched_expected_count"),
        "primary_expected_symbol_period_count": payload.get("primary_expected_symbol_period_count"),
        "primary_mapped_symbol_period_count": payload.get("primary_mapped_symbol_period_count"),
        "primary_expected_join_coverage": payload.get("primary_expected_join_coverage"),
        "primary_unmatched_expected_count": payload.get("primary_unmatched_expected_count"),
        "pit_verified": payload.get("pit_verified", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_financial_coverage/latest.json")
    args = parser.parse_args()
    report = audit(args.database, args.raw_root, args.target_symbols, args.minimum_coverage)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "coverage": report["coverage"], "observed_field_count": report["observed_field_count"], "target_field_count": report["target_field_count"]}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
