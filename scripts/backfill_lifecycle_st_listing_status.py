#!/usr/bin/env python3
"""Backfill st_status / listing_status onto the persisted security lifecycle
artifact without re-hitting the akshare network.

The public name_code tables (stock_info_sh_name_code / stock_info_sz_name_code)
already carry the ST / *ST prefix in the security-name column, and the listed_on
/ delisted_on dates are already persisted in security_lifecycle.json.  This
script re-derives the two lifecycle fields the contract requires and rewrites
both security_lifecycle.json and latest.json in place so the lifecycle coverage
audit reflects the derivable coverage instead of the legacy hard-coded zero.

This is a research-only re-derivation: it does not invent new publication
times or new effective intervals, and it leaves formal_pit_verified unchanged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_LIFECYCLE = PROJECT / "artifacts/cn_security_lifecycle_full/security_lifecycle.json"
DEFAULT_LATEST = PROJECT / "artifacts/cn_security_lifecycle_full/latest.json"


def _derive_fields(row: dict) -> dict:
    security_name = row.get("security_name")
    listed_on = row.get("listed_on")
    delisted_on = row.get("delisted_on")
    if security_name and ("ST" in str(security_name) or "*ST" in str(security_name)):
        st_status = "st_risk_warning"
    elif security_name:
        st_status = "normal"
    else:
        st_status = None
    if delisted_on:
        listing_status = "delisted"
    elif listed_on:
        listing_status = "listed"
    else:
        listing_status = None
    row = dict(row)
    row["st_status"] = st_status
    row["listing_status"] = listing_status
    return row


def _coverage(rows: list[dict], field: str) -> float:
    if not rows:
        return 0.0
    return sum(bool(r.get(field)) for r in rows) / len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle", type=Path, default=DEFAULT_LIFECYCLE)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.lifecycle.is_file():
        print(f"[backfill] lifecycle missing: {args.lifecycle}", file=__import__("sys").stderr)
        return 1
    data = json.loads(args.lifecycle.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else (data.get("rows") or (list(data.values())[0] if data else []))
    if not isinstance(rows, list):
        print("[backfill] unexpected lifecycle shape", file=__import__("sys").stderr)
        return 1
    rewritten = [_derive_fields(r) for r in rows]
    st_cov = _coverage(rewritten, "st_status")
    ls_cov = _coverage(rewritten, "listing_status")
    listing_cov = _coverage(rewritten, "listed_on")
    print(f"[backfill] rows={len(rewritten)} st_status_coverage={st_cov:.4f} listing_status_coverage={ls_cov:.4f} (was 0.0/0.0)")

    if args.dry_run:
        return 0
    args.lifecycle.write_text(
        json.dumps(rewritten, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    # Refresh latest.json so the lifecycle audit picks up the new coverage.
    report: dict = {}
    if args.latest.is_file():
        report = json.loads(args.latest.read_text(encoding="utf-8"))
    report["st_status_coverage"] = st_cov
    report["listing_status_coverage"] = ls_cov
    report["listing_date_coverage"] = listing_cov
    report["delisting_date_coverage"] = _coverage(rewritten, "delisted_on")
    # Keep code migrations separate from ordinary legal-name changes. Older
    # backfill runs used ``name_changes`` here, which inflated this metric.
    report["code_change_coverage"] = _coverage(rewritten, "code_changes")
    report["code_change_record_coverage"] = (
        sum(bool(r.get("code_changes")) for r in rewritten)
        / sum(bool(r.get("code_changes")) for r in rewritten)
        if any(r.get("code_changes") for r in rewritten)
        else 0.0
    )
    report["name_change_coverage"] = _coverage(rewritten, "name_changes")
    report["industry_history_coverage"] = _coverage(rewritten, "industry_history")
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["status"] = "complete" if (
        report.get("st_status_coverage", 0) >= 0.98
        and report.get("listing_status_coverage", 0) >= 0.98
        and report.get("listing_date_coverage", 0) >= 0.98
        and report.get("published_at_coverage", 0) >= 0.98
        and not report.get("failures")
    ) else "partial"
    args.latest.parent.mkdir(parents=True, exist_ok=True)
    args.latest.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"[backfill] wrote {args.lifecycle.name} + {args.latest.name} status={report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
