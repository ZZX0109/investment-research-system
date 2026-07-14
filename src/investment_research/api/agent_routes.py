from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from investment_research.agent.models import AgentRun, ProviderProfile
from investment_research.agent.service import AGENT_TOOLS, AgentOrchestrator
from investment_research.api.agent_schemas import AgentRunCreateRequest, ProviderProfileCreateRequest, ProviderProfilePatchRequest
from investment_research.api.auth_routes import get_authenticated_user
from investment_research.api.routes import get_unit_of_work
from investment_research.domain.base import utc_now
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.research_findings import ResearchFindingsService


router = APIRouter(prefix="/api/v1", tags=["evidence-bound-agent"])


def get_agent_service(uow: SQLiteUnitOfWork = Depends(get_unit_of_work)) -> AgentOrchestrator:
    return AgentOrchestrator(uow)


@router.post("/agent-runs", response_model=AgentRun, status_code=status.HTTP_201_CREATED)
def create_agent_run(
    payload: AgentRunCreateRequest,
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> AgentRun:
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
    profile = ProviderProfile(owner_user_id=user.id, **payload.model_dump())
    return uow.agent_runtime.add_profile(profile)


@router.patch("/llm-provider-profiles/{profile_id}", response_model=ProviderProfile)
def patch_provider_profile(
    profile_id: str,
    payload: ProviderProfilePatchRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> ProviderProfile:
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
