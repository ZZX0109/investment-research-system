from __future__ import annotations

import json
import hashlib
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from investment_research.agent.models import AgentRun, AgentToolCall, ProviderProfile
from investment_research.agent.service import AGENT_TOOLS, FUNCTION_CALL_TOOLS, PUBLIC_FUNCTION_CALL_TOOL_NAMES, AgentOrchestrator
from investment_research.api.agent_schemas import (
    AgentRunCreateRequest,
    ConversationCreateRequest,
    ConversationMessageCreateRequest,
    ProviderProfileCreateRequest,
    ProviderProfilePatchRequest,
)
from investment_research.api.credential_schemas import CredentialSummaryResponse, CredentialUpsertRequest
from investment_research.api.auth_routes import get_authenticated_user
from investment_research.api.routes import get_unit_of_work
from investment_research.domain.base import utc_now
from investment_research.domain.conversation import ConversationMessage, ConversationSession
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.conversation_agent import ConversationAgentService
from investment_research.service.dashboard_read import DashboardReadService
from investment_research.service.research_findings import ResearchFindingsService
from investment_research.service.credential_vault import CredentialVault, CredentialVaultError
from investment_research.service.financial_knowledge import FinancialKnowledgeService
from investment_research.domain.knowledge import FinancialKnowledgeDocument, KnowledgeSearchResult
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService, LocalBGEEmbedder
from investment_research.service.documents import DocumentService
from investment_research.service.ingestion_jobs import IngestionJobService
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
    return [
        tool.model_dump(mode="json")
        for tool in FUNCTION_CALL_TOOLS
        if tool.name in PUBLIC_FUNCTION_CALL_TOOL_NAMES
    ]


@router.get("/financial-knowledge", response_model=list[FinancialKnowledgeDocument])
def list_financial_knowledge(
    market: str = Query(default="CN"),
    symbol: str | None = Query(default=None),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[FinancialKnowledgeDocument]:
    return uow.financial_knowledge.list(market=market.upper(), symbol=symbol, owner_user_id=user.id)


@router.get("/financial-knowledge/search", response_model=list[KnowledgeSearchResult])
def search_financial_knowledge(
    q: str = Query(min_length=2, max_length=500),
    as_of: datetime = Query(),
    market: str = Query(default="CN"),
    symbol: str | None = Query(default=None),
    document_type: str | None = Query(default=None),
    source: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=6, ge=1, le=20),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[KnowledgeSearchResult]:
    results, _ = KnowledgeRetrievalService(uow).search(
        q, as_of=as_of, market=market.upper(), symbol=symbol,
        owner_user_id=user.id, document_type=document_type, source=source,
        limit=limit, offset=offset,
    )
    return results


@router.get("/financial-knowledge/coverage")
def financial_knowledge_coverage(
    market: str = Query(default="CN"),
    symbol: str | None = Query(default=None),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    del user
    records = uow.financial_knowledge.latest_coverage(market=market.upper(), symbol=symbol)
    embedder = LocalBGEEmbedder()
    embedding_status = embedder.status
    metadata_target = sum(item.target_count for item in records)
    metadata_count = sum(item.metadata_count for item in records)
    full_text_count = sum(item.full_text_count for item in records)
    return {
        "market": market.upper(), "symbol": symbol,
        "metadata_target": metadata_target, "metadata_count": metadata_count,
        "metadata_coverage_ratio": 0.0 if metadata_target == 0 else metadata_count / metadata_target,
        "full_text_count": full_text_count,
        "semantic_search_available": bool(embedding_status["available"]),
        "semantic_search_installed": bool(embedding_status["installed"]),
        "semantic_search_model": embedder.model_name,
        "semantic_search_reason": embedding_status["reason"],
        "records": [item.model_dump(mode="json") for item in records],
        "data_tier": "research_pit", "deployment_ready": False,
    }


@router.get("/financial-knowledge/user-uploads")
def list_financial_knowledge_uploads(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[FinancialKnowledgeDocument]:
    return [
        item for item in uow.financial_knowledge.list(owner_user_id=user.id)
        if item.source_kind == "user_upload" and item.owner_user_id == user.id
    ]


@router.get("/financial-knowledge/{document_id}")
def get_financial_knowledge_document(
    document_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    document = uow.financial_knowledge.get(document_id, owner_user_id=user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    chunks = uow.financial_knowledge.chunks_for_document(document_id, owner_user_id=user.id)
    revisions = uow.financial_knowledge.revision_timeline(document_id, owner_user_id=user.id)
    return {
        "document": document.model_dump(mode="json"),
        "chunks": [item.model_dump(mode="json") for item in chunks],
        "revisions": [item.model_dump(mode="json") for item in revisions],
    }


@router.post("/financial-knowledge/{document_id}/request-full-text", status_code=status.HTTP_202_ACCEPTED)
def request_financial_knowledge_full_text(
    document_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
):
    document = uow.financial_knowledge.get(document_id, owner_user_id=user.id)
    if document is None or document.source_kind != "official_public" or not document.source_url:
        raise HTTPException(status_code=404, detail="Official knowledge document not found")
    now = utc_now()
    return IngestionJobService(uow, clock=lambda: now).enqueue(
        job_type="knowledge_document_fetch", symbols=[document_id], requested_by=str(user.id),
        idempotency_key=f"knowledge:full-text:{document_id}:{document.content_hash}",
        market="cn", decision_context="close_confirmed", trade_date=now.date(),
        cutoff_time=now, data_tier="research_pit",
    )


@router.post("/financial-knowledge/uploads", status_code=status.HTTP_201_CREATED)
async def upload_financial_knowledge(
    file: UploadFile = File(...),
    asset_id: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> FinancialKnowledgeDocument:
    data = await file.read()
    documents = DocumentService(uow)
    artifact = None
    try:
        artifact = documents.create(
            user=user, filename=file.filename or "research-document.txt",
            content_type=file.content_type or "application/octet-stream",
            data=data, asset_id=asset_id, source_url=source_url,
        )
        return FinancialKnowledgeService(uow).ingest_user_artifact(artifact, user=user)
    except ValueError as exc:
        if artifact is not None:
            documents.delete_for_user(str(artifact.id), user=user)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/financial-knowledge/uploads/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financial_knowledge_upload(
    document_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> Response:
    document = uow.financial_knowledge.get(document_id, owner_user_id=user.id)
    if document is None or document.source_kind != "user_upload" or not document.raw_payload_ref:
        raise HTTPException(status_code=404, detail="Private knowledge document not found")
    artifact = next(
        (item for item in DocumentService(uow).list_for_user(user=user) if item.storage_path == document.raw_payload_ref),
        None,
    )
    if artifact is not None:
        DocumentService(uow).delete_for_user(str(artifact.id), user=user)
    if not uow.financial_knowledge.delete_private_document(document_id, owner_user_id=user.id):
        raise HTTPException(status_code=404, detail="Private knowledge document not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/financial-knowledge/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh_financial_knowledge(
    mode: str = Query(default="incremental", pattern="^(incremental|backfill|reindex|audit)$"),
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
):
    job_type = {
        "incremental": "knowledge_daily_incremental", "backfill": "knowledge_historical_backfill",
        "reindex": "knowledge_monthly_reindex", "audit": "knowledge_weekly_audit",
    }[mode]
    now = utc_now()
    return IngestionJobService(uow, clock=lambda: now).enqueue(
        job_type=job_type, symbols=[], requested_by=str(user.id),
        idempotency_key=f"knowledge:{mode}:{now.date().isoformat()}",
        market="cn", decision_context="close_confirmed", trade_date=now.date(),
        cutoff_time=now, data_tier="research_pit",
    )


@router.post("/financial-knowledge", response_model=FinancialKnowledgeDocument, status_code=status.HTTP_201_CREATED)
def create_financial_knowledge(
    document: FinancialKnowledgeDocument,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> FinancialKnowledgeDocument:
    try:
        if document.source_kind != "user_upload":
            raise ValueError("manual knowledge creation is limited to private user-owned material")
        secured = document.model_copy(update={
            "owner_user_id": user.id, "access_scope": "private",
            "copyright_status": "user_owned", "data_tier": "research_pit",
            "content_hash": FinancialKnowledgeService.content_hash(
                title=document.title, content=document.content,
                source_url=document.source_url, owner_user_id=user.id,
            ),
        })
        return FinancialKnowledgeService(uow).ingest(secured)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


# ---------------------------------------------------------------------------
# Multi-turn conversations (Phase 3) — the AI left panel's memory layer.
# A conversation pins one asset + one as_of and accumulates turns so the
# agent can reference the previous round ("展开刚才...").  Each user message
# triggers an AgentRun bound to the conversation; the run's plain answer is
# persisted as an assistant message, with the snapshot as_of recorded so a
# later phase can rebuild the exact snapshot the AI saw.
# ---------------------------------------------------------------------------
@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    require_private_research_workspace()
    if uow.assets.get(payload.asset_id) is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    session = ConversationSession(
        user_id=user.id,
        asset_id=UUID(payload.asset_id),
        as_of=payload.as_of,
        title=payload.title,
    )
    uow.conversations.add_session(session)
    return _conversation_response(uow.conversations.get_session(str(session.id), owner_user_id=user.id))


@router.get("/conversations")
def list_conversations(
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> list[dict[str, object]]:
    require_private_research_workspace()
    return [
        _conversation_response(session)
        for session in uow.conversations.list_sessions_for_user(user.id)
    ]


@router.get("/conversations/{session_id}")
def get_conversation(
    session_id: str,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    require_private_research_workspace()
    session = uow.conversations.get_session(session_id, owner_user_id=user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _conversation_response(session)


@router.post("/conversations/{session_id}/messages", status_code=status.HTTP_201_CREATED)
def post_conversation_message(
    session_id: str,
    payload: ConversationMessageCreateRequest,
    uow: SQLiteUnitOfWork = Depends(get_unit_of_work),
    service: AgentOrchestrator = Depends(get_agent_service),
    user: User = Depends(get_authenticated_user),
) -> dict[str, object]:
    """Append a user question, run the agent with conversation memory, and
    persist the assistant's answer as the next message."""
    require_private_research_workspace()
    session = uow.conversations.get_session(session_id, owner_user_id=user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Phase 4 (A3): the multi-turn + snapshot-pinned flow now lives in
    # ConversationAgentService (split out of the route / orchestrator
    # god-class). The single-turn path is untouched. The route is now a thin
    # scheduler: validate session → ConversationAgentService.answer → respond.
    conversation_agent = ConversationAgentService(
        uow,
        dashboard=DashboardReadService(uow, project_root=service.project_root),
        orchestrator=service,
    )
    try:
        run, refreshed = conversation_agent.answer(
            session_id=str(session.id),
            content=payload.content,
            provider_profile_id=payload.provider_profile_id,
            user_preference=payload.user_preference,
            user=user,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "run_id": str(run.id),
        "run_state": run.state.value,
        "conversation": _conversation_response(refreshed),
    }


def _conversation_response(session: object | None) -> dict[str, object]:
    if session is None:
        return {}
    messages = []
    for message in getattr(session, "messages", []):
        messages.append(
            {
                "id": str(message.id),
                "session_id": str(message.session_id),
                "sequence": message.sequence,
                "role": message.role,
                "content": message.content,
                "agent_run_id": None if message.agent_run_id is None else str(message.agent_run_id),
                "snapshot_as_of": message.snapshot_as_of,
                "created_at": message.created_at.isoformat(),
            }
        )
    return {
        "id": str(session.id),
        "user_id": str(session.user_id),
        "asset_id": str(session.asset_id),
        "as_of": session.as_of.isoformat(),
        "title": session.title,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "messages": messages,
    }
