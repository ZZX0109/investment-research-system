"""Dedicated long-running research training worker.

The API and minute scheduler only enqueue durable ``IngestionJob`` records.
This worker owns the potentially multi-hour subprocesses and updates the
same job ledger, so a web restart cannot terminate or duplicate a training
request.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from investment_research.repository.sqlite import SQLiteUnitOfWork, create_unit_of_work
from investment_research.service.ingestion_jobs import IngestionJobService
from investment_research.training.active_snapshot_guard import (
    ActiveSnapshotInputError,
    require_active_snapshot,
    require_training_snapshot_gate,
)
from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.snapshot_landing import SnapshotGateConfig


TRAINING_JOB_TYPES = {
    "research_monthly_training",
    "research_quarterly_challenger",
}


class ResearchTrainingWorker:
    """Claim and execute only the durable training jobs owned by this role."""

    def __init__(self, project: Path | None = None, *, clock=None) -> None:
        self.project = (project or Path(__file__).resolve().parents[3]).resolve()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def tick(self, *, limit: int = 1) -> dict[str, int]:
        # Keep scheduled jobs queued until the downloader handoff has produced
        # an active, hash-verified PIT snapshot.  This check happens before
        # opening/claiming jobs, so a launchd/APScheduler restart cannot start
        # the legacy demo trainer against mutable bundles while data is still
        # landing.  ``_run_job`` remains independently testable; production
        # entry is always through this guarded tick.
        if not self._training_gate_passes():
            return {"succeeded": 0, "degraded": 0, "failed": 0, "skipped": 0, "blocked": 1}
        uow = create_unit_of_work()
        now = self.clock()
        try:
            service = IngestionJobService(uow, clock=lambda: now)

            def run(job):
                return self._run_job(job, service)

            return service.drain(
                {
                    "research_monthly_training": run,
                    "research_quarterly_challenger": run,
                },
                limit=limit,
                allowed_job_types=TRAINING_JOB_TYPES,
            )
        finally:
            uow.close()

    def _training_gate_passes(self) -> bool:
        data_root = self.project / "var" / "cn-research"
        config_path = self.project / "config" / "long_term_training.yaml"
        try:
            active = require_active_snapshot(data_root)
            contract = load_long_term_training_config(config_path)
            require_training_snapshot_gate(
                active,
                config=SnapshotGateConfig(
                    required_datasets=set(contract.required_snapshot_datasets),
                    minimum_financial_coverage=contract.minimum_financial_coverage,
                ),
                labels_mature=True,
            )
        except (ActiveSnapshotInputError, OSError, ValueError):
            return False
        return True

    def _run_job(self, job, service: IngestionJobService):
        if job.job_type not in TRAINING_JOB_TYPES:  # pragma: no cover - protected by TRAINING_JOB_TYPES
            raise ValueError(f"unsupported training job: {job.job_type}")
        rebuild_index = self._latest_rebuild_index()
        if rebuild_index is None:
            raise RuntimeError(
                "long_term_training_rebuild_index_missing; run the PIT rebuild before training"
            )
        queue_root = self.project / "artifacts" / "long_term_training_queue" / (
            f"{job.job_type}-{getattr(job, 'trade_date', None) or self.clock():%Y%m%d}"
        )
        command = [
            sys.executable,
            str(self.project / "scripts/run_research_optimization_queue.py"),
            "--rebuild-index", str(rebuild_index),
            "--object-store", str(self.project / "var" / "cn-research" / "parquet"),
            "--data-root", str(self.project / "var" / "cn-research"),
            "--queue-root", str(queue_root),
            "--max-wait-hours", "0",
        ]
        completed = subprocess.run(
            command,
            cwd=self.project,
            text=True,
            capture_output=True,
            timeout=24 * 60 * 60,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-1000:]
            raise RuntimeError(f"{job.job_type} failed: {detail}")
        return service.complete(
            job,
            coverage_ratio=1.0,
            artifact_version=f"{job.job_type}:{self.clock():%Y%m%d}",
            latest_source_time=self.clock(),
        )

    def _latest_rebuild_index(self) -> Path | None:
        """Find the newest validated PIT rebuild index without touching landing.

        The lifecycle worker may run after the daily close rebuild has already
        produced a dated index.  Only indexes with the expected schema and a
        close-confirmed sample-manifest group are eligible; arbitrary JSON in
        the artifacts directory is never treated as a training input.
        """
        roots = (
            self.project / "artifacts" / "cn_research_pit",
            self.project / "artifacts" / "research_lifecycle",
        )
        candidates: list[tuple[float, Path]] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("rebuild-*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                context = payload.get("contexts", {}).get("close_confirmed", {})
                if (
                    payload.get("schema_version") == "cn-zero-budget-research-rebuild-v1"
                    and isinstance(context, dict)
                    and any(context.get("sample_manifests", {}).values())
                    and payload.get("deployment_ready") is False
                ):
                    try:
                        candidates.append((path.stat().st_mtime, path.resolve()))
                    except OSError:
                        continue
        return max(candidates, key=lambda item: (item[0], str(item[1])))[1] if candidates else None
