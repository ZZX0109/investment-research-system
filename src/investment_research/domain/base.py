from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from investment_research.domain.enums import DataMode, DataSourceType, EntityStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GenerationLink(BaseModel):
    step: str
    producer: str
    version: str
    created_at: datetime = Field(default_factory=utc_now)


class Provenance(BaseModel):
    data_mode: DataMode
    source_type: DataSourceType
    source_name: str
    observed_at: datetime
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    generation_chain: list[GenerationLink] = Field(default_factory=list)


class EntityVersion(BaseModel):
    schema_version: str = "1.0.0"
    entity_version: int = Field(default=1, ge=1)


class DomainEntity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: EntityStatus = EntityStatus.ACTIVE
    version: EntityVersion = Field(default_factory=EntityVersion)
    provenance: Provenance
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def schema(self) -> str:
        return self.version.schema_version

    @property
    def source(self) -> DataSourceType:
        return self.provenance.source_type
