#!/usr/bin/env python3
"""Create an auditable minimal rebuild plan from data revisions.

The command is intentionally planning-only: it does not mutate raw data,
snapshots, model rosters, or the active pointer.  A scheduler can consume the
result to rebuild only the affected symbol/date ranges and then invalidate the
referenced evidence artifacts.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.incremental_rebuild import DataRevisionChange, plan_incremental_rebuild


def _change(item: dict) -> DataRevisionChange:
    required = ("dataset", "symbol", "start_date", "end_date", "new_revision_id")
    missing = [key for key in required if not item.get(key)]
    if missing:
        raise ValueError("revision change missing: " + ",".join(missing))
    start = date.fromisoformat(str(item["start_date"])[:10])
    end = date.fromisoformat(str(item["end_date"])[:10])
    if end < start:
        raise ValueError("revision change end_date precedes start_date")
    return DataRevisionChange(
        dataset=str(item["dataset"]),
        symbol=str(item["symbol"]),
        start_date=start,
        end_date=end,
        old_revision_id=str(item["old_revision_id"]) if item.get("old_revision_id") else None,
        new_revision_id=str(item["new_revision_id"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changes", type=Path, required=True, help="JSON array or object with a changes array")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feature-lookback-sessions", type=int, default=60)
    parser.add_argument("--label-horizons", type=int, nargs="+", default=[60, 120, 240])
    parser.add_argument("--trading-calendar", type=Path, help="JSON array of verified YYYY-MM-DD trading dates")
    parser.add_argument("--snapshot-id", action="append", default=[])
    parser.add_argument("--model-version", action="append", default=[])
    args = parser.parse_args()
    payload = json.loads(args.changes.read_text(encoding="utf-8"))
    raw_changes = payload.get("changes", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_changes, list):
        raise SystemExit("changes must be a JSON array or an object containing changes[]")
    changes = [_change(item) for item in raw_changes if isinstance(item, dict)]
    trading_dates = ()
    calendar_status = "not_supplied_calendar_day_fallback"
    if args.trading_calendar:
        calendar_payload = json.loads(args.trading_calendar.read_text(encoding="utf-8"))
        if not isinstance(calendar_payload, list):
            raise SystemExit("trading calendar must be a JSON array")
        trading_dates = tuple(sorted({date.fromisoformat(str(item)[:10]) for item in calendar_payload}))
        calendar_status = "verified_input_calendar"
    plan = plan_incremental_rebuild(
        changes,
        feature_lookback_sessions=args.feature_lookback_sessions,
        label_horizons=tuple(args.label_horizons),
        trading_dates=trading_dates,
        snapshot_ids=tuple(args.snapshot_id),
        model_versions=tuple(args.model_version),
    )
    output = {
        "schema_version": "incremental-rebuild-plan-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "planned",
        "data_tier": "research_pit",
        "deployment_ready": False,
        "change_count": len(changes),
        "trading_calendar_status": calendar_status,
        "changes": [item.__dict__ | {"start_date": item.start_date.isoformat(), "end_date": item.end_date.isoformat()} for item in changes],
        "plan": plan.as_dict(),
        "notes": [
            "Planning-only artifact; no raw object, snapshot, model, roster, or active pointer was changed.",
            "Downstream artifacts must verify the new revision hash before replacement.",
        ],
    }
    canonical = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    output["plan_hash"] = hashlib.sha256(canonical).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "change_count": len(changes), "plan_hash": output["plan_hash"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
