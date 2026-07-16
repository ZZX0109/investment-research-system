from datetime import date, datetime, timedelta, timezone
from hashlib import sha256

import pytest

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.domain.pit import EventCoverageStatus
from investment_research.api.routes import research_acceptance
from investment_research.service.free_research_ledger import build_coverage_ledgers
from investment_research.service.research_shadow import (
    FileResearchShadowStore,
    ResearchShadowController,
    ResearchShadowOutcome,
    ResearchShadowSession,
)


def test_free_coverage_ledger_does_not_turn_unavailable_events_into_zero() -> None:
    ledgers = build_coverage_ledgers(
        records=[
            {"market": "us", "dataset": "daily_bars", "symbol": "AAPL", "provider": "yfinance", "status": "backfilled"},
            {"market": "us", "dataset": "daily_bars", "symbol": "MSFT", "provider": "yfinance", "status": "fetch_failed"},
            {"market": "us", "dataset": "events", "provider": "sec_edgar", "status": "fetch_failed"},
        ],
        targets={"us": {"AAPL", "MSFT"}},
        generated_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    us = next(item for item in ledgers if item.market == "us")
    assert us.data_tier == DataTier.RESEARCH_PIT
    assert us.coverage_ratio == 0.5
    assert us.unavailable_symbols == ["MSFT"]
    assert us.event_coverage_status == EventCoverageStatus.FETCH_FAILED
    assert "event_coverage:fetch_failed" in us.reasons


def test_research_acceptance_missing_report_is_explicitly_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    payload = research_acceptance(None)
    assert payload["status"] == "blocked"
    assert payload["data_tier"] == "research_pit"
    assert payload["deployment_ready"] is False
    assert payload["blocking_reasons"] == ["acceptance_report_missing"]


def test_public_event_success_plus_incomplete_source_is_partial_not_zero() -> None:
    ledgers = build_coverage_ledgers(
        records=[
            {"market": "cn", "dataset": "daily_bars", "symbol": "600000", "provider": "akshare", "status": "backfilled"},
            {
                "market": "cn", "dataset": "events", "provider": "akshare_cninfo_notices",
                "status": "backfilled", "event_coverage_status": "events_present",
            },
            {"market": "cn", "dataset": "events", "provider": "exchange_archive", "status": "unsupported"},
        ],
        targets={"cn": {"600000"}}, generated_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    cn = next(item for item in ledgers if item.market == "cn")
    assert cn.event_coverage_status == EventCoverageStatus.PARTIAL
    assert "event_coverage:partial" in cn.reasons


def test_research_shadow_is_immutable_and_backfills_all_required_horizons(tmp_path) -> None:
    store = FileResearchShadowStore(tmp_path)
    session = ResearchShadowSession(
        market="cn", decision_context="close_confirmed", trade_date=date(2026, 7, 14),
        frozen_at=datetime(2026, 7, 14, 7, 10, tzinfo=timezone.utc),
        market_snapshot_id="research-cn-close-20260714",
        market_snapshot_hash=sha256(b"snapshot").hexdigest(), coverage_ratio=0.8,
        event_coverage_status=EventCoverageStatus.PARTIAL,
        abstained=True, abstain_reasons=["research_model_not_configured"],
    )
    assert store.freeze(session) == session
    with pytest.raises(ValueError, match="immutable"):
        store.freeze(session.model_copy(update={"coverage_ratio": 0.9}))
    for horizon in (1, 5, 20, 60):
        outcome = ResearchShadowOutcome(
            research_shadow_session_id=session.id, horizon_sessions=horizon,
            filled_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
            realized_return=0.01, realized_max_drawdown=-0.02, mae=-0.02,
            mfe=0.03, direction="up", data_complete=True,
            error_category="correct_abstain",
        )
        assert store.backfill(outcome) == outcome


def test_research_tier_manifest_is_never_approvable() -> None:
    kwargs = dict(
        task="drawdown_20d", decision_context="close_confirmed", model_name="free-rf",
        model_version="v1", baseline_name="historical", label_policy_version="labels-v1",
        market="us", applicable_markets=["us"], training_run_id="free-run-1",
        dataset_manifest_hash="a" * 64, leakage_report_hash="b" * 64,
        holdout_12m_report_hash="c" * 64, stress_6m_report_hash="d" * 64,
        ablation_report_hash="e" * 64, data_tier=DataTier.RESEARCH_PIT,
    )
    research = TaskApprovalManifest(**kwargs)
    assert research.status == "research_only"
    assert not research.deployment_ready
    with pytest.raises(ValueError, match="non-formal"):
        TaskApprovalManifest(**kwargs, status="approved")
    assert RESEARCH_VISIBILITY_ASSUMPTION == "historical_available_at_unproven_public_backfill"


def test_research_shadow_controller_freezes_prediction_and_abstains_on_disagreement(tmp_path) -> None:
    controller = ResearchShadowController(FileResearchShadowStore(tmp_path))
    session = controller.freeze_prediction(
        market="cn", decision_context="close_confirmed", cohort="cn_equity_core",
        task="direction_5d", symbol="600519", trade_date=date(2026, 7, 14),
        frozen_at=datetime(2026, 7, 14, 7, 10, tzinfo=timezone.utc),
        market_snapshot_id="snapshot-1", market_snapshot_hash="a" * 64,
        prediction={"up": 0.5, "down": 0.3, "flat": 0.2}, prediction_price=1500,
        model_artifact_hashes={"model": "b" * 64}, coverage_ratio=0.96,
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        provider_chain=["akshare", "baostock"], model_disagreement=0.31,
    )
    assert session.abstained
    assert "model_disagreement" in session.abstain_reasons
    assert session.evidence_valid


def test_research_shadow_forward_reports_require_20_and_60_valid_dates(tmp_path) -> None:
    store = FileResearchShadowStore(tmp_path)
    controller = ResearchShadowController(store)
    day = date(2026, 1, 5)
    created = 0
    while created < 60:
        if day.weekday() < 5:
            controller.freeze_prediction(
                market="cn", decision_context="close_confirmed", cohort="cn_equity_core",
                task="direction_1d", symbol="600519", trade_date=day,
                frozen_at=datetime.combine(day, datetime.min.time(), timezone.utc),
                market_snapshot_id=f"snapshot-{created}", market_snapshot_hash=sha256(str(created).encode()).hexdigest(),
                prediction={"calibrated_probability": {"up": 0.5, "down": 0.3, "flat": 0.2}},
                prediction_price=100, model_artifact_hashes={"model": "a" * 64},
                coverage_ratio=0.99, event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
                provider_chain=["akshare"], roster_hash="b" * 64,
                model_candidate="constant-class", market_regime="range",
            )
            created += 1
        day += timedelta(days=1)
    summary = store.summarize(market="cn", decision_context="close_confirmed")
    assert summary.valid_session_count == 60
    assert summary.forward_report_20_status == "ready"
    assert summary.primary_change_60_status == "eligible_for_review"
    assert store.generate_forward_report(minimum_sessions=20).is_file()
    assert store.generate_forward_report(minimum_sessions=60).is_file()


def test_research_shadow_price_backfill_uses_effective_entry_price(tmp_path) -> None:
    store = FileResearchShadowStore(tmp_path)
    controller = ResearchShadowController(store)
    session = controller.freeze_prediction(
        market="cn", decision_context="pre_open", cohort="cn_etf_benchmark",
        task="return_20d", symbol="510300", trade_date=date(2026, 7, 14),
        frozen_at=datetime(2026, 7, 15, 1, 10, tzinfo=timezone.utc),
        market_snapshot_id="snapshot-2", market_snapshot_hash="c" * 64,
        prediction={"p10": -0.03, "p50": 0.01, "p90": 0.05}, prediction_price=4,
        model_artifact_hashes={"model": "d" * 64}, coverage_ratio=0.99,
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        provider_chain=["akshare"],
    )
    outcome = controller.backfill_prices(
        session=session, horizon_sessions=1,
        filled_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        entry_price=4.1, closes=[4.2], lows=[4.0],
    )
    assert outcome.data_complete
    assert outcome.realized_return == pytest.approx(4.2 / 4.1 - 1)


def test_research_shadow_summary_reports_forward_evidence_progress(tmp_path) -> None:
    store = FileResearchShadowStore(tmp_path)
    controller = ResearchShadowController(store)
    answered = controller.freeze_prediction(
        market="cn", decision_context="close_confirmed", cohort="cn_equity_core",
        task="direction_1d", symbol="600000", trade_date=date(2026, 7, 14),
        frozen_at=datetime(2026, 7, 14, 7, 10, tzinfo=timezone.utc),
        market_snapshot_id="snapshot-3", market_snapshot_hash="e" * 64,
        prediction={"up": 0.4, "down": 0.3, "flat": 0.3}, prediction_price=10,
        model_artifact_hashes={"model": "f" * 64}, coverage_ratio=0.98,
        event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        provider_chain=["akshare"], model_disagreement=0.1,
    )
    controller.backfill_prices(
        session=answered, horizon_sessions=1,
        filled_at=datetime(2026, 7, 15, tzinfo=timezone.utc), closes=[10.1], lows=[9.9],
    )
    controller.freeze_prediction(
        market="cn", decision_context="close_confirmed", cohort="cn_equity_core",
        task="direction_1d", symbol="600001", trade_date=date(2026, 7, 14),
        frozen_at=datetime(2026, 7, 14, 7, 10, tzinfo=timezone.utc),
        market_snapshot_id="snapshot-4", market_snapshot_hash="1" * 64,
        prediction={}, prediction_price=8, model_artifact_hashes={}, coverage_ratio=0.5,
        event_coverage_status=EventCoverageStatus.FETCH_FAILED,
        provider_chain=["akshare"],
    )
    summary = store.summarize(market="cn", task="direction_1d")
    assert summary.session_count == 2
    assert summary.answered_count == 1
    assert summary.abstain_rate == 0.5
    assert summary.completed_outcomes[1] == 1
