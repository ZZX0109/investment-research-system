#!/usr/bin/env python3
"""Restore a price coverage ledger after a narrow retry replaced the ledger.

The collector intentionally replaces only the requested dataset groups.  A
manual full-history retry can therefore leave a small retry ledger in place
while the immutable price snapshot still exists in a prior generated ledger.
This command merges that prior price ledger with the current non-price records
and updates the CN market summary conservatively.  It never edits raw files or
promotes a snapshot; all hashes and provider statuses remain those recorded by
the source ledgers.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PRICE_DATASETS = {"daily_bars_raw", "daily_bars_qfq"}


def restore(target: Path, price_source: Path) -> dict:
    current = json.loads(target.read_text(encoding="utf-8"))
    source = json.loads(price_source.read_text(encoding="utf-8"))
    source_prices = [item for item in source.get("records", []) if item.get("dataset") in PRICE_DATASETS]
    if not source_prices:
        raise ValueError("price source ledger has no daily price records")
    non_prices = [item for item in current.get("records", []) if item.get("dataset") not in PRICE_DATASETS]
    payload = dict(source)
    payload["records"] = [*source_prices, *non_prices]
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["mode"] = "restored_price_ledger_with_narrow_retry_non_price_records"
    payload["formal_deployment_allowed"] = False
    payload["restore_lineage"] = {
        "price_source": str(price_source),
        "non_price_source": str(target),
        "raw_files_mutated": False,
        "snapshot_activated": False,
    }
    # The price snapshot's old market summary can say 100% for prices, but
    # non-price event records in the current ledger may be partial.  Keep the
    # exact target/success counts and make the summary visibly research-only.
    for market in payload.get("market_coverage", []):
        if market.get("market") == "cn":
            event = next((r for r in non_prices if r.get("dataset") == "events"), None)
            if event and event.get("status") not in {"complete", "backfilled"}:
                market["event_coverage_status"] = "partial"
                market["reasons"] = [
                    reason for reason in market.get("reasons", [])
                    if not str(reason).startswith("event_coverage:")
                ]
                market["reasons"].append("event_coverage:partial")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--price-source", type=Path, default=PROJECT / "artifacts/free_research_coverage_aligned.json")
    args = parser.parse_args()
    payload = restore(args.target, args.price_source)
    temporary = args.target.with_suffix(args.target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.target)
    print(json.dumps({"status": "restored", "records": len(payload["records"]), "target": str(args.target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
