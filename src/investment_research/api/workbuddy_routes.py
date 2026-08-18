"""MCP and REST boundary for Tencent WorkBuddy and other compatible clients."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from investment_research.api.auth_routes import get_authenticated_user
from investment_research.api.routes import get_unit_of_work
from investment_research.domain.models import User
from investment_research.domain.workbuddy import WorkBuddyConnection, WorkBuddyConnectionIssued, WorkBuddyScope
from investment_research.public_demo import require_private_research_workspace
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.workbuddy import WORKBUDDY_TOOLS, WorkBuddyReadService


router = APIRouter(prefix="/api/v1/workbuddy", tags=["workbuddy-mcp"])


class WorkBuddyConnectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[WorkBuddyScope] = Field(default_factory=lambda: ["research.read", "knowledge.read", "shadow.read", "lifecycle.read"])


def _bearer_token(value: str | None) -> str:
    if not value or not value.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="workbuddy_bearer_token_required")
    token = value[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="workbuddy_bearer_token_required")
    return token


def _connection(authorization: str | None, uow: SQLiteUnitOfWork) -> WorkBuddyConnection:
    item = uow.workbuddy_connections.authenticate(_bearer_token(authorization))
    if item is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="workbuddy_connection_invalid_or_revoked")
    return item


@router.get("/connections", response_model=list[WorkBuddyConnection])
def list_connections(uow: SQLiteUnitOfWork = Depends(get_unit_of_work), user: User = Depends(get_authenticated_user)) -> list[WorkBuddyConnection]:
    require_private_research_workspace()
    return uow.workbuddy_connections.list_for_owner(user.id)


@router.post("/connections", response_model=WorkBuddyConnectionIssued, status_code=status.HTTP_201_CREATED)
def create_connection(payload: WorkBuddyConnectionCreateRequest, uow: SQLiteUnitOfWork = Depends(get_unit_of_work), user: User = Depends(get_authenticated_user)) -> WorkBuddyConnectionIssued:
    require_private_research_workspace()
    return uow.workbuddy_connections.issue(owner_user_id=user.id, name=payload.name, scopes=list(payload.scopes))


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_connection(connection_id: str, uow: SQLiteUnitOfWork = Depends(get_unit_of_work), user: User = Depends(get_authenticated_user)) -> None:
    require_private_research_workspace()
    if not uow.workbuddy_connections.revoke(connection_id, owner_user_id=user.id):
        raise HTTPException(status_code=404, detail="workbuddy_connection_not_found")


@router.get("/openapi.json")
def workbuddy_openapi() -> dict[str, Any]:
    """A small stable contract for connector configuration and inspection."""
    return {
        "openapi": "3.1.0", "info": {"title": "A-share Research WorkBuddy Connector", "version": "1.0.0"},
        "paths": {
            "/api/v1/workbuddy/mcp": {"post": {"summary": "MCP Streamable HTTP endpoint", "security": [{"bearerAuth": []}]}},
            "/api/v1/workbuddy/tools": {"get": {"summary": "List read-only research tools", "security": [{"bearerAuth": []}]}},
        },
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    }


@router.get("/tools")
def list_tools(authorization: str | None = Header(default=None), uow: SQLiteUnitOfWork = Depends(get_unit_of_work)) -> dict[str, Any]:
    connection = _connection(authorization, uow)
    allowed = [item for item in WORKBUDDY_TOOLS if item["scope"] in set(connection.scopes)]
    return {"tools": allowed, "data_tier": "research_pit", "read_only": True}


@router.post("/mcp")
async def mcp(request: Request, authorization: str | None = Header(default=None), uow: SQLiteUnitOfWork = Depends(get_unit_of_work)) -> JSONResponse:
    """Minimal Streamable-HTTP MCP JSON-RPC endpoint.

    WorkBuddy can register this URL directly.  Methods are deliberately limited
    to initialize/tools-list/tools-call; resources, prompts, sampling and
    server-initiated writes are not exposed.
    """
    connection = _connection(authorization, uow)
    try:
        payload = await request.json()
    except Exception as exc:
        return _mcp_error(None, -32700, f"parse_error:{type(exc).__name__}")
    request_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str):
        return _mcp_error(request_id, -32600, "invalid_request")
    method = payload["method"]
    if method == "initialize":
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "a-share-research", "version": "1.0.0"}, "instructions": "Read-only A-share research tools. Results are research-only and never trading instructions."}})
    if method == "notifications/initialized":
        return JSONResponse(status_code=202, content={})
    if method == "tools/list":
        allowed = [{key: value for key, value in item.items() if key != "scope"} for item in WORKBUDDY_TOOLS if item["scope"] in set(connection.scopes)]
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"tools": allowed}})
    if method == "tools/call":
        params = payload.get("params") or {}
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _mcp_error(request_id, -32602, "tool_name_required")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _mcp_error(request_id, -32602, "tool_arguments_must_be_object")
        try:
            result = WorkBuddyReadService(uow).call(params["name"], arguments, scopes=set(connection.scopes))
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "structuredContent": result, "isError": False}})
        except PermissionError as exc:
            return _mcp_error(request_id, -32001, str(exc))
        except ValueError as exc:
            return _mcp_error(request_id, -32602, str(exc))
        except Exception as exc:
            return _mcp_error(request_id, -32000, f"research_tool_failed:{type(exc).__name__}")
    return _mcp_error(request_id, -32601, "method_not_found")


def _mcp_error(request_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})
