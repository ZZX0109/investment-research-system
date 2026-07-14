from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from investment_research.agent.models import AgentPlan, AgentRun, CitationAudit
from investment_research.agent.service import AgentExecutionError, AgentOrchestrator
from investment_research.domain.base import Provenance
from investment_research.domain.enums import AssetType, DataMode, DataSourceType, EvidenceType
from investment_research.domain.models import AnalysisRun, Asset, Evidence, PricePoint, PriceSeries, User
from investment_research.pipeline.service import AnalysisPipelineService
from investment_research.workers.paper_validation import PaperValidationWorker
from investment_research.repository.sqlite import SQLiteUnitOfWork


def _provenance(at: datetime) -> Provenance:
    return Provenance(data_mode=DataMode.REAL, source_type=DataSourceType.REAL, source_name="sec-test", observed_at=at)


def _context(tmp_path, *, with_prices: bool = True):
    now = datetime.now(timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "agent.db")
    user = User(email="agent@example.com", display_name="Agent", auth_subject="user:agent", provenance=_provenance(now))
    uow.users.add(user, password_hash="test")
    asset = Asset(ticker="AAPL", name="Apple", asset_type=AssetType.EQUITY, provenance=_provenance(now))
    uow.assets.add(asset)
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)
    if with_prices:
        points = [
            PricePoint(asset_id=asset.id, timestamp=now - timedelta(days=2 - index), open=100 + index, high=101 + index, low=99 + index, close=100 + index, volume=1000, provenance=_provenance(now))
            for index in range(2)
        ]
        uow.price_series.add(PriceSeries(asset_id=asset.id, interval="1d", points=points, provenance=_provenance(now)))
    return uow, user, asset, now


def test_agent_abstains_when_trusted_model_input_is_insufficient(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path, with_prices=False)
    run = AgentOrchestrator(uow).create_and_execute(user=user, asset_id=str(asset.id), task_text="Assess drawdown risk", as_of=now)

    assert run.state.value == "abstained"
    assert run.verdict in {"hold", "block"}
    assert run.report_id is None
    assert run.budget.llm_calls_used <= run.budget.max_llm_calls
    assert run.budget.tool_calls_used <= run.budget.max_tool_calls
    assert uow.agent_runtime.list_events(str(run.id))[-1].event_type == "run.abstained"


def test_agent_abstains_until_legacy_cutoff_model_is_reapproved(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path, with_prices=False)
    for role in ("asset", "benchmark", "sector", "style"):
        points = []
        for index in range(90):
            timestamp = now - timedelta(days=89 - index, minutes=1)
            close = 100.0 + index * (0.08 if role == "asset" else 0.05)
            points.append(
                PricePoint(
                    asset_id=asset.id,
                    timestamp=timestamp,
                    open=close - 0.2,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                    volume=1000 + index * 5,
                    provenance=_provenance(timestamp),
                )
            )
        uow.price_series.add(
            PriceSeries(
                asset_id=asset.id,
                interval="1d",
                series_role=role,
                reference_symbol=None if role == "asset" else f"{role.upper()}-REF",
                points=points,
                provenance=_provenance(now),
            )
        )
    for index in range(2):
        uow.evidence.add(
            Evidence(
                asset_id=asset.id,
                evidence_type=EvidenceType.FILING,
                title=f"Authority filing {index + 1}",
                summary="A published filing fact available before the research cutoff.",
                source_url=f"https://www.sec.gov/Archives/test-{index + 1}",
                collected_at=now - timedelta(minutes=5 - index),
                published_at=now - timedelta(minutes=10 - index),
                provenance=_provenance(now),
            )
        )

    run = AgentOrchestrator(uow).create_and_execute(
        user=user,
        asset_id=str(asset.id),
        task_text="Assess single-asset drawdown risk",
        as_of=now,
    )

    audit = uow.research_audits.get_for_run(str(run.research_run_id))
    failed_checks = [] if audit is None else [item for item in audit.checks if not item["passed"]]
    bundle = AnalysisPipelineService(uow).get_bundle(str(run.research_run_id))
    assert run.state.value == "abstained", {
        "failed_checks": failed_checks,
        "snapshot_as_of": None if bundle is None else bundle.snapshot.as_of,
        "evidence_times": [] if bundle is None else [(item.published_at, item.collected_at) for item in bundle.evidence],
    }
    assert run.verdict in {"hold", "block"}
    assert run.report_id is None
    assert run.research_run_id is not None
    event_types = [item.event_type for item in uow.agent_runtime.list_events(str(run.id))]
    assert event_types[-1] == "run.abstained"


def test_agent_pit_collection_excludes_future_evidence(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    past = Evidence(asset_id=asset.id, evidence_type=EvidenceType.FILING, title="Past", summary="Public", collected_at=now - timedelta(hours=1), published_at=now - timedelta(hours=1), provenance=_provenance(now))
    future = Evidence(asset_id=asset.id, evidence_type=EvidenceType.NEWS, title="Future", summary="Not public", collected_at=now + timedelta(hours=1), published_at=now + timedelta(hours=1), provenance=_provenance(now))
    uow.evidence.add(past)
    uow.evidence.add(future)
    run = AgentRun(owner_user_id=user.id, asset_id=asset.id, task_text="Assess", as_of=now, correlation_id="pit-test")
    uow.agent_runtime.add_run(run)

    selected = AgentOrchestrator(uow)._collect_evidence(run)

    assert [item.id for item in selected] == [past.id]


def test_agent_rejects_unregistered_tools(tmp_path) -> None:
    uow, _, _, _ = _context(tmp_path)
    with pytest.raises(AgentExecutionError, match="Unregistered"):
        AgentOrchestrator(uow)._validate_tools(AgentPlan(tool_ids=["execute_trade"]))


def test_agent_repairs_only_citation_failure_once(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.FILING,
        title="Filed result",
        summary="An authority filing available by the run cutoff.",
        collected_at=now,
        published_at=now,
        provenance=_provenance(now),
    )
    run = AgentRun(owner_user_id=user.id, asset_id=asset.id, task_text="Assess", as_of=now, correlation_id="repair-test")
    uow.agent_runtime.add_run(run)
    context = {
        "evidence": [evidence],
        "audit": {
            "verdict": "hold",
            "deterministic_verdict": "warn",
            "citation": CitationAudit(supported=False, unsupported_claims=["Unsupported wording"]).model_dump(mode="json"),
        },
    }

    result = AgentOrchestrator(uow)._repair_or_abstain(run, context)

    assert result == {"abstain": False, "verdict": "warn", "reason": None, "repaired": True}
    saved = uow.agent_runtime.get_run(str(run.id), user.id)
    assert saved is not None
    assert saved.budget.repair_count == 1
    event_types = [item.event_type for item in uow.agent_runtime.list_events(str(run.id))]
    assert event_types[-2:] == ["run.repair_started", "run.repair_completed"]


def test_agent_cannot_repair_deterministic_hold(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    run = AgentRun(owner_user_id=user.id, asset_id=asset.id, task_text="Assess", as_of=now, correlation_id="hold-test")
    uow.agent_runtime.add_run(run)

    result = AgentOrchestrator(uow)._repair_or_abstain(
        run,
        {
            "evidence": [],
            "audit": {
                "verdict": "hold",
                "deterministic_verdict": "hold",
                "citation": CitationAudit(supported=False, unsupported_claims=["No evidence"]).model_dump(mode="json"),
            },
        },
    )

    assert result["abstain"] is True
    assert run.budget.repair_count == 0


def test_paper_worker_backfills_realized_drawdown_once_due(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    prediction_as_of = now - timedelta(days=35)
    run = AnalysisRun(
        asset_id=asset.id,
        triggered_by=user.auth_subject,
        input_snapshot_ref="paper-test",
        as_of=prediction_as_of,
        provenance=_provenance(prediction_as_of),
    )
    uow.analysis_runs.add(run)
    uow.domain.record_research_run(run=run, owner=user, correlation_id=str(run.id))
    points = []
    for index in range(20):
        close = 100.0 if index < 10 else 100.0 - (index - 9) * 1.2
        observed_at = prediction_as_of + timedelta(days=index + 1)
        points.append(PricePoint(asset_id=asset.id, timestamp=observed_at, open=close, high=close + 1, low=close - 1, close=close, volume=1000, provenance=_provenance(observed_at)))
    uow.price_series.add(PriceSeries(asset_id=asset.id, interval="1d", points=points, provenance=_provenance(now)))
    uow.agent_runtime.add_paper_prediction(
        owner_user_id=user.id,
        asset_id=asset.id,
        research_run_id=run.id,
        model_role="primary",
        model_id="random-forest@test",
        as_of=prediction_as_of,
        risk_probability=0.85,
        feature_coverage=1.0,
        abstained=False,
        feature_values=[0.0] * 29,
    )

    first = PaperValidationWorker(uow).evaluate_due(now)
    second = PaperValidationWorker(uow).evaluate_due(now)
    summary = uow.agent_runtime.paper_summary(user.id)

    assert first == 1
    assert second == 0
    assert summary["prospective"]["primary"]["evaluated_count"] == 1
    assert summary["prospective"]["primary"]["drawdown_lift"] == 0.0


def test_provider_profile_rejects_private_remote_endpoint(tmp_path) -> None:
    _, user, _, _ = _context(tmp_path)
    from investment_research.agent.models import ProviderProfile

    with pytest.raises(ValueError, match="HTTPS"):
        ProviderProfile(owner_user_id=user.id, name="unsafe", protocol="openai_compatible", endpoint="http://127.0.0.1:8080/v1", model="remote")
