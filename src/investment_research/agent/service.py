from __future__ import annotations

from datetime import datetime
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel

from investment_research.agent.llm import LLMProviderError, LLMRequest, LLMResponse, build_llm_provider
from investment_research.agent.models import (
    AgentPlan,
    AgentRun,
    AgentRunState,
    CitationAudit,
    CounterEvidenceQuery,
    ProviderProfile,
    ReportNarrative,
    TaskClassification,
)
from investment_research.domain.base import utc_now
from investment_research.domain.models import User
from investment_research.pipeline.models import AnalysisBundle
from investment_research.pipeline.service import AnalysisPipelineService
from investment_research.pipeline.model_inference import DeploymentModelInferenceService
from investment_research.report.service import ReportService
from investment_research.repository.agent_runtime import stable_hash
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.advanced_research import ResearchAuditService
from investment_research.service.credential_vault import CredentialVault, CredentialVaultError


T = TypeVar("T", bound=BaseModel)


AGENT_NODES = (
    "task_intake",
    "task_classification",
    "plan_generation",
    "tool_selection",
    "evidence_collection",
    "structured_feature_build",
    "model_inference",
    "counter_evidence_search",
    "self_audit",
    "repair_or_abstain",
    "report_generation",
)

AGENT_TOOLS = {
    "collect_pit_evidence": "Collect evidence published no later than the run as-of.",
    "build_29_features": "Build the immutable investment-risk-features-v1 vector.",
    "approved_model_inference": "Run the approved primary model with champion fallback.",
    "historical_analogy": "Retrieve point-in-time historical risk analogies.",
    "quality_gate": "Apply deterministic freshness, provenance, coverage, and model gates.",
}


class AgentExecutionError(RuntimeError):
    pass


class AgentOrchestrator:
    """Authoritative typed executor for evidence-bound single-asset research."""

    def __init__(self, uow: SQLiteUnitOfWork, *, credential_vault: CredentialVault | None = None) -> None:
        self.uow = uow
        self.runtime = uow.agent_runtime
        self.credential_vault = credential_vault

    def create_and_execute(
        self,
        *,
        user: User,
        asset_id: str,
        task_text: str,
        as_of: datetime,
        provider_profile_id: str | None = None,
        user_preference: str = "conservative",
    ) -> AgentRun:
        run = AgentRun(
            owner_user_id=user.id,
            asset_id=UUID(asset_id),
            provider_profile_id=None if provider_profile_id is None else UUID(provider_profile_id),
            task_text=task_text,
            user_preference=user_preference,
            as_of=as_of,
            correlation_id=str(uuid4()),
        )
        self.runtime.add_run(run)
        self.runtime.add_event(run.id, "run.created", payload={"correlation_id": run.correlation_id})
        return self.execute(str(run.id), user=user)

    def execute(self, run_id: str, *, user: User) -> AgentRun:
        run = self.get(run_id, user=user)
        if run.state in {AgentRunState.COMPLETED, AgentRunState.ABSTAINED, AgentRunState.CANCELLED}:
            return run
        resuming = run.state is AgentRunState.FAILED
        run = self._save(run, state=AgentRunState.RUNNING, abstain_reason=None, completed_at=None)
        if resuming:
            self.runtime.add_event(run.id, "run.resumed", node_name=run.current_node)
        context: dict[str, object] = {}
        try:
            restored = AnalysisPipelineService(self.uow).get_bundle(str(run.research_run_id)) if resuming and run.research_run_id else None
            if restored is not None:
                context["intake"] = {"asset_id": str(run.asset_id), "resumed": True}
                context["classification"] = TaskClassification(task_type="single_asset_risk_research", user_preference=run.user_preference)  # type: ignore[arg-type]
                context["plan"] = AgentPlan(tool_ids=list(AGENT_TOOLS))
                context["tools"] = list(AGENT_TOOLS)
                context["evidence"] = [item for item in restored.evidence if (item.published_at or item.collected_at) <= run.as_of][: run.budget.max_evidence]
                context["bundle"] = restored
                restored_prediction = restored.predictions[0] if restored.predictions else None
                context["prediction"] = {
                    "available": bool(restored_prediction and restored_prediction.risk_probability is not None),
                    "risk_probability": None if restored_prediction is None else restored_prediction.risk_probability,
                    "model": None if restored_prediction is None else f"{restored_prediction.model_name}@{restored_prediction.model_version}",
                    "approved": bool(restored_prediction and restored_prediction.deployment_approved),
                    "feature_coverage": 0.0 if restored_prediction is None else restored_prediction.feature_coverage,
                    "restored": True,
                }
                self.runtime.add_event(run.id, "run.checkpoint_restored", node_name="model_inference", payload={"research_run_id": str(run.research_run_id)})
            else:
                context["intake"] = self._node(run, "task_intake", context, lambda: self._task_intake(run, user))
                context["classification"] = self._node(
                    run, "task_classification", context,
                    lambda: self._llm_or_default(
                        run, "task_classification", TaskClassification,
                        {"task_text": run.task_text, "user_preference": run.user_preference, "evidence_ids": []},
                        TaskClassification(task_type="single_asset_risk_research", user_preference=run.user_preference),  # type: ignore[arg-type]
                        400,
                    ),
                )
                context["plan"] = self._node(run, "plan_generation", context, lambda: self._build_plan(run, context))
                context["tools"] = self._node(run, "tool_selection", context, lambda: self._validate_tools(context["plan"]))
                context["evidence"] = self._node(run, "evidence_collection", context, lambda: self._collect_evidence(run))
                context["bundle"] = self._node(run, "structured_feature_build", context, lambda: self._build_bundle(run, user))
                context["prediction"] = self._node(run, "model_inference", context, lambda: self._model_result(run, context["bundle"]))
            context["counter"] = self._node(run, "counter_evidence_search", context, lambda: self._counter_evidence(run, context))
            context["audit"] = self._node(run, "self_audit", context, lambda: self._audit(run, user, context))
            action = self._node(run, "repair_or_abstain", context, lambda: self._repair_or_abstain(run, context))
            if action["abstain"]:
                run = self._save(
                    run,
                    state=AgentRunState.ABSTAINED,
                    verdict=action["verdict"],
                    abstain_reason=action["reason"],
                    current_node="repair_or_abstain",
                    completed_at=utc_now(),
                )
                self.runtime.add_event(run.id, "run.abstained", node_name="repair_or_abstain", payload=action)
                return run
            context["report"] = self._node(run, "report_generation", context, lambda: self._report(run, context))
            report = context["report"]
            run = self._save(
                run,
                state=AgentRunState.COMPLETED,
                verdict=action["verdict"],
                report_id=report.id,
                current_node="report_generation",
                completed_at=utc_now(),
            )
            self.runtime.add_event(run.id, "run.completed", payload={"report_id": str(report.id)})
            return run
        except Exception as exc:
            run = self._save(
                run,
                state=AgentRunState.FAILED,
                abstain_reason=f"{type(exc).__name__}: {str(exc)[:300]}",
                completed_at=utc_now(),
            )
            self.runtime.add_event(run.id, "run.failed", node_name=run.current_node, payload={"error": run.abstain_reason or "unknown"})
            return run

    def get(self, run_id: str, *, user: User) -> AgentRun:
        run = self.runtime.get_run(run_id, user.id)
        if run is None:
            raise ValueError("Agent run not found")
        return run

    def cancel(self, run_id: str, *, user: User) -> AgentRun:
        run = self.get(run_id, user=user)
        if run.state in {AgentRunState.COMPLETED, AgentRunState.ABSTAINED, AgentRunState.FAILED}:
            raise ValueError("Finished Agent run cannot be cancelled")
        run = self._save(run, state=AgentRunState.CANCELLED, completed_at=utc_now())
        self.runtime.add_event(run.id, "run.cancelled")
        return run

    def _node(self, run: AgentRun, name: str, context: object, function):
        current = self.runtime.get_run(str(run.id), run.owner_user_id) or run
        if current.state is AgentRunState.CANCELLED:
            raise AgentExecutionError("Agent run was cancelled")
        run.current_node = name
        run.updated_at = utc_now()
        self.runtime.update_run(run)
        execution_id = self.runtime.start_node(run, name, context)
        try:
            output = function()
        except Exception as exc:
            self.runtime.finish_node(execution_id, run.id, name, {}, error=f"{type(exc).__name__}: {exc}")
            raise
        self.runtime.finish_node(execution_id, run.id, name, self._dump(output))
        return output

    def _task_intake(self, run: AgentRun, user: User) -> dict[str, object]:
        asset = self.uow.assets.get(str(run.asset_id))
        if asset is None:
            raise AgentExecutionError("Asset not found")
        if self.uow.domain.is_registered_user(user.id):
            self.uow.domain.assert_access(resource_type="asset", resource_id=str(run.asset_id), user_id=user.id)
        if run.as_of > utc_now():
            raise AgentExecutionError("as_of cannot be in the future")
        return {"asset_id": str(asset.id), "ticker": asset.ticker, "task_type": run.task_type, "as_of": run.as_of.isoformat()}

    def _build_plan(self, run: AgentRun, context: dict[str, object]) -> AgentPlan:
        default = AgentPlan(tool_ids=list(AGENT_TOOLS))
        plan = self._llm_or_default(
            run, "plan_generation", AgentPlan,
            {"classification": self._dump(context["classification"]), "allowed_tool_ids": list(AGENT_TOOLS), "evidence_ids": []},
            default, 800,
        )
        self.runtime.add_plan(run.id, plan)
        return plan

    def _validate_tools(self, plan: object) -> list[str]:
        assert isinstance(plan, AgentPlan)
        invalid = sorted(set(plan.tool_ids) - set(AGENT_TOOLS))
        if invalid:
            raise AgentExecutionError(f"Unregistered Agent tools: {', '.join(invalid)}")
        return plan.tool_ids

    def _collect_evidence(self, run: AgentRun) -> list[object]:
        evidence = [
            item for item in self.uow.evidence.list_for_asset(str(run.asset_id))
            if (item.published_at or item.collected_at) <= run.as_of
        ]
        source_counts: dict[str, int] = {}
        selected = []
        for item in evidence:
            source = item.provenance.source_name
            if source_counts.get(source, 0) >= 3:
                continue
            source_counts[source] = source_counts.get(source, 0) + 1
            selected.append(item)
            if len(selected) >= run.budget.max_evidence:
                break
        self._record_tool(run, "evidence_collection", "collect_pit_evidence", {"as_of": run.as_of.isoformat()}, {"evidence_ids": [str(item.id) for item in selected]})
        return selected

    def _build_bundle(self, run: AgentRun, user: User) -> AnalysisBundle:
        self._require_tool_budget(run)
        bundle = AnalysisPipelineService(self.uow).build_analysis_for_asset(str(run.asset_id), user=user)
        if bundle.snapshot.as_of and bundle.snapshot.as_of > run.as_of:
            raise AgentExecutionError("Analysis snapshot contains facts newer than Agent run as_of")
        run.research_run_id = bundle.run.id
        run.updated_at = utc_now()
        self.runtime.update_run(run)
        self.runtime.add_tool_call(run.id, "structured_feature_build", "build_29_features", {"asset_id": str(run.asset_id)}, {"research_run_id": str(bundle.run.id)})
        return bundle

    def _model_result(self, run: AgentRun, bundle: object) -> dict[str, object]:
        assert isinstance(bundle, AnalysisBundle)
        prediction = bundle.predictions[0] if bundle.predictions else None
        result = {
            "available": bool(prediction and prediction.risk_probability is not None),
            "risk_probability": None if prediction is None else prediction.risk_probability,
            "model": None if prediction is None else f"{prediction.model_name}@{prediction.model_version}",
            "approved": bool(prediction and prediction.deployment_approved),
            "feature_coverage": 0.0 if prediction is None else prediction.feature_coverage,
        }
        self._record_tool(run, "model_inference", "approved_model_inference", {"research_run_id": str(bundle.run.id)}, result)
        comparison = DeploymentModelInferenceService().predict_comparison(bundle.snapshot)
        feature_vector = DeploymentModelInferenceService().snapshot_feature_vector(bundle.snapshot)
        provider_missing_rate = 1.0 if bundle.snapshot.fallback_reasons else 0.0
        for role, probability in comparison.items():
            self.runtime.add_paper_prediction(
                owner_user_id=run.owner_user_id,
                asset_id=run.asset_id,
                research_run_id=bundle.run.id,
                model_role=role,
                model_id=str(result["model"] if role == "primary" else role),
                as_of=bundle.snapshot.as_of or bundle.snapshot.captured_at,
                risk_probability=probability,
                feature_coverage=float(result["feature_coverage"]),
                abstained=probability is None,
                feature_values=feature_vector.values,
                provider_missing_rate=provider_missing_rate,
            )
        result["paper_comparison"] = comparison
        return result

    def _counter_evidence(self, run: AgentRun, context: dict[str, object]) -> CounterEvidenceQuery:
        evidence_ids = [str(item.id) for item in context["evidence"]]  # type: ignore[union-attr]
        query = self._llm_or_default(
            run, "counter_evidence_search", CounterEvidenceQuery,
            {"model_result": context["prediction"], "evidence_ids": evidence_ids},
            CounterEvidenceQuery(query_terms=["risk", "regulatory", "guidance cut"], challenged_claim="Review contrary evidence", evidence_ids=evidence_ids),
            400,
        )
        self._record_tool(run, "counter_evidence_search", "collect_pit_evidence", {"query_terms": query.query_terms}, {"bounded": True, "new_evidence": 0})
        return query

    def _audit(self, run: AgentRun, user: User, context: dict[str, object]) -> dict[str, object]:
        if run.research_run_id is None:
            raise AgentExecutionError("Research run is missing")
        audit = ResearchAuditService(self.uow).audit(str(run.research_run_id), user=user)
        evidence_ids = [str(item.id) for item in context["evidence"]]  # type: ignore[union-attr]
        citation = self._llm_or_default(
            run, "self_audit", CitationAudit,
            {"deterministic_verdict": audit.verdict.value, "checks": audit.checks, "evidence_ids": evidence_ids},
            CitationAudit(supported=bool(evidence_ids), unsupported_claims=[] if evidence_ids else ["No evidence available"], evidence_ids=evidence_ids),
            600,
        )
        verdict = audit.verdict.value
        if not citation.supported and verdict not in {"block", "hold"}:
            verdict = "hold"
        self._record_tool(run, "self_audit", "quality_gate", {"research_run_id": str(run.research_run_id)}, {"verdict": verdict})
        return {
            "verdict": verdict,
            "deterministic_verdict": audit.verdict.value,
            "audit_id": str(audit.id),
            "citation": citation.model_dump(mode="json"),
        }

    def _repair_or_abstain(self, run: AgentRun, context: dict[str, object]) -> dict[str, object]:
        audit = context["audit"]
        verdict = audit["verdict"]  # type: ignore[index]
        deterministic_verdict = audit["deterministic_verdict"]  # type: ignore[index]
        citation = CitationAudit.model_validate(audit["citation"])  # type: ignore[index]
        if (
            verdict == "hold"
            and deterministic_verdict not in {"hold", "block"}
            and not citation.supported
            and run.budget.repair_count < run.budget.max_repair_count
        ):
            run.state = AgentRunState.REPAIRING
            run.budget.repair_count += 1
            run.updated_at = utc_now()
            self.runtime.update_run(run)
            self.runtime.add_event(
                run.id,
                "run.repair_started",
                node_name="repair_or_abstain",
                payload={"scope": "proposed_claim_citations"},
            )
            evidence_ids = [str(item.id) for item in context["evidence"]]  # type: ignore[union-attr]
            repaired = self._llm_or_default(
                run,
                "repair_or_abstain",
                CitationAudit,
                {
                    "instruction": "Repair citation bindings only. Do not alter facts, probabilities, or gate results.",
                    "unsupported_claims": citation.unsupported_claims,
                    "evidence_ids": evidence_ids,
                },
                CitationAudit(
                    supported=bool(evidence_ids),
                    unsupported_claims=[] if evidence_ids else citation.unsupported_claims,
                    evidence_ids=evidence_ids,
                ),
                800,
            )
            if repaired.supported:
                audit["citation"] = repaired.model_dump(mode="json")  # type: ignore[index]
                audit["verdict"] = deterministic_verdict  # type: ignore[index]
                self.runtime.add_event(
                    run.id,
                    "run.repair_completed",
                    node_name="repair_or_abstain",
                    payload={"verdict": deterministic_verdict},
                )
                return {"abstain": False, "verdict": deterministic_verdict, "reason": None, "repaired": True}
            self.runtime.add_event(
                run.id,
                "run.repair_failed",
                node_name="repair_or_abstain",
                payload={"reason": "Citation support remains incomplete"},
            )
        if verdict in {"hold", "block"}:
            return {"abstain": True, "verdict": verdict, "reason": "Quality gate could not establish a supported, current conclusion"}
        return {"abstain": False, "verdict": verdict, "reason": None}

    def _report(self, run: AgentRun, context: dict[str, object]):
        bundle = context["bundle"]
        assert isinstance(bundle, AnalysisBundle)
        report = ReportService(self.uow).create_report_from_bundle(bundle, report_version="agent-1.0.0")
        evidence_ids = [str(item.id) for item in bundle.evidence]
        narrative = self._llm_or_default(
            run, "report_generation", ReportNarrative,
            {"report_skeleton": {"title": report.title, "thesis": report.thesis}, "evidence_ids": evidence_ids},
            ReportNarrative(
                summary="Deterministic risk report generated from a fixed point-in-time run.",
                supporting_view="Approved model and cited evidence define the risk observation.",
                contrary_view="Stale, conflicting, or incomplete evidence limits the conclusion.",
                observation_conditions=["Refresh after material disclosures", "Abstain below the feature coverage gate"],
                evidence_ids=evidence_ids,
            ),
            1200,
        )
        if narrative.contains_trade_instruction or set(narrative.evidence_ids) - set(UUID(item) for item in evidence_ids):
            self.runtime.add_event(run.id, "llm.output_rejected", node_name="report_generation", payload={"reason": "unsafe_or_invalid_citation"})
        return report

    def _llm_or_default(self, run: AgentRun, node_name: str, response_model: type[T], payload: dict[str, object], default: T, max_output_tokens: int) -> T:
        if run.budget.llm_calls_used >= run.budget.max_llm_calls or run.budget.output_tokens_used >= run.budget.max_output_tokens:
            self.runtime.add_event(run.id, "llm.budget_exhausted", node_name=node_name)
            return default
        estimated_input = len(str(payload)) // 3
        if run.budget.input_tokens_used + estimated_input > run.budget.max_input_tokens:
            self.runtime.add_event(run.id, "llm.input_budget_exhausted", node_name=node_name)
            return default
        profile = self._profile(run)
        request = LLMRequest[T](
            node_name=node_name,
            system_prompt="Return only schema-valid JSON. Cite only supplied evidence IDs. Never provide trade instructions.",
            user_payload=payload,
            response_schema=response_model.model_json_schema(),
            response_model_name=response_model.__name__,
            max_output_tokens=min(max_output_tokens, run.budget.max_output_tokens - run.budget.output_tokens_used),
            evidence_ids=[str(item) for item in payload.get("evidence_ids", [])],
        )
        cache_key = stable_hash({"provider": profile.protocol, "model": profile.model, "prompt": request.prompt_version, "schema": request.response_schema, "snapshot": str(run.research_run_id or run.id), "payload": payload})
        cached = self.runtime.get_cache(cache_key)
        if cached is not None:
            output = response_model.model_validate(cached)
            self._record_llm(run, request, profile, None, cache_hit=True, state="completed")
            return output
        try:
            api_key = None
            if profile.credential_ref:
                if self.credential_vault is None:
                    self.credential_vault = CredentialVault()
                api_key = self.credential_vault.get_secret(profile.credential_ref)
            response = build_llm_provider(profile, api_key).generate_structured(request, response_model)
            supplied = {str(item) for item in request.evidence_ids}
            returned = {str(item) for item in getattr(response.output, "evidence_ids", [])}
            if returned - supplied:
                raise LLMProviderError("Provider returned unknown evidence IDs")
            self.runtime.put_cache(cache_key, response.output.model_dump(mode="json"))
            self._record_llm(run, request, profile, response, cache_hit=False, state="completed")
            return response.output
        except (LLMProviderError, CredentialVaultError, ValueError) as exc:
            self._record_llm(run, request, profile, None, cache_hit=False, state="failed", error=f"{type(exc).__name__}: {exc}")
            self.runtime.add_event(run.id, "llm.degraded", node_name=node_name, payload={"reason": type(exc).__name__})
            fallback = None
            if profile.fallback_profile_id and run.budget.llm_calls_used < run.budget.max_llm_calls:
                fallback = self.runtime.get_profile(str(profile.fallback_profile_id), run.owner_user_id)
            if fallback and fallback.enabled:
                try:
                    fallback_key = None
                    if fallback.credential_ref:
                        if self.credential_vault is None:
                            self.credential_vault = CredentialVault()
                        fallback_key = self.credential_vault.get_secret(fallback.credential_ref)
                    response = build_llm_provider(fallback, fallback_key).generate_structured(request, response_model)
                    supplied = {str(item) for item in request.evidence_ids}
                    returned = {str(item) for item in getattr(response.output, "evidence_ids", [])}
                    if returned - supplied:
                        raise LLMProviderError("Fallback returned unknown evidence IDs")
                    self._record_llm(run, request, fallback, response, cache_hit=False, state="completed")
                    self.runtime.add_event(run.id, "llm.fallback_succeeded", node_name=node_name, payload={"profile_id": str(fallback.id)})
                    return response.output
                except (LLMProviderError, CredentialVaultError, ValueError) as fallback_exc:
                    self._record_llm(run, request, fallback, None, cache_hit=False, state="failed", error=f"{type(fallback_exc).__name__}: {fallback_exc}")
            return default

    def _record_llm(self, run: AgentRun, request: LLMRequest[T], profile: ProviderProfile, response: LLMResponse[T] | None, *, cache_hit: bool, state: str, error: str | None = None) -> None:
        input_tokens = 0 if response is None else response.input_tokens
        output_tokens = 0 if response is None else response.output_tokens
        run.budget.llm_calls_used += 1
        run.budget.input_tokens_used += input_tokens
        run.budget.output_tokens_used += output_tokens
        run.updated_at = utc_now()
        self.runtime.update_run(run)
        self.runtime.add_llm_call(
            run_id=run.id, node_name=request.node_name, protocol=profile.protocol, model=profile.model,
            prompt_version=request.prompt_version, schema_version=request.schema_version,
            request_hash=stable_hash(request.model_dump(mode="json")), evidence_hash=stable_hash(request.evidence_ids),
            input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=0 if response is None else response.latency_ms,
            cache_hit=cache_hit, state=state, error=error,
        )

    def _profile(self, run: AgentRun) -> ProviderProfile:
        if run.provider_profile_id:
            profile = self.runtime.get_profile(str(run.provider_profile_id), run.owner_user_id)
            if profile and profile.enabled:
                return profile
        return ProviderProfile(owner_user_id=run.owner_user_id, name="deterministic-mock", protocol="mock", model="mock-evidence-organizer-v1")

    def _record_tool(self, run: AgentRun, node_name: str, tool_id: str, input_value: object, output: object) -> None:
        self._require_tool_budget(run)
        self.runtime.add_tool_call(run.id, node_name, tool_id, input_value, output)

    def _require_tool_budget(self, run: AgentRun) -> None:
        if run.budget.tool_calls_used >= run.budget.max_tool_calls:
            raise AgentExecutionError("Agent tool-call budget exhausted")
        run.budget.tool_calls_used += 1
        run.updated_at = utc_now()
        self.runtime.update_run(run)

    def _save(self, run: AgentRun, **changes) -> AgentRun:
        updated = run.model_copy(update={**changes, "updated_at": utc_now()})
        return self.runtime.update_run(updated)

    @staticmethod
    def _dump(value: object) -> object:
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value
