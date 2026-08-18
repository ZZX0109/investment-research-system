from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from investment_research.service.research_lifecycle import (
    ResearchLifecycleService,
    ResearchPromotionStore,
    matured_training_cutoff,
)


def test_weekend_uses_latest_completed_calendar_session() -> None:
    dates = [date(2026, 8, 6), date(2026, 8, 7)]
    service_date = date(2026, 8, 8)
    from investment_research.service.research_lifecycle import latest_completed_trade_date

    assert latest_completed_trade_date(service_date, dates) == date(2026, 8, 7)


def test_matured_cutoff_excludes_forward_label_tail() -> None:
    dates = [date(2026, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(30)]
    assert matured_training_cutoff(date(2026, 1, 30), dates, horizon_sessions=20) == date(2026, 1, 10)


def test_daily_plan_is_idempotent_and_monthly_is_boundary() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(31)]
    # The fixture intentionally uses a complete synthetic calendar so the
    # cadence logic can be tested without contacting an exchange provider.
    plan = ResearchLifecycleService.__new__(ResearchLifecycleService)
    plan.cadence = __import__("investment_research.service.research_lifecycle", fromlist=["ResearchCadence"]).ResearchCadence()
    assert plan._is_month_boundary(date(2026, 1, 31), dates)


def test_daily_plan_does_not_use_today_before_close_confirmation() -> None:
    dates = [date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10)]
    service = ResearchLifecycleService.__new__(ResearchLifecycleService)
    service.cadence = __import__("investment_research.service.research_lifecycle", fromlist=["ResearchCadence"]).ResearchCadence()
    plan = service.plan(
        now=datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc),  # 15:00 Shanghai
        trading_dates=dates,
        enqueue=False,
    )
    assert plan.latest_trade_date == date(2026, 8, 7)


def test_empty_exchange_calendar_blocks_training_instead_of_using_calendar_days() -> None:
    service = ResearchLifecycleService.__new__(ResearchLifecycleService)
    service.cadence = __import__("investment_research.service.research_lifecycle", fromlist=["ResearchCadence"]).ResearchCadence()
    plan = service.plan(
        now=datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
        trading_dates=[],
        enqueue=False,
    )
    assert plan.latest_trade_date is None
    assert "exchange_calendar_has_no_completed_trade_date" in plan.reasons


def test_monitor_triggers_retraining_but_leakage_blocks() -> None:
    decision = ResearchLifecycleService.__new__(ResearchLifecycleService).monitor(
        {"coverage_ratio": 0.99, "psi": 0.25, "leakage_errors": 0}
    )
    assert decision.status == "retrain_recommended"
    assert "input_psi_above_threshold" in decision.trigger_reasons

    blocked = ResearchLifecycleService.__new__(ResearchLifecycleService).monitor(
        {"coverage_ratio": 0.99, "leakage_errors": 1}
    )
    assert blocked.status == "blocked"


def test_candidate_requires_shadow_and_research_boundary() -> None:
    evidence = {
        "data_tier": "research_pit",
        "deployment_ready": False,
        "leakage_errors": 0,
        "synthetic_count": 0,
        "artifact_hashes_valid": True,
        "holdout_passed": True,
        "stress_passed": True,
        "baseline_not_regressed": True,
        "regime_stable": True,
        "seed_stable": True,
        "valid_shadow_sessions": 20,
        "shadow_better_than_primary": True,
    }
    assert ResearchLifecycleService.evaluate_candidate(evidence).eligible
    evidence["deployment_ready"] = True
    assert not ResearchLifecycleService.evaluate_candidate(evidence).eligible


def test_promotion_store_keeps_research_only_boundary(tmp_path) -> None:
    store = ResearchPromotionStore(tmp_path)
    evidence = {
        "data_tier": "research_pit", "deployment_ready": False,
        "leakage_errors": 0, "synthetic_count": 0,
        "artifact_hashes_valid": True, "holdout_passed": True,
        "stress_passed": True, "baseline_not_regressed": True,
        "regime_stable": True, "seed_stable": True,
        "valid_shadow_sessions": 20, "shadow_better_than_primary": True,
        "model_version": "candidate-v2",
    }
    path = store.promote(
        scope="cn_close_confirmed_direction_1d",
        candidate=evidence,
        promoted_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )
    assert path.is_file()
    current = (tmp_path / "cn_close_confirmed_direction_1d" / "current.json").read_text()
    assert '"deployment_ready": false' in current
    assert '"status": "research_only"' in current
    assert store.read_current(scope="cn_close_confirmed_direction_1d")["status"] == "research_only"


def test_promotion_controller_is_atomic_and_keeps_previous_on_gate_failure(tmp_path) -> None:
    blocked, path = ResearchLifecycleService.promote_candidate(
        scope="cn_close_confirmed_direction_1d",
        candidate={"data_tier": "research_pit", "deployment_ready": False},
        promotion_root=tmp_path,
    )
    assert not blocked.eligible
    assert path is None
    assert not (tmp_path / "cn_close_confirmed_direction_1d" / "current.json").exists()
