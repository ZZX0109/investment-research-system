from __future__ import annotations

import json
import hashlib
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from investment_research.agent.models import AgentRun, AgentToolCall, ProviderProfile
from investment_research.agent.service import AGENT_TOOLS, FUNCTION_CALL_TOOLS, AgentOrchestrator
from investment_research.api.agent_schemas import AgentRunCreateRequest, ProviderProfileCreateRequest, ProviderProfilePatchRequest
from investment_research.api.credential_schemas import CredentialSummaryResponse, CredentialUpsertRequest
from investment_research.api.auth_routes import get_authenticated_user
from investment_research.api.routes import get_unit_of_work
from investment_research.domain.base import utc_now
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.research_findings import ResearchFindingsService
from investment_research.service.credential_vault import CredentialVault, CredentialVaultError
from investment_research.domain.knowledge import FinancialKnowledgeDocument, KnowledgeSearchResult
from investment_research.public_demo import require_private_research_workspace


router = APIRouter(prefix="/api/v1", tags=["evidence-bound-agent"])


@router.get("/llm-credentials", response_model=list[CredentialSummaryResponse])
def list_llm_credentials(user: User = Depends(get_authenticated_user)) -> list[CredentialSummaryResponse]:
    """List masked LLM credentials for the signed-in research workspace."""
    del user
    require_private_research_workspace()
    try:
        return CredentialVault().list_credentials()
    except CredentialVaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/llm-credentials", response_model=CredentialSummaryResponse, status_code=status.HTTP_201_CREATED)
def upsert_llm_credential(
    payload: CredentialUpsertRequest,
    user: User = Depends(get_authenticated_user),
) -> CredentialSummaryResponse:
    """Store an API key in the encrypted local vault; the secret is never returned."""
    del user
    require_private_research_workspace()
    try:
        return CredentialVault().upsert_credential(payload)
    except CredentialVaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_agent_service(uow: SQLiteUnitOfWork = Depends(get_unit_of_work)) -> AgentOrchestrator:
    return AgentOrchestrator(uow)


@router.post("/agent-runs", response_model=AgentRun, status_code=status.HTTP_201_CREATED)
def create_agent_run(
    payload: AgentRunCreateRequest,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> AgentRun:
    require_private_research_workspace()
    try:
        return service.create_and_execute(
            user=user,
            asset_id=payload.asset_id,
            task_text=payload.task_text,
            as_of=payload.as_of,
            provider_profile_id=payload.provider_profile_id,
            user_preference=payload.user_preference,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agent-runs/{run_id}", response_model=AgentRun)
def get_agent_run(
    run_id: str,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> AgentRun:
    try:
        return service.get(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agent-runs/{run_id}/events")
def stream_agent_events(
    run_id: str,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> StreamingResponse:
    try:
        run = service.get(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def generate():
        for event in service.runtime.list_events(str(run.id)):
            yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/agent-runs/{run_id}/tool-calls", response_model=list[AgentToolCall])
def list_agent_tool_calls(
    run_id: str,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> list[AgentToolCall]:
    """Expose a hashed, user-scoped execution trace without exposing secrets."""
    service.get(run_id, user=user)
    return service.runtime.list_tool_calls(run_id)


@router.get("/agent-runs/{run_id}/explanation")
def get_agent_explanation(
    run_id: str,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    """Return the safe, evidence-bound explanation produced for a completed run."""
    service.get(run_id, user=user)
    for event in reversed(service.runtime.list_events(run_id)):
        if event.event_type == "llm.research_explanation":
            return dict(event.payload)
    raise HTTPException(status_code=404, detail="Research explanation is not available for this run")


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRun)
def cancel_agent_run(
    run_id: str,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> AgentRun:
    try:
        return service.cancel(run_id, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/agent-runs/{run_id}/resume", response_model=AgentRun)
def resume_agent_run(
    run_id: str,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> AgentRun:
    current = service.get(run_id, user=user)
    if current.state.value != "failed":
        raise HTTPException(status_code=409, detail="Only failed Agent runs can be resumed")
    return service.execute(run_id, user=user)


@router.get("/agent-tools")
def list_agent_tools(user: User = Depends(get_authenticated_user)) -> list[dict[str, str]]:
    del user
    return [{"id": tool_id, "description": description} for tool_id, description in AGENT_TOOLS.items()]


@router.get("/agent-function-tools")
def list_agent_function_tools(user: User = Depends(get_authenticated_user)) -> list[dict[str, object]]:
    """Return the only functions a user-configured LLM may call."""
    del user
    return [tool.model_dump(mode="json") for tool in FUNCTION_CALL_TOOLS]


@router.get("/financial-knowledge", response_model=list[FinancialKnowledgeDocument])
def list_financial_knowledge(
    market: str = Query(default="CN"),
    symbol: str | None = Query(default=None),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[FinancialKnowledgeDocument]:
    del user
    return uow.financial_knowledge.list(market=market.upper(), symbol=symbol)


@router.get("/financial-knowledge/search", response_model=list[KnowledgeSearchResult])
def search_financial_knowledge(
    q: str = Query(min_length=2, max_length=500),
    as_of: datetime = Query(),
    market: str = Query(default="CN"),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=6, ge=1, le=20),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[KnowledgeSearchResult]:
    del user
    return uow.financial_knowledge.search(q, as_of=as_of, market=market.upper(), symbol=symbol, limit=limit)


@router.post("/financial-knowledge", response_model=FinancialKnowledgeDocument, status_code=status.HTTP_201_CREATED)
def create_financial_knowledge(
    document: FinancialKnowledgeDocument,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> FinancialKnowledgeDocument:
    del user
    if document.data_tier != "research_pit":
        raise HTTPException(
            status_code=400,
            detail="Public knowledge ingestion is research_pit only; formal_pit requires a separately authorized pipeline",
        )
    expected_hash = hashlib.sha256(
        f"{document.title}|{document.content}|{document.source_url}".encode()
    ).hexdigest()
    if document.content_hash != expected_hash:
        raise HTTPException(status_code=400, detail="content_hash does not match title/content/source_url")
    if document.available_at < document.published_at:
        raise HTTPException(status_code=400, detail="available_at cannot precede published_at")
    return uow.financial_knowledge.add(document)


@router.get("/llm-provider-profiles", response_model=list[ProviderProfile])
def list_provider_profiles(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[ProviderProfile]:
    return uow.agent_runtime.list_profiles(user.id)


@router.post("/llm-provider-profiles", response_model=ProviderProfile, status_code=status.HTTP_201_CREATED)
def create_provider_profile(
    payload: ProviderProfileCreateRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ProviderProfile:
    require_private_research_workspace()
    profile = ProviderProfile(owner_user_id=user.id, **payload.model_dump())
    return uow.agent_runtime.add_profile(profile)


@router.patch("/llm-provider-profiles/{profile_id}", response_model=ProviderProfile)
def patch_provider_profile(
    profile_id: str,
    payload: ProviderProfilePatchRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ProviderProfile:
    require_private_research_workspace()
    profile = uow.agent_runtime.get_profile(profile_id, user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Provider profile not found")
    updates = payload.model_dump(exclude_unset=True)
    if "fallback_profile_id" in updates and updates["fallback_profile_id"] is not None:
        updates["fallback_profile_id"] = UUID(updates["fallback_profile_id"])
    updated = profile.model_copy(update={**updates, "updated_at": utc_now()})
    return uow.agent_runtime.update_profile(updated)


@router.delete("/llm-provider-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_profile(
    profile_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> Response:
    require_private_research_workspace()
    if not uow.agent_runtime.delete_profile(profile_id, user.id):
        raise HTTPException(status_code=404, detail="Provider profile not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/paper-validation/summary")
def paper_validation_summary(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    return ResearchFindingsService(uow).paper_summary(user.id)


@router.get("/models/research-findings")
def model_research_findings(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    del user
    return ResearchFindingsService(uow).model_findings()


@router.get("/documents/{document_id}/evaluation")
def get_document_evaluation(
    document_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    evaluation = uow.document_evaluations.get(document_id, user.id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Document evaluation not found")
    return evaluation
