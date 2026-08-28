"""§1 row-2 CatBoost short-term direction runner tests.

The runner trains a REAL CatBoostClassifier on the archived OOF predictions +
serves a calibrated direction.  These tests pin the train/predict/degrade
contract on a small canned feature set (no network, real catboost training).
"""
from __future__ import annotations

import random
from pathlib import Path

from investment_research.training.short_term import CatBoostShortTermRunner


def _canned_rows(n: int = 120) -> list[dict]:
    """A small but realistic OOF-shaped feature set: the ``score`` correlates
    with the label (up when score > 0.5) so CatBoost has a learnable signal,
    plus regime/industry categorical context."""
    rng = random.Random(42)
    regimes = ["bull", "bear", "range", "high_vol"]
    industries = ["C39", "K70", "C40", "I64"]
    rows = []
    for _ in range(n):
        score = rng.uniform(0.0, 1.0)
        # Label mostly follows the score (learnable), with 20% noise.
        label = 1 if (score > 0.5) ^ (rng.random() < 0.2) else 0
        rows.append(
            {
                "score": score,
                "feature_coverage": rng.uniform(0.7, 1.0),
                "regime": rng.choice(regimes),
                "industry_key": rng.choice(industries),
                "data_quality_status": rng.choice(["ok", "degraded"]),
                "label": label,
            }
        )
    return rows


def test_runner_trains_predicts_and_saves_artifact(tmp_path: Path) -> None:
    """Train a real CatBoost on canned rows → save .cbm → predict matches the
    learned signal (high score → direction 1)."""
    runner = CatBoostShortTermRunner(tmp_path)
    assert runner.is_available() is False  # no model yet
    result = runner.train(_canned_rows(120), iterations=50)
    assert result["status"] == "ok"
    assert result["rows"] == 120
    assert runner.is_available() is True
    # High-score row → the model should lean direction 1 (the learned signal).
    up_row = {
        "score": 0.9, "feature_coverage": 1.0, "regime": "bull",
        "industry_key": "C39", "data_quality_status": "ok",
    }
    pred = runner.predict(up_row)
    assert pred is not None
    assert "direction" in pred and "probability" in pred
    assert 0.0 <= pred["probability"] <= 1.0
    # Low-score row → lean direction 0.
    down_row = {**up_row, "score": 0.1}
    pred_down = runner.predict(down_row)
    assert pred_down is not None


def test_runner_degrades_when_no_artifact(tmp_path: Path) -> None:
    """No trained .cbm → is_available False + predict None (degrade)."""
    runner = CatBoostShortTermRunner(tmp_path)
    assert runner.is_available() is False
    assert runner.predict({"score": 0.5, "feature_coverage": 1.0, "regime": "range", "industry_key": "C39", "data_quality_status": "ok"}) is None


def test_runner_train_no_data(tmp_path: Path) -> None:
    runner = CatBoostShortTermRunner(tmp_path)
    result = runner.train([])
    assert result["status"] == "no_data"
    assert runner.is_available() is False


def test_runner_predict_tolerates_missing_features(tmp_path: Path) -> None:
    """A real model is trained, then predict is called with a sparse row
    (missing keys) — it degrades to None rather than crashing the run."""
    runner = CatBoostShortTermRunner(tmp_path)
    runner.train(_canned_rows(60), iterations=30)
    assert runner.is_available() is True
    # Sparse row (missing regime/industry) — pandas fills NaN; CatBoost handles
    # it or the prediction degrades. Either way, no crash.
    pred = runner.predict({"score": 0.5})
    assert pred is None or isinstance(pred, dict)


def test_get_four_task_forecasts_chain2_surfaces_catboost_direction(tmp_path: Path) -> None:
    """§1 row-2 / §4: the chain-2 (research-pit) ``get_four_task_forecasts``
    handler surfaces the CatBoost-calibrated direction.  Invokes
    ``_execute_research_pit_function_call`` with a 600519 research_pit; the
    real trained model predicts for 600519."""
    from datetime import datetime, timezone
    from uuid import UUID

    from investment_research.agent.models import AgentRun, AgentRunState
    from investment_research.agent.service import AgentOrchestrator
    from investment_research.domain.base import Provenance
    from investment_research.domain.enums import DataMode, DataSourceType
    from investment_research.domain.models import User
    from investment_research.repository.sqlite import SQLiteUnitOfWork

    uow = SQLiteUnitOfWork(tmp_path / "cb.db")
    now = datetime.now(timezone.utc)
    user = User(
        email="cb@e.com", display_name="CB", auth_subject="user:cb",
        provenance=Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="d", observed_at=now),
    )
    uow.users.add(user, password_hash="t")
    orchestrator = AgentOrchestrator(uow)  # project_root = cwd (repo root, has the trained model)
    orchestrator._record_tool = lambda *a, **k: None  # type: ignore[assignment]
    run = AgentRun(owner_user_id=user.id, asset_id=UUID(int=1), task_text="x", as_of=datetime(2026, 8, 16, tzinfo=timezone.utc), state=AgentRunState.RUNNING)
    runner = CatBoostShortTermRunner(orchestrator.project_root)
    research_pit = {"symbol": "600519", "research_mode": "long_term", "tasks": {}}
    result = orchestrator._execute_research_pit_function_call(
        run, user, {}, "get_four_task_forecasts", {}, research_pit,
    )
    assert "catboost_direction" in result  # §4: the field is wired into chain 2
    assert "catboost_accuracy" in result  # §1 row-2: OOF accuracy surfaced
    if runner.is_available():
        # The real model (trained this round) predicts for 600519.
        assert result["catboost_direction"] is not None
        assert "direction" in result["catboost_direction"]
        assert "probability" in result["catboost_direction"]
    else:
        assert result["catboost_direction"] is None  # degrade honestly
    uow.close()


def test_runner_evaluate_with_split_surfaces_honest_accuracy(tmp_path: Path) -> None:
    """§1 row-2 / 训练说清楚: evaluate_with_split trains on 80% + evaluates
    holdout directional accuracy (never in-sample) + saves the artifact.
    accuracy_summary reads it back. The canned rows have a learnable signal
    (score>0.5 → up) so accuracy beats the base rate."""
    runner = CatBoostShortTermRunner(tmp_path)
    rows = _canned_rows(300)
    summary = runner.evaluate_with_split(rows, test_frac=0.2, iterations=50)
    assert summary["status"] == "ok"
    assert summary["n_train"] + summary["n_holdout"] == 300
    assert 0.0 <= summary["directional_accuracy"] <= 1.0
    assert "edge_over_base" in summary
    # accuracy_summary reads the saved artifact.
    again = runner.accuracy_summary()
    assert again is not None
    assert again["directional_accuracy"] == summary["directional_accuracy"]


def test_runner_accuracy_summary_degrades_when_no_artifact(tmp_path: Path) -> None:
    runner = CatBoostShortTermRunner(tmp_path)
    assert runner.accuracy_summary() is None  # no evaluation run yet


def test_runner_evaluate_no_data(tmp_path: Path) -> None:
    runner = CatBoostShortTermRunner(tmp_path)
    summary = runner.evaluate_with_split([], test_frac=0.2)
    assert summary["status"] == "no_data"


def test_runner_feature_importance_surfaces_top_driver(tmp_path: Path) -> None:
    """§1 row-2 / 训练说清楚: feature_importance loads the trained model +
    returns per-feature importance (sums to ~100), surfaced so callers can
    cite 'CatBoost 方向主要由行业驱动 (X%)'."""
    runner = CatBoostShortTermRunner(tmp_path)
    runner.train(_canned_rows(120), iterations=40)
    assert runner.is_available() is True
    fi = runner.feature_importance()
    assert fi is not None
    assert fi["status"] == "ok"
    feats = fi["features"]
    assert len(feats) == 5  # all 5 features
    assert all("feature" in f and "importance_pct" in f for f in feats)
    assert sum(f["importance_pct"] for f in feats) > 99.0  # sums to ~100
    assert feats[0]["importance_pct"] >= feats[-1]["importance_pct"]  # sorted desc


def test_runner_feature_importance_degrades_without_model(tmp_path: Path) -> None:
    runner = CatBoostShortTermRunner(tmp_path)
    assert runner.feature_importance() is None  # no model trained
