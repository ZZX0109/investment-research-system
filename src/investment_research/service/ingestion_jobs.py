from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from investment_research.domain.trusted_market import IngestionJob, JobType
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.config import get_app_settings


JobHandler = Callable[[IngestionJob], IngestionJob]


class IngestionJobService:
    def __init__(self, uow: SQLiteUnitOfWork, *, clock=None) -> None:
        self.uow = uow
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def enqueue(
        self,
        *,
        job_type: JobType,
        symbols: list[str],
        requested_by: str,
        idempotency_key: str | None = None,
        priority: int = 100,
        scheduled_for: datetime | None = None,
        market: str | None = None,
        decision_context: str | None = None,
        trade_date: date | None = None,
        cutoff_time: datetime | None = None,
        market_snapshot_id: str | None = None,
        market_snapshot_hash: str | None = None,
        dataset_hash: str | None = None,
        training_run_id: str | None = None,
        candidate_version: str | None = None,
        report_hash: str | None = None,
        rollback_version: str | None = None,
        data_tier: str | None = None,
    ) -> IngestionJob:
        if job_type == "minute_collection" and not get_app_settings().minute_collection_enabled:
            raise ValueError("minute collection is disabled until licensed source, latency, completeness, and failover gates pass")
        now = self.clock()
        key = idempotency_key or self._key(job_type, symbols, now)
        existing = self.uow.ingestion_jobs.by_idempotency_key(key)
        if existing is not None:
            return existing
        return self.uow.ingestion_jobs.add(
            IngestionJob(
                idempotency_key=key,
                job_type=job_type,
                symbols=sorted(set(symbols)),
                requested_by=requested_by,
                priority=priority,
                created_at=now,
                scheduled_for=scheduled_for or now,
                market=market,
                decision_context=decision_context,
                trade_date=trade_date,
                cutoff_time=cutoff_time,
                market_snapshot_id=market_snapshot_id,
                market_snapshot_hash=market_snapshot_hash,
                dataset_hash=dataset_hash,
                training_run_id=training_run_id,
                candidate_version=candidate_version,
                report_hash=report_hash,
                rollback_version=rollback_version,
                data_tier=data_tier,
            )
        )

    def get(self, job_id: str, *, requested_by: str | None = None) -> IngestionJob:
        item = self.uow.ingestion_jobs.get(job_id)
        if item is None or (requested_by is not None and item.requested_by != requested_by):
            raise ValueError("Ingestion job not found")
        return item

    def cancel(self, job_id: str, *, requested_by: str) -> IngestionJob:
        item = self.get(job_id, requested_by=requested_by)
        if item.state in {"succeeded", "degraded", "failed", "cancelled"}:
            return item
        now = self.clock()
        state = "cancelled" if item.state in {"queued", "retrying"} else item.state
        return self.uow.ingestion_jobs.add(
            item.model_copy(update={"cancel_requested": True, "state": state, "completed_at": now if state == "cancelled" else None})
        )

    def mark_running(self, item: IngestionJob) -> IngestionJob:
        if item.cancel_requested:
            return self.uow.ingestion_jobs.add(item.model_copy(update={"state": "cancelled", "completed_at": self.clock()}))
        return self.uow.ingestion_jobs.add(
            item.model_copy(update={"state": "running", "started_at": item.started_at or self.clock(), "attempts": item.attempts + 1})
        )

    def complete(
        self,
        item: IngestionJob,
        *,
        degraded: bool = False,
        coverage_ratio: float = 1.0,
        quality_issues: list[str] | None = None,
        artifact_version: str | None = None,
        latest_source_time: datetime | None = None,
    ) -> IngestionJob:
        issues = quality_issues or []
        return self.uow.ingestion_jobs.add(
            item.model_copy(
                update={
                    "state": "degraded" if degraded else "succeeded",
                    "completed_at": self.clock(),
                    "coverage_ratio": coverage_ratio,
                    "quality_status": "degraded" if degraded else "passed",
                    "quality_issues": issues,
                    "artifact_version": artifact_version,
                    "latest_source_time": latest_source_time,
                }
            )
        )

    def fail(self, item: IngestionJob, exc: Exception) -> IngestionJob:
        now = self.clock()
        retryable = item.attempts < item.max_attempts and not item.cancel_requested
        delay = min(300, 2 ** max(1, item.attempts))
        return self.uow.ingestion_jobs.add(
            item.model_copy(
                update={
                    "state": "retrying" if retryable else "failed",
                    "next_attempt_at": now + timedelta(seconds=delay) if retryable else None,
                    "completed_at": None if retryable else now,
                    "quality_status": "failed",
                    "error_code": type(exc).__name__,
                    "error_message": str(exc)[:1000],
                }
            )
        )

    def drain(
        self,
        handlers: dict[str, JobHandler],
        *,
        limit: int = 20,
        allowed_job_types: set[str] | None = None,
    ) -> dict[str, int]:
        """Run a bounded set of durable jobs owned by one worker role.

        ``allowed_job_types`` is important when the same durable queue is
        shared by the scheduler, collection worker and long-running training
        worker: a worker must leave jobs owned by another role queued instead
        of marking them as unsupported.
        """
        result = {"succeeded": 0, "degraded": 0, "failed": 0, "skipped": 0}
        runnable = self.uow.ingestion_jobs.runnable(
            self.clock(),
            limit=max(limit, 100) if allowed_job_types else limit,
        )
        if allowed_job_types is not None:
            runnable = [item for item in runnable if item.job_type in allowed_job_types][:limit]
        for queued in runnable:
            item = self.mark_running(queued)
            if item.state == "cancelled":
                result["skipped"] += 1
                continue
            handler = handlers.get(item.job_type)
            if handler is None:
                self.fail(item, LookupError(f"No handler registered for {item.job_type}"))
                result["failed"] += 1
                continue
            try:
                completed = handler(item)
                if completed.state not in {"succeeded", "degraded"}:
                    completed = self.complete(completed)
                result[completed.state] += 1
            except Exception as exc:
                failed = self.fail(item, exc)
                result["failed" if failed.state == "failed" else "skipped"] += 1
        return result

    @staticmethod
    def _key(job_type: str, symbols: list[str], now: datetime) -> str:
        bucket = now.replace(second=0, microsecond=0).isoformat()
        raw = f"{job_type}|{','.join(sorted(set(symbols)))}|{bucket}".encode()
        return hashlib.sha256(raw).hexdigest()
