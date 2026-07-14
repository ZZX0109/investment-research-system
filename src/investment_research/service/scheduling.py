from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from investment_research.domain.models import ReportSchedule, User
from investment_research.repository.sqlite import (
    SQLiteUnitOfWork,
    create_unit_of_work,
)
from investment_research.report.service import ReportService
from investment_research.service.outbox import OutboxService
from investment_research.service.advanced_research import (
    AssetRefreshService,
    _real_provenance,
)
from investment_research.workers.paper_validation import PaperValidationWorker
from investment_research.service.market_observation import MarketObservationService
from investment_research.service.ingestion_jobs import IngestionJobService


def next_run(frequency: str, now: datetime) -> datetime | None:
    if frequency == "manual":
        return None
    if frequency == "event_triggered":
        return None
    if frequency == "daily":
        return now + timedelta(days=1)
    if frequency == "weekly":
        return now + timedelta(days=7)
    return now + timedelta(days=30)


class ReportScheduleService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def create(
        self,
        *,
        user: User,
        frequency: str,
        asset_id: str | None,
        enabled: bool = True,
        timezone_name: str = "Asia/Shanghai",
    ) -> ReportSchedule:
        if frequency not in {"manual", "daily", "weekly", "monthly", "event_triggered"}:
            raise ValueError("Unsupported frequency")
        if asset_id and self.uow.assets.get(asset_id) is None:
            raise ValueError("Asset not found")
        now = datetime.now(timezone.utc)
        item = ReportSchedule(
            user_id=user.id,
            asset_id=None if asset_id is None else UUID(asset_id),
            frequency=frequency,
            enabled=enabled,
            next_run_at=next_run(frequency, now) if enabled else None,
            timezone=timezone_name,
            provenance=_real_provenance("report-schedule", now),
        )
        return self.uow.report_schedules.add(item)

    def list(self, *, user: User) -> list[ReportSchedule]:
        return self.uow.report_schedules.list_for_user(str(user.id))

    def update(
        self,
        schedule_id: str,
        *,
        user: User,
        frequency: str | None = None,
        enabled: bool | None = None,
    ) -> ReportSchedule:
        item = self.uow.report_schedules.get(schedule_id)
        if item is None or item.user_id != user.id:
            raise ValueError("Report schedule not found")
        now = datetime.now(timezone.utc)
        resolved_frequency = frequency or item.frequency
        resolved_enabled = item.enabled if enabled is None else enabled
        updated = item.model_copy(
            update={
                "frequency": resolved_frequency,
                "enabled": resolved_enabled,
                "next_run_at": next_run(resolved_frequency, now)
                if resolved_enabled
                else None,
                "updated_at": now,
            }
        )
        return self.uow.report_schedules.add(updated)

    def delete(self, schedule_id: str, *, user: User) -> None:
        item = self.uow.report_schedules.get(schedule_id)
        if item is None or item.user_id != user.id:
            raise ValueError("Report schedule not found")
        self.uow.report_schedules.delete(schedule_id)


class LocalResearchScheduler:
    def __init__(self) -> None:
        self.scheduler = None

    def start(self) -> None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError:
            return
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.scheduler.add_job(
            self.tick,
            "interval",
            minutes=1,
            id="research-schedule-tick",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler:
            self.scheduler.shutdown(wait=False)

    def tick(self) -> None:
        uow = create_unit_of_work()
        now = datetime.now(timezone.utc)
        try:
            OutboxService(uow).drain(limit=100)
            PaperValidationWorker(uow).tick(now)
            market_service = MarketObservationService(uow, clock=lambda: now)
            for asset_id in uow.paper_observations.pending_asset_ids():
                asset = uow.assets.get(asset_id)
                if asset is not None:
                    IngestionJobService(uow, clock=lambda: now).enqueue(
                        job_type="daily_close_confirmation",
                        symbols=[asset.ticker],
                        requested_by="scheduler",
                        idempotency_key=f"market-observation:{asset_id}:{now.strftime('%Y%m%d%H%M')}",
                        priority=20,
                    )
            def refresh_market_job(job):
                for symbol in job.symbols:
                    assets = [asset for asset in uow.assets.list() if asset.ticker == symbol]
                    for asset in assets:
                        market_service.refresh(str(asset.id))
                return IngestionJobService(uow, clock=lambda: now).complete(job, coverage_ratio=1.0, latest_source_time=now)
            IngestionJobService(uow, clock=lambda: now).drain(
                {"daily_close_confirmation": refresh_market_job}, limit=100
            )
            timed = uow.report_schedules.list_due(now.isoformat())
            event_triggered = [
                item
                for item in uow.report_schedules.list_active()
                if item.frequency == "event_triggered"
                and self._has_new_event(uow, item)
            ]
            for schedule in [*timed, *event_triggered]:
                auth = uow.users.get_by_id(str(schedule.user_id))
                if auth is None or schedule.asset_id is None:
                    continue
                result = AssetRefreshService(uow).refresh_and_analyze(
                    str(schedule.asset_id), user=auth.user
                )
                if result.analysis_bundle is not None:
                    ReportService(uow).create_report_from_bundle(result.analysis_bundle)
                uow.report_schedules.add(
                    schedule.model_copy(
                        update={
                            "last_run_at": now,
                            "next_run_at": next_run(schedule.frequency, now),
                            "updated_at": now,
                        }
                    )
                )
        finally:
            uow.close()

    def _has_new_event(self, uow: SQLiteUnitOfWork, schedule: ReportSchedule) -> bool:
        if schedule.asset_id is None:
            return False
        evidence = uow.evidence.list_for_asset(str(schedule.asset_id))
        if not evidence:
            return False
        latest = max((item.published_at or item.collected_at) for item in evidence)
        return schedule.last_run_at is None or latest > schedule.last_run_at
