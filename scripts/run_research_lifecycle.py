#!/usr/bin/env python3
"""Run one bounded research lifecycle tick.

The command is safe to call from cron/launchd/APScheduler every few minutes.
Daily ticks collect and freeze research data; monthly/quarterly ticks enqueue
training jobs for ``run_training_worker.py`` rather than running them in this
bounded command. No path in this script can promote a free-data artifact to
formal deployment.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import create_unit_of_work
from investment_research.service.ingestion_jobs import IngestionJobService
from investment_research.service.research_lifecycle import ResearchLifecycleService
from investment_research.service.scheduling import LocalResearchScheduler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded CN research lifecycle")
    parser.add_argument("--as-of", type=datetime.fromisoformat, default=None)
    parser.add_argument("--trading-dates-file", type=Path, default=None)
    parser.add_argument("--execute", action="store_true", help="Run due data/training subprocesses")
    parser.add_argument("--skip-daily-data", action="store_true")
    parser.add_argument("--skip-training", action="store_true")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/research_lifecycle/latest.json")
    return parser.parse_args()


def _load_dates(path: Path | None) -> list[date]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("cn", payload.get("XSHG", []))
    if not isinstance(payload, list):
        raise ValueError("trading dates file must contain a list or a cn list")
    return sorted({date.fromisoformat(str(item)) for item in payload})


def main() -> int:
    args = parse_args()
    now = args.as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    dates = _load_dates(args.trading_dates_file)
    uow = create_unit_of_work()
    try:
        lifecycle = ResearchLifecycleService(uow, clock=lambda: now)
        plan = lifecycle.plan(now=now, trading_dates=dates or None, enqueue=True)
        report = {
            "schema_version": "research-lifecycle-run-v1",
            "run_id": f"research-lifecycle-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}",
            "as_of": now.isoformat(),
            "latest_trade_date": None if plan.latest_trade_date is None else plan.latest_trade_date.isoformat(),
            "mature_training_cutoff": None if plan.mature_training_cutoff is None else plan.mature_training_cutoff.isoformat(),
            "due_jobs": list(plan.jobs),
            "plan_reasons": list(plan.reasons),
            "data_tier": "research_pit",
            "status": "research_only",
            "deployment_ready": False,
            "executions": [],
        }

        if args.execute and plan.latest_trade_date is not None:
            skipped_types: set[str] = set()
            if args.skip_daily_data:
                skipped_types.add("research_daily_close")
            if args.skip_training:
                skipped_types.update({"research_monthly_training", "research_quarterly_challenger"})
            if skipped_types:
                jobs = uow.ingestion_jobs.list_recent(limit=100)
                cancellation = IngestionJobService(uow, clock=lambda: now)
                for item in jobs:
                    if (
                        item.job_type in skipped_types
                        and item.market == "cn"
                        and item.decision_context == "close_confirmed"
                        and item.trade_date == plan.latest_trade_date
                        and item.requested_by == "research-lifecycle"
                    ):
                        cancellation.cancel(str(item.id), requested_by="research-lifecycle")
            # Reuse the same durable short-job dispatcher as APScheduler.
            # Training jobs intentionally remain queued for the dedicated
            # run_training_worker.py process; this bounded command never
            # blocks on a multi-hour subprocess.
            LocalResearchScheduler()._drain_research_jobs(uow, now)
            planned_types = set(plan.jobs)
            for item in uow.ingestion_jobs.list_recent(limit=100):
                if (
                    item.job_type in planned_types
                    and item.market == "cn"
                    and item.decision_context == "close_confirmed"
                    and item.trade_date == plan.latest_trade_date
                ):
                    report["executions"].append({
                        "job_id": str(item.id),
                        "label": item.job_type,
                        "state": item.state,
                        "attempts": item.attempts,
                        "quality_issues": item.quality_issues,
                        "artifact_version": item.artifact_version,
                        "error_code": item.error_code,
                        "error_message": item.error_message,
                        "skipped_by_request": item.job_type in skipped_types,
                        "execution_mode": "training_worker"
                        if item.job_type in {"research_monthly_training", "research_quarterly_challenger"}
                        else "scheduler",
                    })
    finally:
        uow.close()

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    failed = [
        item for item in report["executions"]
        if item.get("state") in {"failed", "retrying"}
    ]
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
