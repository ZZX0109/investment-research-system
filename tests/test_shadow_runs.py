from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.shadow_runs import ShadowRunController
from investment_research.training.formal_release import finalize_task_manifest
from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.training.approval_reports import REQUIRED_SCOPE_REPORTS


def _freeze(
    controller, *, day: int, coverage: float = 0.99, synthetic: int = 0,
    artifact_hashes: dict[str, str] | None = None,
    expected_artifact_hashes: dict[str, str] | None = None,
):
    trade_date = date(2026, 7, 1) + timedelta(days=day - 1)
    return controller.freeze(
        training_run_id="run-1",
        market="cn",
        decision_context="close_confirmed",
        task="drawdown_20d",
        trade_date=trade_date,
        frozen_at=datetime.combine(trade_date, datetime.min.time(), timezone.utc),
        market_snapshot_id=uuid4(),
        market_snapshot_hash=sha256(f"snapshot-{day}".encode()).hexdigest(),
        artifact_hashes=artifact_hashes or {"model.pkl": sha256(b"model").hexdigest()},
        expected_artifact_hashes=(
            expected_artifact_hashes
            if expected_artifact_hashes is not None
            else (artifact_hashes or {"model.pkl": sha256(b"model").hexdigest()})
        ),
        coverage_ratio=coverage,
        formal_synthetic_output_count=synthetic,
    )


def test_shadow_sessions_are_immutable_and_gate_release_on_20_valid_days(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "shadow.db")
    controller = ShadowRunController(uow.shadow_runs, required_sessions=20)
    invalid = _freeze(controller, day=1, coverage=0.97)
    assert not invalid.valid
    assert "critical_data_coverage_below_98pct" in invalid.invalid_reasons
    for day in range(2, 22):
        _freeze(controller, day=day)
    scope = dict(
        training_run_id="run-1", market="cn", decision_context="close_confirmed", task="drawdown_20d"
    )
    assert controller.valid_session_count(**scope) == 20
    assert controller.release_ready(**scope)
    manifest = TaskApprovalManifest(
        task="drawdown_20d", decision_context="close_confirmed", status="approved",
        model_name="baseline", model_version="v1", baseline_name="baseline",
        label_policy_version="four-market-tradeable-label-v1", market="cn",
        applicable_markets=["cn"], training_run_id="run-1",
        dataset_manifest_hash="a" * 64, leakage_report_hash="b" * 64,
        holdout_12m_report_hash="c" * 64, stress_6m_report_hash="d" * 64,
        ablation_report_hash="e" * 64, data_snapshot_hash="f" * 64,
        dependency_lock_hash="g" * 64, artifact_hashes={"model.pkl": "h" * 64},
        approval_evidence_hashes={name: "i" * 64 for name in REQUIRED_SCOPE_REPORTS},
        critical_data_coverage=0.99, holdout_12m_passed=True, stress_6m_passed=True,
        market_regime_sample_gate_passed=True, cost_gate_passed=True,
    )
    finalized = finalize_task_manifest(manifest, shadow_controller=controller)
    assert finalized.deployment_ready
    assert finalized.shadow_run_sessions == 20
    with pytest.raises(ValueError, match="immutable"):
        _freeze(controller, day=2, synthetic=1)
    uow.close()


def test_shadow_outcome_backfill_is_separate_and_immutable(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "shadow-outcome.db")
    controller = ShadowRunController(uow.shadow_runs, outcomes_repository=uow.shadow_outcomes)
    session = _freeze(controller, day=1)
    outcome = controller.backfill_outcome(
        shadow_session_id=session.id, horizon_sessions=5,
        filled_at=datetime(2026, 7, 8, tzinfo=timezone.utc), realized_return=0.03,
        realized_max_drawdown=-0.02, mae=-0.02, mfe=0.04, direction="up", data_complete=True,
    )
    assert outcome.shadow_session_id == session.id
    assert uow.shadow_runs.get_scope_day(
        training_run_id="run-1", market="cn", decision_context="close_confirmed",
        task="drawdown_20d", trade_date=session.trade_date.isoformat(),
    ).id == session.id
    with pytest.raises(ValueError, match="immutable"):
        controller.backfill_outcome(
            shadow_session_id=session.id, horizon_sessions=5,
            filled_at=datetime(2026, 7, 8, tzinfo=timezone.utc), realized_return=-0.3,
            realized_max_drawdown=-0.3, mae=-0.3, mfe=0.0, direction="down", data_complete=True,
        )
    with pytest.raises(ValueError):
        controller.backfill_outcome(
            shadow_session_id=session.id, horizon_sessions=2,
            filled_at=datetime(2026, 7, 8, tzinfo=timezone.utc), realized_return=None,
            realized_max_drawdown=None, mae=None, mfe=None,
        )
    uow.close()


def test_shadow_hash_mismatch_never_counts_as_valid_session(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "shadow-hash.db")
    controller = ShadowRunController(uow.shadow_runs)
    session = _freeze(
        controller, day=1,
        artifact_hashes={"model.pkl": sha256(b"executed-model").hexdigest()},
        expected_artifact_hashes={"model.pkl": sha256(b"approved-model").hexdigest()},
    )
    assert not session.valid
    assert "artifact_hash_mismatch" in session.invalid_reasons
    assert controller.valid_session_count(
        training_run_id="run-1", market="cn", decision_context="close_confirmed",
        task="drawdown_20d",
    ) == 0
    uow.close()
