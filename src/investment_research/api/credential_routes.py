from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from investment_research.api.artifact_security import require_agent_api_access
from investment_research.api.credential_schemas import (
    CredentialSummaryResponse,
    CredentialUpsertRequest,
)
from investment_research.service.credential_vault import CredentialVault, CredentialVaultError

router = APIRouter(prefix="/api/v1/test-officer/credentials", tags=["test-officer-credentials"])


def get_credential_vault() -> CredentialVault:
    return CredentialVault()


@router.get("", response_model=list[CredentialSummaryResponse])
def list_credentials(
    request: Request,
    vault: CredentialVault = Depends(get_credential_vault),
) -> list[CredentialSummaryResponse]:
    require_agent_api_access(request)
    try:
        return vault.list_credentials()
    except CredentialVaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", response_model=CredentialSummaryResponse, status_code=status.HTTP_201_CREATED)
def upsert_credential(
    request: Request,
    payload: CredentialUpsertRequest,
    vault: CredentialVault = Depends(get_credential_vault),
) -> CredentialSummaryResponse:
    require_agent_api_access(request)
    try:
        return vault.upsert_credential(payload)
    except CredentialVaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    request: Request,
    credential_id: str,
    vault: CredentialVault = Depends(get_credential_vault),
) -> Response:
    require_agent_api_access(request)
    try:
        deleted = vault.delete_credential(credential_id)
    except CredentialVaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
