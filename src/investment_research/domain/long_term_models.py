"""Relational aggregates used by the long-lived research domain."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.base import utc_now
from investment_research.domain.enums import (
    AccessRole,
    ClaimStatus,
    JudgeVerdict,
    ModelLifecycleStatus,
    ResearchRunState,
)


class ResourceShare(BaseModel):
    id: UUID
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: UUID
    viewer_user_id: UUID
    role: AccessRole = AccessRole.VIEWER
    created_by_user_id: UUID
    created_at: datetime = Field(default_factory=utc_now)


class Claim(BaseModel):
    id: UUID
    asset_id: UUID
    owner_user_id: UUID
    statement: str = Field(min_length=1)
    direction: str = Field(pattern="^(positive|neutral|negative|unknown)$")
    status: ClaimStatus = ClaimStatus.PROPOSED
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[UUID] = Field(min_length=1)
    citation_ids: list[UUID] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    contrary_claim_id: UUID | None = None
    supersedes_claim_id: UUID | None = None
    reviewed_by_user_id: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _reviewed_claim_requires_reviewer(self) -> "Claim":
        if self.status in {ClaimStatus.VERIFIED, ClaimStatus.REJECTED} and (
            self.reviewed_by_user_id is None or self.reviewed_at is None
        ):
            raise ValueError("Verified or rejected claims require reviewer metadata")
        return self


class ResearchRunRecord(BaseModel):
    run_id: UUID
    owner_user_id: UUID
    state: ResearchRunState
    correlation_id: str = Field(min_length=8, max_length=64)
    snapshot_hash: str = Field(min_length=64, max_length=64)
    feature_contract_version: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ModelVersionRecord(BaseModel):
    id: UUID
    model_id: str = Field(min_length=1)
    status: ModelLifecycleStatus
    feature_contract_version: str | None = None
    artifact_key: str = Field(min_length=1)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class GateFinding(BaseModel):
    rule_key: str = Field(min_length=1)
    severity: JudgeVerdict
    passed: bool
    reason: str = Field(min_length=1)


class GateEvaluation(BaseModel):
    id: UUID
    research_run_id: UUID
    policy_version: str = Field(min_length=1)
    correlation_id: str = Field(min_length=8, max_length=64)
    verdict: JudgeVerdict
    score: float = Field(ge=0.0, le=1.0)
    findings: list[GateFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
