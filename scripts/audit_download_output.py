#!/usr/bin/env python3
"""Audit a completed downloader output without promoting it to a snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from investment_research.training.snapshot_landing import audit_file_contents

PROJECT = Path(__file__).resolve().parents[1]
REQUIRED_CATEGORIES = {
    "prices",
    "adjustment_factors",
    "trading_status",
    "market_breadth",
    "industry",
    "financials",
    "corporate_actions",
    "events",
    "financing",
    "macro",
    "pit_time",
}

DATASET_CATEGORY = {
    "daily_bars_raw": "prices",
    "daily_bars_qfq": "prices",
    "cn_adjustment_factors": "adjustment_factors",
    "cn_adjustment_factors_research": "adjustment_factors",
    "cn_trading_status": "trading_status",
    "cn_market_breadth_derived": "market_breadth",
    "cn_industry_mapping": "industry",
    "cn_security_master_research": "industry",
    "cn_security_industry_history_akshare": "industry",
    "cn_fundamentals_research": "financials",
    "cn_financial_ratios_akshare_research": "financials",
    "cn_financial_disclosures_cninfo_research": "pit_time",
    "cn_financials": "financials",
    "cn_corporate_actions_detailed": "corporate_actions",
    "cn_corporate_actions_research": "corporate_actions",
    "events": "events",
    "cn_margin_financing": "financing",
    "cn_margin_financing_sh": "financing",
    "cn_margin_financing_sz": "financing",
    "macro_series_bundle": "macro",
    "cn_macro_cpi_monthly": "macro",
    "cn_macro_ppi_monthly": "macro",
    "cn_macro_pmi_monthly": "macro",
    "cn_macro_lpr": "macro",
    "cn_macro_shibor": "macro",
    "cn_macro_m2": "macro",
    "cn_macro_social_financing": "macro",
    "cn_macro_fx_rmb": "macro",
    "cn_macro_pit": "macro",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--auxiliary-report", type=Path, default=PROJECT / "artifacts/cn_research_auxiliary/latest.json")
    parser.add_argument("--derived-trading-status", type=Path, default=PROJECT / "artifacts/cn_trading_status/latest.json")
    parser.add_argument("--derived-security-master", type=Path, default=PROJECT / "artifacts/cn_security_master/latest.json")
    parser.add_argument("--financial-report", type=Path, default=PROJECT / "artifacts/cn_financial_coverage/latest.json")
    parser.add_argument("--macro-report", type=Path, default=PROJECT / "artifacts/cn_research_auxiliary/macro_pit_latest.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/download_manifests/latest.json")
    args = parser.parse_args()
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    records = [_coverage_record(item, args.raw_root) for item in coverage.get("records", [])]
    cn_coverage = next(
        (
            item for item in coverage.get("market_coverage", [])
            if isinstance(item, dict) and item.get("market") == "cn"
        ),
        {},
    )
    target_symbol_count = int(cn_coverage.get("target_count", 0) or 0)
    successful_target_symbol_count = int(cn_coverage.get("successful_target_count", 0) or 0)
    failed_target_symbol_count = len(cn_coverage.get("unavailable_symbols", []) or [])
    database_records = _database_records(args.database, args.raw_root)
    blocked_datasets: list[str] = []
    database_by_key = {
        (item.get("dataset"), item.get("provider"), item.get("symbol")): item
        for item in database_records
    }
    for item in records:
        reference = database_by_key.get((item.get("dataset"), item.get("provider"), item.get("symbol")))
        if reference:
            for key in ("output_path", "sha256_verified", "sha256", "revision_id", "available_at_coverage", "collected_at_coverage"):
                if item.get(key) in (None, "") and reference.get(key) not in (None, ""):
                    item[key] = reference[key]
    records.extend(database_records)
    if database_records:
        records.append({
            "category": "pit_time",
            "dataset": "canonical_time_contract",
            "provider": "catalog-derived",
            "symbol": None,
            "status": "degraded",
            "quality_status": "degraded",
            "rows": len(database_records),
            "date_start": None,
            "date_end": None,
            "published_at_coverage": None,
            "available_at_coverage": sum(bool(item.get("available_at_coverage")) for item in database_records) / len(database_records),
            "collected_at_coverage": _coverage_ratio(database_records, "collected_at_coverage"),
            "revision_coverage": 1.0,
            "revision_id": None,
            "missing_reason": "published_time_unverified",
            "missing_reason_code": "published_time_unverified",
            "payload_hash": None,
            "sha256": None,
            "output_path": None,
            "sha256_verified": None,
            "audit_status": "download_output_only",
            "schema_valid": None,
            "duplicate_key_count": None,
            "ohlc_error_count": None,
            "trading_date_error_count": None,
            "trading_status_error_count": None,
            "adjustment_error_count": None,
            "security_lifecycle_error_count": None,
            "reference_error_count": None,
            "pit_time_error_count": None,
        })
    if args.derived_trading_status.is_file():
        try:
            status_record = json.loads(args.derived_trading_status.read_text(encoding="utf-8"))
            if status_record.get("dataset") == "cn_trading_status":
                if status_record.get("quality_status") != "complete":
                    blocked_datasets.append(f"cn_trading_status:{status_record.get('quality_status', 'unknown')}")
                records.append({
                    "category": "trading_status",
                    "dataset": "cn_trading_status",
                    "provider": status_record.get("provider"),
                    "symbol": None,
                    "status": status_record.get("status", "unknown"),
                    "quality_status": status_record.get("quality_status", "degraded"),
                    "rows": status_record.get("row_count"),
                    "date_start": status_record.get("date_start"),
                    "date_end": status_record.get("date_end"),
                    "published_at_coverage": status_record.get("published_at_coverage"),
                    "available_at_coverage": status_record.get("available_at_coverage"),
                    "collected_at_coverage": status_record.get("collected_at_coverage"),
                    "revision_coverage": status_record.get("revision_coverage"),
                    "revision_id": "derived-standard-v1",
                    "missing_reason": status_record.get("missing_reason"),
                    "missing_reason_code": status_record.get("missing_reason_code"),
                    "payload_hash": status_record.get("sha256"),
                    "sha256": status_record.get("sha256"),
                    "output_path": status_record.get("output_path"),
                    "sha256_verified": status_record.get("sha256_verified"),
                    "audit_status": "download_output_only",
                    "schema_valid": None,
                    "duplicate_key_count": None,
                    "ohlc_error_count": None,
                    "trading_date_error_count": None,
                    "pit_time_error_count": None,
                })
        except (OSError, json.JSONDecodeError):
            blocked_datasets.append("cn_trading_status:report_unreadable")
    if args.derived_security_master.is_file():
        try:
            master_record = json.loads(args.derived_security_master.read_text(encoding="utf-8"))
            if master_record.get("dataset") == "cn_historical_universe_memberships":
                if master_record.get("quality_status") != "complete":
                    blocked_datasets.append(f"cn_historical_universe_memberships:{master_record.get('quality_status', 'unknown')}")
                records.append({
                    "category": "industry",
                    "dataset": "cn_historical_universe_memberships",
                    "provider": master_record.get("provider"),
                    "symbol": None,
                    "status": master_record.get("status", "unknown"),
                    "quality_status": master_record.get("quality_status", "degraded"),
                    "rows": master_record.get("row_count"),
                    "date_start": None,
                    "date_end": None,
                    "published_at_coverage": master_record.get("published_at_coverage"),
                    "available_at_coverage": master_record.get("available_at_coverage"),
                    "collected_at_coverage": master_record.get("collected_at_coverage"),
                    "revision_coverage": 1.0,
                    "revision_id": "derived-security-master-v1",
                    "missing_reason": master_record.get("missing_reason"),
                    "missing_reason_code": master_record.get("missing_reason_code"),
                    "payload_hash": master_record.get("sha256"),
                    "sha256": master_record.get("sha256"),
                    "output_path": master_record.get("output_path"),
                    "sha256_verified": master_record.get("sha256_verified"),
                    "audit_status": "download_output_only",
                    "schema_valid": None,
                    "duplicate_key_count": None,
                    "ohlc_error_count": None,
                    "trading_date_error_count": None,
                    "pit_time_error_count": None,
                })
        except (OSError, json.JSONDecodeError):
            blocked_datasets.append("cn_historical_universe_memberships:report_unreadable")
    financial_target_field_count = 0
    financial_observed_field_count = 0
    financial_low_coverage_fields: list[str] = []
    if args.financial_report.is_file():
        try:
            financial = json.loads(args.financial_report.read_text(encoding="utf-8"))
            financial_target_field_count = int(financial.get("target_field_count", 0) or 0)
            financial_observed_field_count = int(financial.get("observed_field_count", 0) or 0)
            financial_low_coverage_fields = [
                str(value) for value in financial.get("low_coverage_fields", []) if value
            ]
            if financial.get("quality_status") != "complete":
                blocked_datasets.append(
                    f"cn_fundamentals_research:{financial.get('quality_status', 'unknown')}"
                )
            records.append({
                "category": "financials",
                "dataset": "cn_fundamentals_research_coverage",
                "provider": financial.get("provider", "catalog-derived"),
                "symbol": None,
                "status": financial.get("status", "unknown"),
                "quality_status": financial.get("quality_status", "degraded"),
                "rows": financial.get("observed_field_count"),
                "date_start": financial.get("period_start"),
                "date_end": financial.get("period_end"),
                "published_at_coverage": financial.get("published_at_coverage"),
                "available_at_coverage": financial.get("available_at_coverage"),
                "collected_at_coverage": financial.get("collected_at_coverage"),
                "revision_coverage": financial.get("revision_coverage"),
                "revision_id": "financial-coverage-audit-v1",
                "missing_reason": financial.get("missing_reason"),
                "missing_reason_code": financial.get("missing_reason_code"),
                "payload_hash": financial.get("sha256"),
                "sha256": financial.get("sha256"),
                "output_path": str(args.financial_report),
                "sha256_verified": None,
                "audit_status": "download_output_only",
                "schema_valid": True,
                "duplicate_key_count": None,
                "ohlc_error_count": None,
                "trading_date_error_count": None,
                "pit_time_error_count": None,
            })
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            blocked_datasets.append("cn_fundamentals_research:report_unreadable")
    if args.macro_report.is_file():
        try:
            macro = json.loads(args.macro_report.read_text(encoding="utf-8"))
            if macro.get("quality_status") != "complete":
                blocked_datasets.append(f"cn_macro_pit:{macro.get('quality_status', 'unknown')}")
            records.append({
                "category": "macro",
                "dataset": "cn_macro_pit",
                "provider": "catalog-derived",
                "symbol": None,
                "status": macro.get("status", "unknown"),
                "quality_status": macro.get("quality_status", "degraded"),
                "rows": macro.get("record_count"),
                "date_start": None,
                "date_end": None,
                "published_at_coverage": macro.get("published_at_coverage"),
                "available_at_coverage": macro.get("available_at_coverage"),
                "collected_at_coverage": macro.get("collected_at_coverage"),
                "revision_coverage": macro.get("revision_coverage"),
                "revision_id": "macro-pit-audit-v1",
                "missing_reason": macro.get("missing_reason"),
                "missing_reason_code": macro.get("missing_reason_code"),
                "payload_hash": None,
                "sha256": None,
                "output_path": macro.get("output_path"),
                "sha256_verified": None,
                "audit_status": "download_output_only",
                "schema_valid": True,
                "duplicate_key_count": None,
                "ohlc_error_count": None,
                "trading_date_error_count": None,
                "pit_time_error_count": None,
            })
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            blocked_datasets.append("cn_macro_pit:report_unreadable")
    _audit_manifest_references(records, args.raw_root)
    _audit_manifest_files(records, args.raw_root)
    categories = {item["category"] for item in records if item["category"]}
    missing = sorted(REQUIRED_CATEGORIES - categories)
    failures = [item for item in records if item["status"] in {"fetch_failed", "unsupported", "unavailable"}]
    audit_failures = [
        item for item in records
        if item.get("reference_error_count")
        or item.get("schema_valid") is not True
        or any(item.get(key) not in (None, 0) for key in (
            "duplicate_key_count", "security_code_error_count", "ohlc_error_count", "trading_date_error_count",
            "trading_status_error_count", "adjustment_error_count",
            "security_lifecycle_error_count", "pit_time_error_count",
        ))
    ]
    if audit_failures:
        blocked_datasets.append(f"content_audit_failed:{len(audit_failures)}")
    event_semantics_errors = _event_semantics_errors(records)
    if event_semantics_errors:
        blocked_datasets.extend(
            f"event_missing_semantics_invalid:{reason}"
            for reason in event_semantics_errors
        )
    degraded_records = [
        item for item in records
        if _quality_status(str(item.get("status", "unknown"))) != "complete"
    ]
    if degraded_records:
        blocked_datasets.append(f"quality_incomplete:{len(degraded_records)}")
    if args.auxiliary_report.is_file():
        try:
            auxiliary = json.loads(args.auxiliary_report.read_text(encoding="utf-8"))
            datasets = auxiliary.get("datasets", {})
            for name, item in datasets.items():
                if isinstance(item, dict) and item.get("status") not in {None, "complete"}:
                    blocked_datasets.append(f"{name}:{item.get('status')}")
        except (OSError, json.JSONDecodeError):
            blocked_datasets.append("auxiliary_report_unreadable")
    quality_summary: dict[str, int] = {}
    for item in records:
        quality_summary[item["status"]] = quality_summary.get(item["status"], 0) + 1
    audit_counters = {
        "records_with_output_path": sum(bool(item.get("output_path")) for item in records),
        "sha256_verified": sum(item.get("sha256_verified") is True for item in records),
        "sha256_unverified": sum(item.get("sha256_verified") is not True for item in records),
        "published_at_unverified": sum(item.get("published_at_coverage") not in (1.0,) for item in records),
        "available_at_unverified": sum(item.get("available_at_coverage") not in (1.0,) for item in records),
        "adjustment_errors": sum(int(item.get("adjustment_error_count") or 0) for item in records),
        "trading_status_errors": sum(int(item.get("trading_status_error_count") or 0) for item in records),
        "security_lifecycle_errors": sum(int(item.get("security_lifecycle_error_count") or 0) for item in records),
        "reference_errors": sum(int(item.get("reference_error_count") or 0) for item in records),
        "security_code_errors": sum(int(item.get("security_code_error_count") or 0) for item in records),
    }
    success_count = sum(_quality_status(str(item.get("status", "unknown"))) == "complete" for item in records)
    unavailable_count = sum(_quality_status(str(item.get("status", "unknown"))) == "unavailable" for item in records)
    degraded_count = len(records) - success_count - unavailable_count
    payload = {
        "schema_version": "download-output-manifest-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_coverage_ledger": str(args.coverage),
        "source_database": str(args.database),
        "raw_root": str(args.raw_root),
        "data_tier": coverage.get("data_tier", "research_pit"),
        "status": "blocked" if missing or failures or blocked_datasets else "ready_for_landing",
        "ready_for_landing": not missing and not failures and not blocked_datasets,
        "missing_categories": missing,
        "success_count": success_count,
        "failure_count": len(failures),
        "unavailable_count": unavailable_count,
        "degraded_count": degraded_count,
        "quality_failure_count": len(records) - success_count,
        "target_symbol_count": target_symbol_count,
        "successful_target_symbol_count": successful_target_symbol_count,
        "failed_target_symbol_count": failed_target_symbol_count,
        "observed_symbol_count": len({str(item.get("symbol")) for item in records if item.get("symbol")}),
        "blocked_datasets": sorted(blocked_datasets),
        "event_semantics_errors": event_semantics_errors,
        "financial_target_field_count": financial_target_field_count,
        "financial_observed_field_count": financial_observed_field_count,
        "financial_low_coverage_fields": financial_low_coverage_fields,
        "record_count": len(records),
        "quality_summary": quality_summary,
        "audit_counters": audit_counters,
        "records": records,
        "notes": [
            "This audit does not mutate or activate any snapshot.",
            "Public historical backfill remains research-only until historical available_at is proven.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "records": len(records), "missing_categories": missing}, ensure_ascii=False))
    return 0 if payload["ready_for_landing"] else 2


def _coverage_record(item: dict, raw_root: Path) -> dict:
    dataset = str(item.get("dataset", "unknown"))
    status = item.get("status", "unknown")
    reason = item.get("reason") or item.get("degraded_reason")
    return {
        "category": DATASET_CATEGORY.get(dataset),
        "dataset": dataset,
        "provider": item.get("provider"),
        "symbol": item.get("symbol"),
        "status": status,
        "quality_status": _quality_status(status),
        "rows": item.get("rows_or_bytes"),
        "date_start": item.get("coverage_start"),
        "date_end": item.get("coverage_end"),
        "published_at_coverage": item.get("published_at_coverage"),
        "available_at_coverage": item.get("available_at_coverage"),
        "collected_at_coverage": item.get("collected_at_coverage"),
        "revision_coverage": item.get("revision_coverage") if item.get("revision_coverage") is not None else (1.0 if item.get("revision_id") else 0.0),
        "revision_id": item.get("revision_id"),
        "missing_reason": reason,
        "missing_reason_code": _missing_reason_code(reason, status),
        "payload_hash": item.get("payload_hash"),
        "sha256": item.get("payload_hash"),
        "output_path": None,
        "sha256_verified": None,
        "audit_status": "download_output_only",
        "schema_valid": None,
        "duplicate_key_count": None,
        "ohlc_error_count": None,
        "trading_date_error_count": None,
        "trading_status_error_count": None,
        "adjustment_error_count": None,
        "security_lifecycle_error_count": None,
        "reference_error_count": None,
        "pit_time_error_count": None,
    }


_EVENT_MISSING_REASON_CODES = {
    "no_events_confirmed",
    "provider_not_covered",
    "published_time_unverified",
    "field_missing_in_source",
    "fetch_failed",
    "pending_backfill",
}


def _event_semantics_errors(records: list[dict]) -> list[str]:
    """Return explicit event-absence contract violations.

    A completed event record may carry only the explicit
    ``no_events_confirmed`` reason/code pair.  Conversely, any non-complete
    event record must explain why the observation is absent; an unqualified
    ``no events`` value is not evidence that no event existed.
    This check runs before landing promotion so readiness cannot be repaired
    later by interpreting an already-invalid manifest.
    """
    errors: set[str] = set()
    for item in records:
        if not isinstance(item, dict):
            continue
        if item.get("dataset") != "events" and item.get("category") != "events":
            continue
        quality = str(item.get("quality_status") or item.get("status") or "unavailable")
        reason = item.get("missing_reason")
        code = item.get("missing_reason_code")
        if quality != "complete" and not reason:
            errors.add("missing_reason")
        if code is not None and code not in _EVENT_MISSING_REASON_CODES:
            errors.add(f"unknown_missing_reason_code:{code}")
        explicit_none = (
            code == "no_events_confirmed"
            and str(reason or "").strip().lower() in {"no_events_confirmed", "no events confirmed"}
        )
        if quality == "complete" and (reason or code) and not explicit_none:
            errors.add("complete_event_record_has_missing_reason")
        if str(reason or "").strip().lower() in {"no events", "no_event", "none", "0"} and code != "no_events_confirmed":
            errors.add("unqualified_no_event_statement")
    return sorted(errors)


def _database_records(database: Path, raw_root: Path) -> list[dict]:
    if not database.is_file():
        return []
    result: list[dict] = []
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute("SELECT provider,dataset,available_at,quality_status,payload_json FROM raw_data_batches").fetchall()
    finally:
        connection.close()
    for provider, dataset, available_at, quality_status, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        reference = str(payload.get("payload_ref", ""))
        relative = reference.removeprefix("file-object://")
        path = (raw_root / relative).resolve() if relative else None
        within_root = path is not None and raw_root.resolve() in path.parents
        digest = _sha256(path) if within_root and path.is_file() else None
        result.append({
            "category": DATASET_CATEGORY.get(dataset),
            "dataset": dataset,
            "provider": provider,
            "symbol": payload.get("symbol"),
            "status": "complete" if quality_status == "passed" else quality_status,
            "quality_status": "complete" if quality_status == "passed" else "degraded",
            "rows": payload.get("row_count"),
            "date_start": payload.get("coverage_start"),
            "date_end": payload.get("coverage_end"),
            "published_at_coverage": None,
            "available_at_coverage": 1.0 if payload.get("available_at") or available_at else 0.0,
            "collected_at_coverage": 1.0 if payload.get("fetched_at") or payload.get("received_at") else 0.0,
            "revision_coverage": 1.0 if payload.get("revision_id") or payload.get("revision") or payload.get("payload_hash") else 0.0,
            "revision_id": payload.get("revision_id") or payload.get("revision") or payload.get("payload_hash"),
            "missing_reason": None if quality_status == "passed" else ";".join(payload.get("quality_issues", [])),
            "missing_reason_code": _missing_reason_code(
                None if quality_status == "passed" else ";".join(payload.get("quality_issues", [])),
                quality_status,
            ),
            "payload_hash": payload.get("payload_hash"),
            "sha256": digest or payload.get("payload_hash"),
            "output_path": str(path) if within_root and path.is_file() else None,
            "sha256_verified": bool(digest and digest == payload.get("payload_hash")),
            "audit_status": "download_output_only",
            "schema_valid": None,
            "duplicate_key_count": None,
            "ohlc_error_count": None,
            "trading_date_error_count": None,
            "trading_status_error_count": None,
            "adjustment_error_count": None,
            "security_lifecycle_error_count": None,
            "reference_error_count": None,
            "pit_time_error_count": None,
        })
    return result


def _audit_manifest_references(records: list[dict], raw_root: Path) -> None:
    """Annotate every record with a local path/hash reference check.

    A coverage row without a landed file is deliberately an error here.  The
    downloader audit is not allowed to treat a catalog claim as a file that a
    later snapshot can safely consume.
    """
    root = raw_root.resolve()
    for item in records:
        output = item.get("output_path")
        digest = item.get("sha256")
        if item.get("dataset") == "canonical_time_contract":
            item["reference_error_count"] = 0
            continue
        if not output or not digest:
            item["reference_error_count"] = 1
            item["sha256_verified"] = False if item.get("sha256_verified") is not True else item["sha256_verified"]
            continue
        path = Path(str(output)).resolve()
        valid = root in path.parents and path.is_file()
        if valid:
            try:
                valid = _sha256(path) == str(digest)
            except OSError:
                valid = False
        item["reference_error_count"] = 0 if valid else 1
        item["sha256_verified"] = bool(valid)


def _audit_manifest_files(records: list[dict], raw_root: Path) -> None:
    """Run format-aware checks once per referenced file and copy the results."""
    root = raw_root.resolve()
    cache: dict[Path, dict] = {}
    for item in records:
        output = item.get("output_path")
        if item.get("dataset") == "canonical_time_contract":
            item["schema_valid"] = True
            continue
        if not output:
            item["schema_valid"] = False
            continue
        path = Path(str(output)).resolve()
        if root not in path.parents or not path.is_file():
            item["schema_valid"] = False
            continue
        if path not in cache:
            cache[path] = audit_file_contents(path, dataset=str(item.get("dataset") or "unknown"))
        for key, value in cache[path].items():
            if key == "reference_error_count":
                continue
            if key == "row_count" and item.get("rows") in (None, ""):
                item["rows"] = value
            elif key != "row_count":
                item[key] = value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage_ratio(records: list[dict], field: str) -> float | None:
    """Return an observed coverage ratio without turning unknown into 100%."""
    values = [item.get(field) for item in records if item.get(field) is not None]
    if not values:
        return None
    try:
        return sum(float(value) >= 1.0 for value in values) / len(values)
    except (TypeError, ValueError):
        return None


def _quality_status(status: str) -> str:
    if status in {"complete", "backfilled"}:
        return "complete"
    if status in {"fetch_failed", "unsupported", "unavailable"}:
        return "unavailable"
    return "degraded"


def _missing_reason_code(reason: str | None, status: str) -> str | None:
    if _quality_status(status) == "complete":
        return None
    text = (reason or "").lower()
    if "provider" in text or status == "unsupported":
        return "provider_not_covered"
    if "publish" in text or "available" in text or "rolling" in text:
        return "published_time_unverified"
    if "field" in text or "column" in text:
        return "field_missing_in_source"
    if "fetch" in text or status == "fetch_failed":
        return "fetch_failed"
    return "pending_backfill"


if __name__ == "__main__":
    raise SystemExit(main())
