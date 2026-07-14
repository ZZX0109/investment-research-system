from datetime import datetime, timedelta, timezone

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.ingestion_jobs import IngestionJobService


def test_job_is_idempotent_cancelable_and_retryable(tmp_path) -> None:
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    clock = [now]
    uow = SQLiteUnitOfWork(tmp_path / "jobs.db")
    service = IngestionJobService(uow, clock=lambda: clock[0])
    first = service.enqueue(job_type="announcement_incremental", symbols=["600519.SH"], requested_by="user", idempotency_key="same")
    again = service.enqueue(job_type="announcement_incremental", symbols=["600519.SH"], requested_by="user", idempotency_key="same")
    assert first.id == again.id

    running = service.mark_running(first)
    failed = service.fail(running, RuntimeError("temporary"))
    assert failed.state == "retrying"
    assert failed.next_attempt_at is not None
    clock[0] = failed.next_attempt_at + timedelta(seconds=1)
    assert service.uow.ingestion_jobs.runnable(clock[0])[0].id == first.id

    cancelled = service.cancel(str(first.id), requested_by="user")
    assert cancelled.state == "cancelled"
