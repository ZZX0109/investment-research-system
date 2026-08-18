from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from investment_research.workers.training import ResearchTrainingWorker
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.ingestion_jobs import IngestionJobService
from investment_research.service.scheduling import LocalResearchScheduler


def test_training_worker_runs_training_outside_scheduler(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("investment_research.workers.training.subprocess.run", fake_run)
    worker = ResearchTrainingWorker(tmp_path, clock=lambda: datetime(2026, 8, 17, tzinfo=timezone.utc))
    rebuild_index = tmp_path / "rebuild-20260817.json"
    rebuild_index.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(worker, "_latest_rebuild_index", lambda: rebuild_index)
    job = SimpleNamespace(job_type="research_monthly_training")
    completed = []

    class Service:
        def complete(self, item, **kwargs):
            completed.append((item, kwargs))
            return SimpleNamespace(state="succeeded")

    result = worker._run_job(job, Service())
    assert result.state == "succeeded"
    assert captured["command"][0]
    assert "run_research_optimization_queue.py" in captured["command"][1]
    assert "--rebuild-index" in captured["command"]
    assert captured["kwargs"]["timeout"] == 24 * 60 * 60
    assert completed[0][1]["artifact_version"].startswith("research_monthly_training:")


def test_training_worker_keeps_jobs_blocked_without_active_snapshot(monkeypatch, tmp_path: Path) -> None:
    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("training subprocess must not start before the active snapshot gate")

    monkeypatch.setattr("investment_research.workers.training.subprocess.run", fail_if_started)
    worker = ResearchTrainingWorker(tmp_path)
    result = worker.tick()
    assert result["blocked"] == 1
    assert result["succeeded"] == 0


def test_scheduler_leaves_long_training_job_for_training_worker(monkeypatch, tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "jobs.db")
    now = datetime(2026, 8, 17, tzinfo=timezone.utc)
    IngestionJobService(uow, clock=lambda: now).enqueue(
        job_type="research_monthly_training",
        symbols=[],
        requested_by="test",
        idempotency_key="training-job-1",
    )
    monkeypatch.setattr("investment_research.service.scheduling.create_unit_of_work", lambda: uow)
    LocalResearchScheduler()._drain_research_jobs(uow, now)
    stored = uow.ingestion_jobs.list_recent(limit=10)
    assert stored[0].job_type == "research_monthly_training"
    assert stored[0].state == "queued"
    uow.close()
