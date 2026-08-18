from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from investment_research.agent.llm import HTTPStructuredProvider, LLMToolDefinition, LLMToolRequest
from investment_research.agent.models import AgentPlan, AgentRun, CitationAudit, ProviderProfile, ReportNarrative
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


def _write_long_term_scorecard(tmp_path, *, symbol: str, as_of_date: str, completeness: float = 96.0, with_model_readings: bool = True) -> None:
    report = tmp_path / "artifacts" / "long_term_training" / "latest.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    scorecard = {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "long_term_quality": 76.0,
        "growth_stability": 72.0,
        "valuation_position": 78.0,
        "shareholder_return": 68.0,
        "long_term_risk": 58.0,
        "evidence_completeness": completeness,
        "evidence": [],
        "score_type": "pit_evidence_scorecard_not_trained_label",
    }
    if with_model_readings:
        scorecard["long_term_model_readings"] = {
            task: {
                "q10": values[0], "q50": values[1], "q90": values[2],
                "horizon_days": horizon, "model": "fixture-model",
                "model_version": f"fixture:{task}", "data_as_of": f"{as_of_date}T07:00:00+00:00",
                "snapshot_id": "fixture-snapshot", "artifact_hash": "a" * 64,
            }
            for task, values, horizon in (
                ("excess_return_120d", (-0.10, 0.02, 0.14), 120),
                ("excess_return_240d", (-0.16, 0.04, 0.22), 240),
                ("future_max_drawdown_120d", (-0.34, -0.18, -0.08), 120),
                ("future_max_drawdown_240d", (-0.43, -0.24, -0.11), 240),
            )
        }
    report.write_text(
        json.dumps({
            "status": "research_only",
            "scorecards": [scorecard],
        }),
        encoding="utf-8",
    )


def test_long_term_agent_enforces_long_term_tool_sequence_without_short_forecasts(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    _write_long_term_scorecard(tmp_path, symbol=asset.ticker, as_of_date=now.date().isoformat())

    run = AgentOrchestrator(uow, project_root=tmp_path).create_and_execute(
        user=user, asset_id=str(asset.id), task_text="请解释这家公司的长期基本面和估值风险", as_of=now,
    )

    assert run.state.value == "completed"
    tool_ids = [item.tool_id for item in uow.agent_runtime.list_tool_calls(str(run.id))]
    required = [
        "collect_pit_evidence", "get_long_term_scorecard", "get_long_term_model_readings", "get_long_term_data_trust",
        "get_long_term_evidence_balance", "get_long_term_fact_cards", "quality_gate",
    ]
    assert [tool for tool in tool_ids if tool in required] == required
    assert "get_four_task_forecasts" not in tool_ids
    assert "approved_model_inference" not in tool_ids
    explanation = next(
        item for item in uow.agent_runtime.list_events(str(run.id))
        if item.event_type == "llm.research_explanation"
    )
    assert explanation.payload["status"] == "research_only"
    assert explanation.payload["applicable_horizon"]
    assert explanation.payload["current_assessment"]
    assert explanation.payload["reasoning"]
    assert explanation.payload["major_risks"]
    assert explanation.payload["observation_conditions"]
    assert explanation.payload["invalidation_conditions"]
    assert explanation.payload["data_as_of"] == now.date().isoformat()
    assert set(explanation.payload["long_term_model_readings"]) == {
        "excess_return_120d", "excess_return_240d",
        "future_max_drawdown_120d", "future_max_drawdown_240d",
    }
    assert explanation.payload["citation_audit"]["valid"] is True
    assert explanation.payload["citation_audit"]["source_count"] >= 1
    assert explanation.payload["compliance_audit"]["allowed"] is True
    assert explanation.payload["compliance_audit"]["policy_version"] == "cn-public-research-text-v1"
    assert explanation.payload["compliance_audit"]["llm_output_rejected"] is False
    assert all(source["citation_id"] for source in explanation.payload["sources"])


def test_long_term_scorecard_and_model_readings_are_separate_tool_payloads(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    _write_long_term_scorecard(tmp_path, symbol=asset.ticker, as_of_date=now.date().isoformat())
    run = AgentOrchestrator(uow, project_root=tmp_path).create_and_execute(
        user=user, asset_id=str(asset.id), task_text="长期基本面", as_of=now,
    )
    service = AgentOrchestrator(uow, project_root=tmp_path)
    context = {"research_pit": service._research_pit_context(run)}
    scorecard = service._execute_research_pit_function_call(
        run, user, context, "get_long_term_scorecard", {}, context["research_pit"],
    )
    readings = service._execute_research_pit_function_call(
        run, user, context, "get_long_term_model_readings", {}, context["research_pit"],
    )
    assert "long_term_model_readings" not in scorecard
    assert readings["ok"] is True
    assert set(readings["model_readings"]) == {
        "excess_return_120d", "excess_return_240d",
        "future_max_drawdown_120d", "future_max_drawdown_240d",
    }


def test_long_term_agent_abstains_when_four_model_readings_are_missing(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    _write_long_term_scorecard(
        tmp_path, symbol=asset.ticker, as_of_date=now.date().isoformat(), with_model_readings=False,
    )

    run = AgentOrchestrator(uow, project_root=tmp_path).create_and_execute(
        user=user, asset_id=str(asset.id), task_text="请解释长期模型和经营质量", as_of=now,
    )

    assert run.state.value == "abstained"
    assert "long_term_model_readings_unavailable" in (run.abstain_reason or "")
    explanation = next(
        item for item in uow.agent_runtime.list_events(str(run.id))
        if item.event_type == "llm.research_explanation"
    )
    assert explanation.payload["status"] == "abstain"
    assert "四项长期模型读数尚未生成" in explanation.payload["summary"]


def test_long_term_agent_abstains_when_scorecard_is_missing(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)

    run = AgentOrchestrator(uow, project_root=tmp_path).create_and_execute(
        user=user, asset_id=str(asset.id), task_text="给我长期投资研究结论", as_of=now,
    )

    assert run.state.value == "abstained"
    assert run.verdict == "hold"
    assert "long_term_training_report_missing" in (run.abstain_reason or "")
    tool_ids = [item.tool_id for item in uow.agent_runtime.list_tool_calls(str(run.id))]
    assert "get_long_term_scorecard" in tool_ids
    assert "get_long_term_fact_cards" in tool_ids
    assert "get_four_task_forecasts" not in tool_ids
    explanation = next(
        item for item in uow.agent_runtime.list_events(str(run.id))
        if item.event_type == "llm.research_explanation"
    )
    assert explanation.payload["status"] == "abstain"
    assert "暂不形成长期判断" in explanation.payload["summary"]


def test_unsafe_long_term_narrative_is_rejected_and_replaced(tmp_path, monkeypatch) -> None:
    uow, user, asset, now = _context(tmp_path)
    _write_long_term_scorecard(tmp_path, symbol=asset.ticker, as_of_date=now.date().isoformat())
    service = AgentOrchestrator(uow, project_root=tmp_path)
    original = service._llm_or_default

    def unsafe_llm(run, node_name, response_model, payload, default, max_output_tokens):
        if response_model is ReportNarrative:
            return ReportNarrative(
                summary="建议买入并长期持有。", supporting_view="评分较高。", contrary_view="无。",
                observation_conditions=[], evidence_ids=[], contains_trade_instruction=False,
            )
        return original(run, node_name, response_model, payload, default, max_output_tokens)

    monkeypatch.setattr(service, "_llm_or_default", unsafe_llm)
    run = service.create_and_execute(
        user=user, asset_id=str(asset.id), task_text="长期基本面分析", as_of=now,
    )

    events = uow.agent_runtime.list_events(str(run.id))
    assert any(item.event_type == "llm.output_rejected" for item in events)
    explanation = next(item for item in events if item.event_type == "llm.research_explanation")
    rendered = json.dumps(explanation.payload, ensure_ascii=False)
    assert "建议买入" not in rendered
    assert "长期持有" not in rendered
    assert explanation.payload["generated_by"] == "deterministic_fallback"
    assert explanation.payload["compliance_audit"]["allowed"] is True
    assert explanation.payload["compliance_audit"]["llm_output_rejected"] is True
    assert set(explanation.payload["compliance_audit"]["rejected_reason_codes"]) >= {
        "DIRECT_BUY_INSTRUCTION", "HOLD_INSTRUCTION",
    }


def test_agent_abstains_when_trusted_model_input_is_insufficient(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path, with_prices=False)
    run = AgentOrchestrator(uow).create_and_execute(user=user, asset_id=str(asset.id), task_text="Assess drawdown risk", as_of=now)

    assert run.state.value == "abstained"
    assert run.verdict in {"hold", "block"}
    assert run.report_id is None
    assert run.budget.llm_calls_used <= run.budget.max_llm_calls
    assert run.budget.tool_calls_used <= run.budget.max_tool_calls
    events = uow.agent_runtime.list_events(str(run.id))
    assert events[-1].event_type == "run.abstained"
    explanation = next(item for item in events if item.event_type == "llm.research_explanation")
    assert explanation.payload["status"] == "abstain"
    assert explanation.payload["summary"]
    assert isinstance(explanation.payload["observation_conditions"], list)
    assert explanation.payload["sources"] == []


def test_agent_uses_frozen_research_pit_artifacts_without_legacy_price_series(tmp_path) -> None:
    """The user-facing assistant must not fall back to the retired model path."""
    uow = SQLiteUnitOfWork(tmp_path / "agent.db")
    now = datetime.now(timezone.utc)
    user = User(email="pit@example.com", display_name="PIT", auth_subject="user:pit", provenance=_provenance(now))
    uow.users.add(user, password_hash="test")
    asset = Asset(ticker="600519", name="Moutai", asset_type=AssetType.EQUITY, provenance=_provenance(now))
    uow.assets.add(asset)
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=user.id)

    output_dir = tmp_path / "artifacts" / "research-output"
    output_dir.mkdir(parents=True)
    tasks = ("direction_1d", "direction_5d", "return_20d", "drawdown_20d")
    predictions = [
        {
            "symbol": "600519",
            "task": task,
            "trade_date": "2026-08-07",
            "market_snapshot_id": "snapshot-1",
            "market_snapshot_hash": "snapshot-hash",
            "prediction_price": 1200.0,
            "coverage_ratio": 1.0,
            "core_feature_coverage": 1.0,
            "data_status": "degraded",
            "provider_chain": ["akshare", "baostock"],
            "abstained": False,
            "prediction": {"reference": task},
            "gating_reasons": [],
            "abstain_reasons": [],
            "model_candidate": "baseline",
            "research_status": "exploratory",
            "model_disagreement": 0.12,
        }
        for task in tasks
    ]
    prediction_ref = "artifacts/research-output/predictions.json"
    (output_dir / "predictions.json").write_text(
        json.dumps({"data_tier": "research_pit", "deployment_ready": False, "predictions": predictions}),
        encoding="utf-8",
    )
    report_dir = tmp_path / "artifacts" / "cn_research_demo"
    report_dir.mkdir(parents=True)
    (report_dir / "latest.json").write_text(
        json.dumps({
            "data_tier": "research_pit",
            "deployment_ready": False,
            "inference": {task: {"prediction_ref": prediction_ref} for task in tasks},
        }),
        encoding="utf-8",
    )

    run = AgentOrchestrator(uow, project_root=tmp_path).create_and_execute(
        user=user,
        asset_id=str(asset.id),
        task_text="为什么当前风险是这个水平？",
        as_of=now,
    )

    assert run.state.value == "completed"
    assert run.verdict == "warn"
    tool_ids = [item.tool_id for item in uow.agent_runtime.list_tool_calls(str(run.id))]
    assert "get_price_trend" in tool_ids
    assert "get_four_task_forecasts" in tool_ids
    assert "build_29_features" not in tool_ids
    explanation = next(item for item in uow.agent_runtime.list_events(str(run.id)) if item.event_type == "llm.research_explanation")
    assert explanation.payload["status"] == "research_only"
    assert explanation.payload["generated_by"] == "deterministic_fallback"


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


def test_agent_pit_collection_does_not_use_collection_time_as_public_time(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    unverified = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.NEWS,
        title="Unverified timing",
        summary="Collected locally without a verifiable publication timestamp.",
        collected_at=now - timedelta(hours=1),
        published_at=None,
        publication_time_verified=False,
        provenance=_provenance(now),
    )
    uow.evidence.add(unverified)
    run = AgentRun(owner_user_id=user.id, asset_id=asset.id, task_text="Assess", as_of=now, correlation_id="pit-missing-public-time")
    uow.agent_runtime.add_run(run)

    assert AgentOrchestrator(uow)._collect_evidence(run) == []


def test_agent_rejects_unregistered_tools(tmp_path) -> None:
    uow, _, _, _ = _context(tmp_path)
    with pytest.raises(AgentExecutionError, match="Unregistered"):
        AgentOrchestrator(uow)._validate_tools(AgentPlan(tool_ids=["execute_trade"]))


def test_function_call_executor_rejects_unallowlisted_or_parameterized_actions(tmp_path) -> None:
    uow, user, asset, now = _context(tmp_path)
    run = AgentRun(owner_user_id=user.id, asset_id=asset.id, task_text="Assess", as_of=now, correlation_id="function-call-test")
    uow.agent_runtime.add_run(run)
    service = AgentOrchestrator(uow)

    unknown = service._execute_function_call(run, user, {}, "execute_trade", {})
    parameterized = service._execute_function_call(run, user, {}, "collect_pit_evidence", {"url": "https://example.invalid"})

    assert unknown == {"ok": False, "error": "tool_not_allowlisted"}
    assert parameterized == {"ok": False, "error": "arguments_not_permitted"}
    calls = uow.agent_runtime.list_tool_calls(str(run.id))
    assert [item.tool_id for item in calls] == ["execute_trade", "collect_pit_evidence"]


def test_openai_compatible_provider_sends_native_allowlisted_tool_schema(monkeypatch) -> None:
    """A configured provider must receive actual chat-completions tools, not prose."""
    profile = ProviderProfile(
        owner_user_id=uuid4(),
        name="test-provider",
        protocol="openai_compatible",
        endpoint="https://example.com/v1/chat/completions",
        model="test-model",
    )
    provider = HTTPStructuredProvider(profile, api_key="test-key")
    monkeypatch.setattr(provider, "_validate_runtime_endpoint", lambda: None)
    observed: dict[str, object] = {}

    class Response:
        def read(self):
            return json.dumps(
                {
                    "id": "chatcmpl-test",
                    "model": "test-model",
                    "choices": [{"message": {"content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "quality_gate", "arguments": "{}"}}]}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout, context=None):
        observed["payload"] = json.loads(request.data.decode("utf-8"))
        observed["authorization"] = request.headers.get("Authorization")
        assert timeout == 20.0
        return Response()

    monkeypatch.setattr("investment_research.agent.llm.urlopen", fake_urlopen)
    result = provider.invoke_tools(
        LLMToolRequest(
            node_name="tool_selection",
            system_prompt="read-only",
            messages=[{"role": "user", "content": "research"}],
            tools=[LLMToolDefinition(name="quality_gate", description="gate", parameters={"type": "object", "properties": {}, "additionalProperties": False})],
            max_output_tokens=100,
        )
    )

    assert observed["payload"] == {
        "model": "test-model",
        "messages": [{"role": "system", "content": "read-only"}, {"role": "user", "content": "research"}],
        "tools": [{"type": "function", "function": {"name": "quality_gate", "description": "gate", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_tokens": 100,
    }
    assert result.tool_calls[0].name == "quality_gate"
    assert result.tool_calls[0].arguments == {}


def test_openai_compatible_provider_completes_a_v1_base_endpoint(monkeypatch) -> None:
    profile = ProviderProfile(
        owner_user_id=uuid4(),
        name="base-url-provider",
        protocol="openai_compatible",
        endpoint="https://api.example.com/v1",
        model="test-model",
    )
    provider = HTTPStructuredProvider(profile, api_key="test-key")
    monkeypatch.setattr(provider, "_validate_runtime_endpoint", lambda: None)
    observed: dict[str, object] = {}

    class Response:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": None, "tool_calls": []}}]}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout, context=None):
        observed["url"] = request.full_url
        return Response()

    monkeypatch.setattr("investment_research.agent.llm.urlopen", fake_urlopen)
    provider.invoke_tools(
        LLMToolRequest(
            node_name="tool_selection", system_prompt="read-only", messages=[{"role": "user", "content": "research"}],
            tools=[], max_output_tokens=100,
        )
    )
    assert observed["url"] == "https://api.example.com/v1/chat/completions"


@pytest.mark.parametrize(
    ("protocol", "endpoint", "response", "expected_key", "expected_name"),
    [
        (
            "anthropic_messages", "https://api.anthropic.example/v1/messages",
            {"content": [{"type": "tool_use", "id": "use-1", "name": "quality_gate", "input": {}}], "usage": {"input_tokens": 2, "output_tokens": 1}},
            "input_schema", "quality_gate",
        ),
        (
            "gemini_generate_content", "https://generativelanguage.example/v1beta/models/test:generateContent",
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "quality_gate", "args": {}}}]}}], "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1}},
            "functionDeclarations", "quality_gate",
        ),
    ],
)
def test_native_provider_protocols_emit_native_function_calls(monkeypatch, protocol, endpoint, response, expected_key, expected_name) -> None:
    profile = ProviderProfile(owner_user_id=uuid4(), name="native", protocol=protocol, endpoint=endpoint, model="test-model")
    provider = HTTPStructuredProvider(profile, api_key="test-key")
    monkeypatch.setattr(provider, "_validate_runtime_endpoint", lambda: None)
    observed = {}

    class Response:
        def read(self):
            return json.dumps(response).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout, context=None):
        observed["payload"] = json.loads(request.data.decode("utf-8"))
        observed["headers"] = dict(request.headers.items())
        return Response()

    monkeypatch.setattr("investment_research.agent.llm.urlopen", fake_urlopen)
    result = provider.invoke_tools(LLMToolRequest(
        node_name="tool_selection", system_prompt="read-only", messages=[{"role": "user", "content": "research"}],
        tools=[LLMToolDefinition(name="quality_gate", description="gate", parameters={"type": "object", "properties": {}, "additionalProperties": False})], max_output_tokens=100,
    ))
    assert result.tool_calls[0].name == expected_name
    encoded = json.dumps(observed["payload"])
    assert expected_key in encoded


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
