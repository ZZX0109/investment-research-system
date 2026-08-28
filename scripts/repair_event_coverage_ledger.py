#!/usr/bin/env python3
"""Retain the last non-empty CNINFO event window after a provider outage."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def repair(target: Path, fallback: Path) -> dict:
    payload = json.loads(target.read_text(encoding="utf-8"))
    backup = json.loads(fallback.read_text(encoding="utf-8"))
    records = list(payload.get("records", []))
    candidates = [
        item for item in backup.get("records", [])
        if item.get("provider") == "akshare_cninfo_notices"
        and item.get("dataset") == "events"
        and item.get("status") in {"partial", "backfilled"}
        and int(item.get("rows_or_bytes", 0) or 0) > 0
    ]
    if not candidates:
        raise ValueError("fallback event ledger has no non-empty partial record")
    failed = [
        item for item in records
        if item.get("provider") == "akshare_cninfo_notices" and item.get("dataset") == "events"
    ]
    if not failed or not all(item.get("status") == "fetch_failed" for item in failed):
        return payload
    retained = dict(candidates[-1])
    retained["reason"] = "provider_retry_failed_previous_partial_retained:" + str(failed[-1].get("reason") or "fetch_failed")
    payload["records"] = [
        item for item in records
        if not (item.get("provider") == "akshare_cninfo_notices" and item.get("dataset") == "events")
    ] + [retained]
    for market in payload.get("market_coverage", []):
        if market.get("market") != "cn":
            continue
        market["event_coverage_status"] = "partial"
        market["failed_providers"] = [provider for provider in market.get("failed_providers", []) if provider != "akshare_cninfo_notices"]
        market["reasons"] = [reason for reason in market.get("reasons", []) if not str(reason).startswith("event_coverage:")]
        market["reasons"].append("event_coverage:partial")
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--fallback", type=Path, default=PROJECT / "artifacts/free_research_coverage_events_inc.json")
    args = parser.parse_args()
    payload = repair(args.target, args.fallback)
    temporary = args.target.with_suffix(args.target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.target)
    print(json.dumps({"status": "repaired", "target": str(args.target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
