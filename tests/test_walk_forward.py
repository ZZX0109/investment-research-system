"""§1 step 7 / §3 walk-forward summary regression tests.

``summarize_walk_forward`` turns the archived predicted-vs-actual readings
(``ModelHistoryPoint``) into a per-asset daily accuracy + error view — the
per-asset complement to the global accuracy_surface.  These tests pin the
computation + the empty-degradation so the LLM/dashboard see honest numbers.
"""
from __future__ import annotations

from types import SimpleNamespace

from investment_research.agent.evaluation import summarize_walk_forward


def _pt(date: str, predicted: float, actual: float) -> SimpleNamespace:
    return SimpleNamespace(decision_date=date, predicted_return=predicted, actual_return=actual)


def test_summarize_walk_forward_directional_accuracy() -> None:
    # 3 of 4 directional calls correct; errors as computed below.
    history = [
        _pt("2024-03-31", 0.10, 0.20),   # both + → correct; |err|=0.10
        _pt("2024-06-30", -0.05, 0.15),  # pred - / act + → wrong; |err|=0.20
        _pt("2024-09-30", 0.08, 0.01),   # both + → correct; |err|=0.07
        _pt("2024-12-31", -0.12, -0.04), # both - → correct; |err|=0.08
    ]
    summary = summarize_walk_forward(history)
    assert summary["status"] == "ok"
    assert summary["decision_count"] == 4
    assert summary["directional_accuracy"] == 0.75  # 3/4
    assert abs(summary["mean_abs_error"] - (0.10 + 0.20 + 0.07 + 0.08) / 4) < 1e-9
    # signed error: (0.10-0.20) + (-0.05-0.15) + (0.08-0.01) + (-0.12+0.04)
    expected_signed = (-0.10 + -0.20 + 0.07 + -0.08) / 4
    assert abs(summary["mean_signed_error"] - expected_signed) < 1e-9
    assert len(summary["dates"]) == 4
    assert summary["dates"][0] == {
        "date": "2024-03-31", "predicted": 0.10, "actual": 0.20,
        "correct": True, "abs_error": 0.10,
    }


def test_summarize_walk_forward_degrades_when_empty() -> None:
    summary = summarize_walk_forward([])
    assert summary["status"] == "unavailable"
    assert summary["reason"] == "no_model_history"
    assert summary["decision_count"] == 0
    assert summary["directional_accuracy"] is None
    assert summary["dates"] == []


def test_summarize_walk_forward_tolerates_malformed_points() -> None:
    # None entries + missing decision_date are skipped, never crash.
    history = [_pt("2024-03-31", 0.1, 0.2), None, SimpleNamespace(decision_date=None)]
    summary = summarize_walk_forward(history)
    assert summary["status"] == "ok"
    assert summary["decision_count"] == 1


def test_load_model_prediction_history_reads_parquet_and_groups_by_date(tmp_path) -> None:
    """§3 row-5 shared loader: reads the archived OOF/holdout parquet, filters
    to this symbol, + groups candidate rows by decision date (mean predicted
    vs actual) — the data path get_model_validation_metrics now surfaces."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    art_root = tmp_path / "artifacts" / "long_term_training"
    art_root.mkdir(parents=True)
    # Two OOF rows for 600519 on the same date (grouped → mean) + one row for a
    # different symbol (filtered out) + one non-OOF row (filtered out).
    table = pa.table(
        {
            "split": ["oof", "oof", "oof", "train"],
            "symbol": ["600519", "600519", "000001", "600519"],
            "decision_date": ["2024-03-31", "2024-03-31", "2024-03-31", "2024-03-31"],
            "target": [0.20, 0.24, 0.50, 0.20],
            "score": [0.10, 0.14, 0.30, 0.10],
        }
    )
    pq.write_table(table, art_root / "latest.predictions.parquet")

    from investment_research.agent.evaluation import load_model_prediction_history

    history = load_model_prediction_history(tmp_path, "600519")
    # One grouped date; mean predicted=(0.10+0.14)/2=0.12, mean actual=(0.20+0.24)/2=0.22.
    assert len(history) == 1
    point = history[0]
    assert point.decision_date == "2024-03-31"
    assert abs(point.predicted_return - 0.12) < 1e-9
    assert abs(point.actual_return - 0.22) < 1e-9
    # summarize → daily accuracy (1 date, predicted+ actual+ → correct).
    from investment_research.agent.evaluation import summarize_walk_forward

    summary = summarize_walk_forward(history)
    assert summary["status"] == "ok"
    assert summary["decision_count"] == 1
    assert summary["directional_accuracy"] == 1.0


def test_load_model_prediction_history_degrades_when_artifact_missing(tmp_path) -> None:
    """No parquet → [] (never synthesizes), so the tool surfaces
    walk_forward_daily status='unavailable' honestly."""
    from investment_research.agent.evaluation import (
        load_model_prediction_history,
        summarize_walk_forward,
    )

    history = load_model_prediction_history(tmp_path, "600519")
    assert history == []
    assert summarize_walk_forward(history)["status"] == "unavailable"


def test_directional_accuracy_by_regime_surfaces_where_model_works() -> None:
    """§3 / 训练说清楚 WHERE for the long-term model: the
    get_model_validation_metrics handler surfaces directional_accuracy_by_regime
    (a NEW metric distinct from accuracy_surface rank_ic) — bull 64% vs range
    55% shows WHERE the long-term model works."""
    from pathlib import Path
    from investment_research.agent.service import AgentOrchestrator
    from investment_research.repository.sqlite import SQLiteUnitOfWork
    import tempfile

    repo_root = Path(__file__).resolve().parent.parent
    parquet = repo_root / "artifacts" / "long_term_training" / "latest.predictions.parquet"
    uow = SQLiteUnitOfWork(Path(tempfile.mkdtemp()) / "dar.db")
    try:
        orch = AgentOrchestrator(uow, project_root=repo_root)
        res = orch._directional_accuracy_by_regime()
        if not parquet.exists():
            assert res["status"] == "unavailable"  # degrade honestly
            return
        assert res["status"] == "ok"
        assert "directional_accuracy" in res and isinstance(res["n"], int)
        assert 0.0 <= res["directional_accuracy"] <= 1.0
        by = res.get("by_regime", {})
        assert isinstance(by, dict) and by  # has regime breakdowns
        # The metric is clearly labeled as distinct from rank_ic (no conflict).
        assert "rank_ic" in str(res.get("metric", "")).lower() or "distinct" in str(res.get("metric", "")).lower()
        for reg, m in by.items():
            assert "n" in m and "directional_accuracy" in m
            assert 0.0 <= m["directional_accuracy"] <= 1.0
    finally:
        uow.close()
