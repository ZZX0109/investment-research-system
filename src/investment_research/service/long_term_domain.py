"""Commands and queries for claims, sharing, and immutable research lineage."""

from __future__ import annotations

from uuid import UUID, uuid4

from investment_research.api.schemas import ClaimCreateRequest, ResourceShareCreateRequest
from investment_research.domain.enums import ClaimStatus
from investment_research.domain.long_term_models import Claim, ResourceShare
from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork


SHAREABLE_RESOURCE_TYPES = {
    "asset",
    "analysis_run",
    "research_report",
    "watchlist",
    "portfolio_snapshot",
}


class LongTermDomainService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def submit_claim(self, payload: ClaimCreateRequest, *, user: User) -> Claim:
        self.uow.domain.assert_access(
            resource_type="asset", resource_id=payload.asset_id, user_id=user.id, write=True
        )
        evidence_by_id = {
            str(item.id): item
            for item in self.uow.evidence.list_for_asset(payload.asset_id)
        }
        selected = []
        for evidence_id in payload.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise ValueError("Evidence not found")
            self.uow.domain.register_evidence(evidence=evidence, owner=user)
            selected.append(UUID(evidence_id))
        claim = Claim(
            id=uuid4(),
            asset_id=UUID(payload.asset_id),
            owner_user_id=user.id,
            statement=payload.statement,
            direction=payload.direction,
            confidence=payload.confidence,
            evidence_ids=selected,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            contrary_claim_id=None
            if payload.contrary_claim_id is None
            else UUID(payload.contrary_claim_id),
            supersedes_claim_id=None
            if payload.supersedes_claim_id is None
            else UUID(payload.supersedes_claim_id),
        )
        return self.uow.domain.submit_claim(claim, owner=user)

    def review_claim(self, claim_id: str, *, status: str, user: User) -> Claim:
        return self.uow.domain.review_claim(
            claim_id=claim_id, status=ClaimStatus(status), reviewer=user
        )

    def list_claims(self, asset_id: str, *, user: User) -> list[Claim]:
        return self.uow.domain.list_claims(asset_id=asset_id, user=user)

    def create_share(
        self, *, resource_type: str, resource_id: str, payload: ResourceShareCreateRequest, owner: User
    ) -> ResourceShare:
        self._validate_resource_type(resource_type)
        viewer = self.uow.users.get_by_email(payload.viewer_email.lower())
        if viewer is None:
            raise ValueError("Viewer not found")
        return self.uow.domain.create_share(
            resource_type=resource_type,
            resource_id=UUID(resource_id),
            viewer=viewer.user,
            owner=owner,
        )

    def list_shares(self, *, resource_type: str, resource_id: str, owner: User) -> list[ResourceShare]:
        self._validate_resource_type(resource_type)
        return self.uow.domain.list_shares(
            resource_type=resource_type, resource_id=UUID(resource_id), requester=owner
        )

    def revoke_share(self, *, resource_type: str, resource_id: str, viewer_user_id: str, owner: User) -> None:
        self._validate_resource_type(resource_type)
        self.uow.domain.revoke_share(
            resource_type=resource_type,
            resource_id=UUID(resource_id),
            viewer_user_id=UUID(viewer_user_id),
            owner=owner,
        )

    def _validate_resource_type(self, resource_type: str) -> None:
        if resource_type not in SHAREABLE_RESOURCE_TYPES:
            raise ValueError("Resource type is not shareable")
