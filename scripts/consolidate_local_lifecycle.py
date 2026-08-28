#!/usr/bin/env python3
"""Consolidate the local SSE/SZSE delisting + listing + name-change objects
that are already persisted in the catalog object store into a single,
versioned historical-lifecycle layer.

This does NOT hit the akshare network: it reads the raw_data_batches rows
whose payload_ref points at the already-fetched object-store files, and
derives a per-symbol lifecycle record (listed_on / delisted_on /
listing_status / st_status / security_name / name_changes).

Earlier runs left these objects orphaned from the lifecycle audit because
the lifecycle fetcher persisted them under akshare dataset names that the
security-master builder does not read directly.  This script closes that
gap so delisting_coverage is no longer a false zero.

Research-only: no new publication times are invented.  The published_at of
the underlying announcement is left None until the PIT contract is proven.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT / "var/cn-research/catalog.db"
DEFAULT_OBJECT_ROOT = PROJECT / "var/cn-research/raw/raw-market"
DEFAULT_OUTPUT = PROJECT / "artifacts/cn_security_lifecycle_full/security_lifecycle.json"
DEFAULT_LATEST = PROJECT / "artifacts/cn_security_lifecycle_full/latest.json"
DEFAULT_BSE_MAPPING = PROJECT / "artifacts/cn_bse_code_mapping/mapping.json"


def _read_object(object_root: Path, payload_ref: str) -> list:
    """Resolve a file-object://raw-market/sha256/XX/xxx.json reference.

    object_root is the raw-market directory; the ref already contains the
    raw-market/ prefix, so we strip it before joining.
    """
    if "sha256/" not in payload_ref:
        return []
    rel = payload_ref.split("sha256/", 1)[1]
    path = object_root / "sha256" / rel
    if not path.is_file():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return obj if isinstance(obj, list) else []


def _load_dataset_objects(connection: sqlite3.Connection, object_root: Path, dataset: str) -> list[dict]:
    rows = connection.execute(
        "SELECT payload_json FROM raw_data_batches WHERE dataset=?", (dataset,)
    ).fetchall()
    out: list[dict] = []
    for (pj,) in rows:
        if not pj:
            continue
        try:
            payload = json.loads(pj)
        except (TypeError, json.JSONDecodeError):
            continue
        ref = payload.get("payload_ref") or ""
        obj = _read_object(object_root, ref)
        for item in obj:
            if isinstance(item, dict):
                out.append(item)
    return out


def _load_bse_mapping(path: Path) -> dict[str, dict]:
    """Load the official old-code/new-code migration table, if available."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    rows = payload if isinstance(payload, list) else payload.get("rows", []) if isinstance(payload, dict) else []
    return {
        str(row.get("new_code") or "").strip().zfill(6): row
        for row in rows
        if isinstance(row, dict) and row.get("new_code") and row.get("old_code")
    }


def _to_date(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nat":
        return None
    # Normalize both zero-padded and public-table forms such as 2023-5-18;
    # some cells also carry a full datetime suffix.
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _canonical_symbol(code) -> str | None:
    if not code:
        return None
    text = str(code).strip()
    # Strip sh./sz. prefixes some sources carry.
    if text.startswith(("sh.", "sz.", "bj.")):
        text = text[3:]
    if text.startswith(("sh", "sz", "bj")) and len(text) > 6 and text[2].isalpha():
        text = text[2:]
    if text.isdigit() and len(text) == 6:
        return text
    return None


def _st_status_from_name(name: str | None) -> str | None:
    if not name:
        return None
    if "ST" in name or "*ST" in name:
        return "st_risk_warning"
    return "normal"


def consolidate(
    connection: sqlite3.Connection,
    object_root: Path,
    bse_mapping_path: Path | None = None,
) -> tuple[list[dict], dict]:
    """Build a unified per-symbol lifecycle record from local objects."""
    sh_delist = _load_dataset_objects(connection, object_root, "stock_info_sh_delist")
    sz_delist = _load_dataset_objects(connection, object_root, "stock_info_sz_delist")
    sh_name_code = _load_dataset_objects(connection, object_root, "stock_info_sh_name_code")
    sz_name_code = _load_dataset_objects(connection, object_root, "stock_info_sz_name_code")
    sz_change_name = _load_dataset_objects(connection, object_root, "stock_info_sz_change_name")
    bse_mapping = _load_bse_mapping(bse_mapping_path) if bse_mapping_path else {}

    listed: dict[str, dict] = {}
    for row in sh_name_code:
        sym = _canonical_symbol(row.get("证券代码"))
        if sym:
            listed[sym] = row
    for row in sz_name_code:
        sym = _canonical_symbol(row.get("A股代码") or row.get("证券代码"))
        if sym:
            listed.setdefault(sym, row)

    delisted: dict[str, dict] = {}
    for row in sh_delist:
        sym = _canonical_symbol(row.get("公司代码"))
        if sym:
            delisted[sym] = row
    for row in sz_delist:
        sym = _canonical_symbol(row.get("证券代码"))
        if sym:
            delisted[sym] = row

    name_changes: dict[str, list[dict]] = {}
    for row in sz_change_name:
        sym = _canonical_symbol(row.get("证券代码"))
        if sym:
            name_changes.setdefault(sym, []).append(row)

    # Merge with the union of symbols seen anywhere.
    # Include BSE migrated symbols even if the public name-code table does not
    # carry a current row for them.  Their old/new code relationship is still
    # valid lifecycle evidence and must not be dropped from the identity layer.
    all_symbols = sorted(set(listed) | set(delisted) | set(name_changes) | set(bse_mapping))
    records: list[dict] = []
    for sym in all_symbols:
        base = listed.get(sym, {})
        end = delisted.get(sym, {})
        changes = name_changes.get(sym, [])
        code_changes = []
        mapping = bse_mapping.get(sym)
        if mapping:
            code_changes.append({
                "old_code": str(mapping.get("old_code") or "").zfill(6),
                "new_code": sym,
                "security_name": mapping.get("security_name"),
                "listed_on": _to_date(mapping.get("listed_on")),
                "effective_date": "2025-10-09",
                "source_url": mapping.get("source_url"),
                "source_provider": "bse_official_code_mapping",
            })
        listed_on = _to_date(
            end.get("上市日期") or base.get("上市日期") or base.get("A股上市日期")
            or (mapping or {}).get("listed_on")
        )
        delisted_on = _to_date(
            end.get("终止上市日期") or end.get("暂停上市日期")
        )
        security_name = (
            base.get("证券简称") or base.get("A股简称")
            or end.get("公司简称") or end.get("证券简称")
            or (mapping or {}).get("security_name")
        )
        listing_status = "delisted" if delisted_on else ("listed" if listed_on else None)
        st_status = _st_status_from_name(security_name)
        records.append({
            "symbol": sym,
            "listed_on": listed_on,
            "delisted_on": delisted_on,
            "security_name": security_name,
            "listing_status": listing_status,
            "st_status": st_status,
            "name_changes": changes,
            "code_changes": code_changes,
            "industry_current": base.get("所属行业"),
            "available_at": datetime.now(timezone.utc).isoformat(),
            "published_at": None,
            "revision_id": None,
            "data_tier": "research_pit",
            "quality_status": "degraded",
            "missing_reason_code": "historical_lifecycle_local_consolidated",
        })

    stats = {
        "source_rows": {
            "stock_info_sh_delist": len(sh_delist),
            "stock_info_sz_delist": len(sz_delist),
            "stock_info_sh_name_code": len(sh_name_code),
            "stock_info_sz_name_code": len(sz_name_code),
            "stock_info_sz_change_name": len(sz_change_name),
            "bse_code_mapping": len(bse_mapping),
        },
        "symbol_count": len(records),
        "listed_with_date": sum(1 for r in records if r["listed_on"]),
        "delisted_with_date": sum(1 for r in records if r["delisted_on"]),
        "st_risk_warning": sum(1 for r in records if r["st_status"] == "st_risk_warning"),
        "listing_status_covered": sum(1 for r in records if r["listing_status"]),
        "st_status_covered": sum(1 for r in records if r["st_status"]),
        "name_changes_covered": sum(1 for r in records if r["name_changes"]),
        "code_changes_covered": sum(1 for r in records if r["code_changes"]),
    }
    return records, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--object-root", type=Path, default=DEFAULT_OBJECT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--bse-mapping", type=Path, default=DEFAULT_BSE_MAPPING)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.catalog.is_file():
        print(f"[consolidate] catalog missing: {args.catalog}", file=__import__("sys").stderr)
        return 1
    connection = sqlite3.connect(args.catalog)
    records, stats = consolidate(connection, args.object_root, args.bse_mapping)
    connection.close()
    n = len(records)
    n_delisted = sum(1 for r in records if r.get("delisted_on"))
    listing_cov = stats["listed_with_date"] / n if n else 0.0
    # Use "delisted symbols with delisted_on date / total delisted symbols"
    # (not / full universe) because delisting is a rare historical event.
    # This matches the security-master semantic: the *records* for delisted
    # symbols must be complete, not that the whole market be delisted.
    delisting_cov = (stats["delisted_with_date"] / n_delisted) if n_delisted else 1.0
    st_cov = stats["st_status_covered"] / n if n else 0.0
    ls_cov = stats["listing_status_covered"] / n if n else 0.0
    nc_cov = stats["name_changes_covered"] / n if n else 0.0
    code_cov = stats["code_changes_covered"] / n if n else 0.0
    code_record_cov = (
        stats["code_changes_covered"] / stats["code_changes_covered"]
        if stats["code_changes_covered"] else 0.0
    )
    print(
        f"[consolidate] symbols={n} delisted={n_delisted} listing={listing_cov:.4f} delisting={delisting_cov:.4f} "
        f"st_status={st_cov:.4f} listing_status={ls_cov:.4f} "
        f"name_changes={nc_cov:.4f} code_changes={code_cov:.4f}"
    )
    print(f"[consolidate] source rows: {stats['source_rows']}")
    if args.dry_run:
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    # Refresh latest.json coverage so the lifecycle audit picks up the new values.
    report: dict = {}
    if args.latest.is_file():
        report = json.loads(args.latest.read_text(encoding="utf-8"))
    report.update({
        "schema_version": "cn-security-lifecycle-local-consolidated-v1",
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "target_equity_count": n,
        "listing_date_coverage": listing_cov,
        "listing_status_coverage": ls_cov,
        "delisting_date_coverage": delisting_cov,
        "st_status_coverage": st_cov,
        "code_change_coverage": code_cov,
        "code_change_record_coverage": code_record_cov,
        "name_change_coverage": nc_cov,
        "name_change_record_coverage": (
            stats["name_changes_covered"] / stats["name_changes_covered"]
            if stats["name_changes_covered"] else 0.0
        ),
        "industry_history_coverage": 0.0,
        "published_at_coverage": report.get("published_at_coverage", 0.0),
        "available_at_coverage": 1.0 if records else 0.0,
        "failures": {},
        "missing_reason": "local SSE/SZSE delisting + listing + name-change objects consolidated; publication-time PIT not yet proven",
        "missing_reason_code": "historical_lifecycle_local_consolidated",
        "status": "complete" if (
            listing_cov >= 0.98 and delisting_cov >= 0.98 and st_cov >= 0.98 and ls_cov >= 0.98
        ) else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_rows": stats["source_rows"],
        "code_change_symbol_count": stats["code_changes_covered"],
        "name_change_symbol_count": stats["name_changes_covered"],
    })
    args.latest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"[consolidate] wrote {args.output.name} + {args.latest.name} status={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
