from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
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
from investment_research.service.research_lifecycle import ResearchLifecycleService


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
            # Persist the zero-budget research cadence separately from user
            # report schedules.  The planner is idempotent, so the minute
            # tick can safely run on weekends, holidays, and process restarts;
            # it will never create a second job for the same market/date.
            ResearchLifecycleService(uow, clock=lambda: now).plan(
                now=now, market="cn", decision_context="close_confirmed", enqueue=True,
            )
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
            self._drain_research_jobs(uow, now)
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

    def _drain_research_jobs(self, uow: SQLiteUnitOfWork, now: datetime) -> None:
        """Execute short collection/audit jobs; training belongs to its worker.

        The scheduler only dispatches bounded jobs.  The two potentially
        multi-hour research training jobs remain queued for
        ``scripts/run_training_worker.py`` so an APScheduler tick cannot hold
        a scheduler slot for 24 hours.
        """
        project = Path(__file__).resolve().parents[3]
        service = IngestionJobService(uow, clock=lambda: now)

        def run_script(job):
            if job.job_type == "research_daily_close":
                command = [
                    sys.executable,
                    str(project / "scripts/run_free_research_cycle.py"),
                    "--groups", "prices", "events",
                    "--run-directory", str(project / "artifacts" / "research_lifecycle" / "daily-runs"),
                ]
            elif job.job_type == "research_label_backfill":
                # Outcome backfill needs the exact per-symbol standard
                # manifest.  Keep the job durable and explicit until that
                # manifest is present; never fabricate a completed outcome.
                return service.complete(
                    job, degraded=True,
                    quality_issues=["shadow_backfill_waiting_for_matching_standard_manifest"],
                    artifact_version="backfill-pending-manifest",
                )
            elif job.job_type == "research_weekly_monitor":
                return self._write_research_monitor_report(job, project, now, service)
            elif job.job_type == "knowledge_daily_incremental":
                command = [sys.executable, str(project / "scripts/sync_financial_knowledge.py"), "--mode", "incremental"]
            elif job.job_type == "knowledge_historical_backfill":
                command = [sys.executable, str(project / "scripts/sync_financial_knowledge.py"), "--mode", "backfill"]
            elif job.job_type == "knowledge_weekly_audit":
                command = [sys.executable, str(project / "scripts/audit_financial_knowledge.py")]
            elif job.job_type == "knowledge_monthly_reindex":
                command = [sys.executable, str(project / "scripts/reindex_financial_knowledge.py")]
            elif job.job_type == "knowledge_document_fetch":
                if len(job.symbols) != 1:
                    raise ValueError("knowledge_document_fetch requires one document ID")
                command = [
                    sys.executable, str(project / "scripts/fetch_financial_document.py"),
                    "--document-id", job.symbols[0],
                ]
            elif job.job_type in {"research_model_promotion", "research_model_rollback"}:
                # Promotion/rollback records are deliberately explicit jobs.
                # A worker may not infer eligibility from a missing artifact;
                # the caller must provide a complete candidate/rollback
                # evidence bundle and the ResearchPromotionStore performs the
                # final boundary validation before changing the pointer.
                return service.complete(
                    job,
                    degraded=True,
                    quality_issues=["promotion_requires_explicit_research_gate_evidence"],
                    artifact_version="promotion-pending-evidence",
                )
            else:
                raise ValueError(f"unsupported research lifecycle job: {job.job_type}")
            completed = subprocess.run(
                command, cwd=project, text=True, capture_output=True,
                timeout=24 * 60 * 60, check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"{job.job_type} failed: {completed.stderr[-500:]}")
            if job.job_type == "research_daily_close":
                prediction_count = self._run_daily_research_inference(
                    project=project,
                    now=now,
                    job=job,
                    collection_stdout=completed.stdout,
                )
                return service.complete(
                    job,
                    coverage_ratio=1.0,
                    artifact_version=f"{job.job_type}:{now:%Y%m%d}:predictions={prediction_count}",
                    latest_source_time=now,
                )
            return service.complete(
                job, coverage_ratio=1.0,
                artifact_version=f"{job.job_type}:{now:%Y%m%d}",
                latest_source_time=now,
            )

        service.drain(
            {
                "research_daily_close": run_script,
                "research_weekly_monitor": run_script,
                "research_label_backfill": run_script,
                "research_model_promotion": run_script,
                "research_model_rollback": run_script,
                "knowledge_daily_incremental": run_script,
                "knowledge_historical_backfill": run_script,
                "knowledge_weekly_audit": run_script,
                "knowledge_monthly_reindex": run_script,
                "knowledge_document_fetch": run_script,
            },
            limit=5,
            allowed_job_types={
                "research_daily_close", "research_weekly_monitor",
                "research_label_backfill", "research_model_promotion",
                "research_model_rollback", "knowledge_daily_incremental",
                "knowledge_historical_backfill", "knowledge_weekly_audit",
                "knowledge_monthly_reindex", "knowledge_document_fetch",
            },
        )

    def _run_daily_research_inference(
        self,
        *,
        project: Path,
        now: datetime,
        job,
        collection_stdout: str,
    ) -> int:
        """Run roster-bound inference after a successful daily rebuild.

        A missing rebuild index or roster is not converted into a fake
        probability.  In that case the cycle freezes one explicit abstain
        placeholder from the coverage ledger.  Once a research roster exists,
        the same immutable prediction file is passed to the Shadow freezer.
        """
        index_path = self._rebuild_index_from_cycle_report(collection_stdout)
        prediction_root = project / "artifacts" / "research_lifecycle" / "daily-predictions"
        shadow_root = project / "artifacts" / "research_shadow" / "daily"
        prediction_root.mkdir(parents=True, exist_ok=True)
        shadow_root.mkdir(parents=True, exist_ok=True)
        prediction_files: list[Path] = []
        if index_path is not None and index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                index = {}
            context = index.get("contexts", {}).get("close_confirmed", {}) if isinstance(index, dict) else {}
            for cohort in ("cn_equity_core", "cn_etf_benchmark"):
                cohort_ref = index.get("cohort_refs", {}).get(cohort) if isinstance(index, dict) else None
                if not cohort_ref:
                    continue
                try:
                    cohort_payload = json.loads(Path(cohort_ref).read_text(encoding="utf-8"))
                    symbols = [str(item["symbol"]) for item in cohort_payload.get("members", []) if item.get("symbol")]
                except (OSError, ValueError, KeyError, TypeError):
                    continue
                if not symbols or not context.get("sample_manifests"):
                    continue
                output = prediction_root / f"{job.id}-{cohort}.json"
                command = [
                    sys.executable,
                    str(project / "scripts" / "run_cn_research_inference.py"),
                    "--rebuild-index", str(index_path),
                    "--roster-root", str(project / "artifacts" / "free_research_models"),
                    "--cohort", cohort,
                    "--symbols", *symbols,
                    "--output", str(output),
                ]
                result = subprocess.run(command, cwd=project, text=True, capture_output=True, timeout=24 * 60 * 60, check=False)
                if result.returncode == 0 and output.is_file():
                    prediction_files.append(output)
        freeze_base = [
            sys.executable,
            str(project / "scripts" / "run_free_research_cycle.py"),
            "--skip-collection", "--skip-rebuild", "--freeze-shadow",
            "--shadow-directory", str(shadow_root),
            "--run-directory", str(project / "artifacts" / "research_lifecycle" / "daily-runs"),
        ]
        if prediction_files:
            for prediction in prediction_files:
                subprocess.run(
                    [*freeze_base, "--prediction-file", str(prediction)],
                    cwd=project, text=True, capture_output=True, timeout=30 * 60, check=False,
                )
        else:
            # No valid roster/index: still create a transparent abstain
            # session so daily evidence accumulation does not disappear.
            subprocess.run(freeze_base, cwd=project, text=True, capture_output=True, timeout=30 * 60, check=False)
        return len(prediction_files)

    @staticmethod
    def _latest_json_path(output: str) -> Path | None:
        for line in reversed((output or "").splitlines()):
            candidate = Path(line.strip())
            if candidate.suffix == ".json" and candidate.is_file():
                return candidate
        return None

    @classmethod
    def _rebuild_index_from_cycle_report(cls, output: str) -> Path | None:
        report_path = cls._latest_json_path(output)
        if report_path is None:
            return None
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        for item in report.get("results", []):
            if item.get("group") != "pit_rebuild":
                continue
            return cls._latest_json_path(str(item.get("stdout", "")))
        return None

    @staticmethod
    def _write_research_monitor_report(job, project: Path, now: datetime, service: IngestionJobService):
        acceptance = project / "artifacts" / "cn_research_demo" / "latest-backend-acceptance.json"
        payload = {}
        if acceptance.is_file():
            try:
                payload = json.loads(acceptance.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        metrics = {
            "coverage_ratio": float(data.get("coverage_ratio", 1.0) or 1.0),
            "provider_failure_rate": float(data.get("provider_failure_rate", 0.0) or 0.0),
            "abstain_rate": float(data.get("abstain_rate", 0.0) or 0.0),
            "psi": float(data.get("psi", 0.0) or 0.0),
            "brier_delta": float(data.get("brier_delta", 0.0) or 0.0),
            "ece_delta": float(data.get("ece_delta", 0.0) or 0.0),
            "leakage_errors": int(data.get("leakage_errors", 0) or 0),
        }
        decision = ResearchLifecycleService.__new__(ResearchLifecycleService).monitor(metrics)
        report_root = project / "artifacts" / "research_lifecycle"
        report_root.mkdir(parents=True, exist_ok=True)
        report_path = report_root / f"monitor-{now:%Y%m%dT%H%M%SZ}.json"
        report_path.write_text(json.dumps({
            "schema_version": "research-monitor-v1",
            "data_tier": "research_pit", "status": "research_only", "deployment_ready": False,
            "job_id": str(job.id), "as_of": now.isoformat(), "metrics": metrics,
            "decision": {"status": decision.status, "trigger_reasons": list(decision.trigger_reasons)},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return service.complete(job, degraded=decision.status != "healthy", quality_issues=list(decision.trigger_reasons), artifact_version=str(report_path.relative_to(project)))

    def _has_new_event(self, uow: SQLiteUnitOfWork, schedule: ReportSchedule) -> bool:
        if schedule.asset_id is None:
            return False
        evidence = uow.evidence.list_for_asset(str(schedule.asset_id))
        if not evidence:
            return False
        latest = max((item.published_at or item.collected_at) for item in evidence)
        return schedule.last_run_at is None or latest > schedule.last_run_at
