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
    sample_manifest = tmp_path / "sample-manifests.json"
    sample_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("investment_research.workers.training.require_active_snapshot", lambda _root: SimpleNamespace())
    monkeypatch.setattr(worker, "_latest_bound_sample_manifest", lambda _active: sample_manifest)
    job = SimpleNamespace(job_type="research_monthly_training")
    completed = []

    class Service:
        def complete(self, item, **kwargs):
            completed.append((item, kwargs))
            return SimpleNamespace(state="succeeded")

    result = worker._run_job(job, Service())
    assert result.state == "succeeded"
    assert captured["command"][0]
    assert "run_long_term_automation.py" in captured["command"][1]
    assert "--mode" in captured["command"]
    assert "formal" in captured["command"]
    assert "--samples" in captured["command"]
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


def test_training_worker_blocks_without_active_bound_sample_manifest(monkeypatch, tmp_path: Path) -> None:
    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("formal orchestrator must not start without a bound sample list")

    monkeypatch.setattr("investment_research.workers.training.subprocess.run", fail_if_started)
    monkeypatch.setattr("investment_research.workers.training.require_active_snapshot", lambda _root: SimpleNamespace())
    worker = ResearchTrainingWorker(tmp_path)
    monkeypatch.setattr(worker, "_latest_rebuild_index", lambda: tmp_path / "rebuild.json")
    job = SimpleNamespace(job_type="research_monthly_training")

    class Service:
        def complete(self, *_args, **_kwargs):  # pragma: no cover - should not be reached
            raise AssertionError("job completed despite missing bound sample list")

    try:
        worker._run_job(job, Service())
    except RuntimeError as exc:
        assert "bound_sample_manifest_missing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("worker accepted an unbound sample list")


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


def test_market_refresh_drain_does_not_claim_research_collection_jobs(tmp_path: Path) -> None:
    """Regression: the market-refresh pass owns only its own job type."""
    uow = SQLiteUnitOfWork(tmp_path / "jobs.db")
    now = datetime(2026, 8, 17, tzinfo=timezone.utc)
    service = IngestionJobService(uow, clock=lambda: now)
    service.enqueue(
        job_type="research_daily_close", symbols=[], requested_by="test",
        idempotency_key="research-collection-1",
    )
    service.drain(
        {"daily_close_confirmation": lambda job: service.complete(job)},
        allowed_job_types={"daily_close_confirmation"},
    )
    stored = uow.ingestion_jobs.list_recent(limit=10)
    assert stored[0].state == "queued"
    uow.close()


def test_recover_interrupted_research_job_leaves_training_job_running(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "jobs.db")
    service = IngestionJobService(uow)
    research = service.enqueue(job_type="research_daily_close", symbols=[], requested_by="test")
    training = service.enqueue(job_type="research_monthly_training", symbols=[], requested_by="test")
    service.mark_running(research)
    service.mark_running(training)
    assert service.recover_interrupted_running(job_types={"research_daily_close"}) == 1
    assert uow.ingestion_jobs.get(str(research.id)).state == "retrying"
    assert uow.ingestion_jobs.get(str(training.id)).state == "running"
    uow.close()


def test_daily_collection_uses_current_universe_not_legacy_demo_pool(tmp_path: Path) -> None:
    command = LocalResearchScheduler._daily_collection_command(tmp_path)
    assert str(tmp_path / "artifacts/cn_security_master_universe/security_master_current.json") in command
    assert str(tmp_path / "config/cn_research_target_167_symbols.json") not in command
    assert "--rebuild-include-all-raw-symbols" in command
    assert "--rebuild-skip-samples" in command
