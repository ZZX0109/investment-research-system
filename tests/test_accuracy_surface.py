"""§3/§1-step-7 accuracy-surface regression tests.

``get_model_validation_metrics`` now carries an ``accuracy_surface`` field built
from ``artifacts/model_performance/accuracy_surface.json`` (frozen holdout/stress
rank_ic from the trained long-term model).  This closes the 'training accuracy
hidden' gap so the LLM (and the user via the answer) sees the actual rank_ic.
These tests pin the read + the graceful degradation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from investment_research.agent.service import AgentOrchestrator
from investment_research.repository.sqlite import SQLiteUnitOfWork


def _orch(tmp_path: Path) -> AgentOrchestrator:
    uow = SQLiteUnitOfWork(tmp_path / "acc.db")
    orchestrator = AgentOrchestrator(uow)
    orchestrator._record_tool = lambda *a, **k: None  # type: ignore[assignment]
    return orchestrator, uow


def test_accuracy_surface_summary_surfaces_rank_ic(tmp_path: Path) -> None:
    orchestrator, uow = _orch(tmp_path)
    try:
        summary = orchestrator._accuracy_surface_summary()
        assert summary["status"] == "ok"
        tasks = summary["tasks"]
        # Return task: directional rank_ic (higher = better, gate > 0.10).
        ret = tasks["excess_return_240d"]
        assert ret["metric_type"] == "rank_ic"
        assert isinstance(ret["best_holdout_rank_ic"], float)
        assert ret["best_holdout_rank_ic"] > 0.10  # passes the promotion gate
        assert ret["best_variant"] == "stability-end-180"
        assert ret["variant_count"] >= 10
        assert ret["passing_gt_0_10"] >= 8
        # Drawdown task: quantile metrics (p50_mae / interval_coverage), NOT rank_ic.
        dd = tasks["future_max_drawdown_240d"]
        assert dd["metric_type"] == "p50_mae"
        assert isinstance(dd["best_holdout_p50_mae"], float)
        assert dd["best_holdout_p50_mae"] < 0.20  # sane median abs error
        assert isinstance(dd["best_holdout_interval_coverage"], float)
        assert dd["best_variant"] == "risk-master-h256"
    finally:
        uow.close()


def test_accuracy_surface_summary_degrades_when_artifact_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator, uow = _orch(tmp_path)
    # Force the artifact path to resolve to a non-existent file.
    monkeypatch.setattr(
        orchestrator, "_safe_project_path",
        lambda ref: Path("/nonexistent/model_performance/accuracy_surface.json"),
    )
    try:
        summary = orchestrator._accuracy_surface_summary()
        assert summary["status"] == "unavailable"
        assert summary["reason"] == "accuracy_surface_missing"
    finally:
        uow.close()
