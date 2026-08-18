#!/usr/bin/env python3
"""Convert a verified download manifest into landing metadata.

This command is intentionally fail-closed: a blocked audit cannot be turned
into a landing run by guessing missing PIT or quality fields.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from investment_research.training.snapshot_landing import load_pit_leakage_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--pit-leakage-audit", type=Path, default=None,
        help="optional PIT leakage report; its count and SHA-256 are copied into manifest metadata",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "ready_for_landing"
        or not manifest.get("ready_for_landing")
        or manifest.get("blocked_datasets")
    ):
        print(json.dumps({"status": "blocked", "reason": "download_manifest_not_ready_for_landing"}, ensure_ascii=False))
        return 2
    raw_root = Path(manifest["raw_root"]).resolve()
    files: dict[str, dict] = {}
    symbols: set[str] = set()
    industries: set[str] = set()
    for item in manifest.get("records", []):
        output_path = item.get("output_path")
        if not output_path or not item.get("sha256") or item.get("sha256_verified") is not True:
            print(json.dumps({"status": "blocked", "reason": "manifest_file_reference_unverified", "dataset": item.get("dataset")}, ensure_ascii=False))
            return 2
        path = Path(output_path).resolve()
        if raw_root not in path.parents or not path.is_file():
            print(json.dumps({"status": "blocked", "reason": "manifest_file_missing", "path": output_path}, ensure_ascii=False))
            return 2
        relative = path.relative_to(raw_root).as_posix()
        dataset = str(item.get("dataset") or "unknown")
        complete = (
            item.get("status") in {"complete", "backfilled"}
            and item.get("published_at_coverage") == 1.0
            and item.get("available_at_coverage") == 1.0
            and item.get("collected_at_coverage") == 1.0
            and bool(item.get("revision_id"))
        )
        missing_reason = item.get("missing_reason")
        if not complete and not missing_reason:
            missing_reason = "PIT or revision coverage is incomplete"
        entry = files.setdefault(relative, {
            "dataset": dataset,
            "provider": str(item.get("provider") or "unknown"),
            "layer": "raw",
            "raw_hash": item.get("raw_hash") or item.get("payload_hash"),
            "revision_id": item.get("revision_id"),
            "row_count": item.get("rows"),
            "published_at_coverage": item.get("published_at_coverage"),
            "available_at_coverage": item.get("available_at_coverage"),
            "collected_at_coverage": item.get("collected_at_coverage"),
            "revision_coverage": item.get("revision_coverage") if item.get("revision_coverage") is not None else (1.0 if item.get("revision_id") else 0.0),
            "quality_status": "complete" if complete else "degraded",
            "missing_reason": missing_reason,
            "missing_reason_code": "published_time_unverified" if item.get("published_at_coverage") != 1.0 else "pending_backfill" if not item.get("revision_id") else None,
            "schema_valid": True,
            "duplicate_key_count": int(item.get("duplicate_key_count", 0) or 0),
            "ohlc_error_count": int(item.get("ohlc_error_count", 0) or 0),
            "trading_date_error_count": int(item.get("trading_date_error_count", 0) or 0),
            "trading_status_error_count": int(item.get("trading_status_error_count", 0) or 0),
            "adjustment_error_count": int(item.get("adjustment_error_count", 0) or 0),
            "security_lifecycle_error_count": int(item.get("security_lifecycle_error_count", 0) or 0),
            "reference_error_count": int(item.get("reference_error_count", 0) or 0),
            "pit_time_error_count": int(item.get("pit_time_error_count", 0) or 0),
        })
        if item.get("symbol"):
            symbols.add(str(item["symbol"]))
        if dataset in {"cn_security_master_research", "cn_industry_mapping"} and item.get("symbol"):
            industries.add(str(item["symbol"]))
        # The same payload may be represented by coverage and catalog rows.
        if entry["quality_status"] == "complete" and item.get("status") not in {"complete", "backfilled"}:
            entry["quality_status"] = "degraded"
    manifest_metadata = {
        "target_symbol_count": int(manifest.get("target_symbol_count", 0) or len(symbols)),
        "observed_symbol_count": int(manifest.get("observed_symbol_count", 0) or len(symbols)),
        "industry_target_symbol_count": len(symbols),
        "industry_observed_symbol_count": len(industries),
        "financial_target_field_count": int(manifest.get("financial_target_field_count", 0) or 0),
        "financial_observed_field_count": int(manifest.get("financial_observed_field_count", 0) or 0),
        "financial_low_coverage_fields": [
            str(value) for value in manifest.get("financial_low_coverage_fields", []) if value
        ],
    }
    if args.pit_leakage_audit is not None:
        try:
            count, ref, digest = load_pit_leakage_audit(args.pit_leakage_audit)
        except ValueError as exc:
            print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
            return 2
        manifest_metadata.update({
            "pit_leakage_error_count": count,
            "pit_leakage_audit_ref": ref,
            "pit_leakage_audit_sha256": digest,
        })
    metadata = {
        "manifest": {
            **manifest_metadata,
        },
        "files": files,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, args.output)
    print(json.dumps({"status": "ready", "file_count": len(files), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
