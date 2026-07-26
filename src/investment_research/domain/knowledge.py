from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from investment_research.domain.base import utc_now


class FinancialKnowledgeDocument(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=2, max_length=20_000)
    source_name: str = Field(min_length=2, max_length=160)
    source_url: str = Field(pattern=r"^https://", max_length=2_000)
    market: str = "CN"
    symbol: str | None = None
    document_type: str = Field(min_length=2, max_length=48)
    published_at: datetime
    effective_from: datetime
    effective_to: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)
    available_at: datetime
    revision: int = 1
    content_hash: str
    data_tier: Literal["research_pit", "formal_pit"] = "research_pit"
    status: Literal["active", "superseded", "withdrawn"] = "active"


class KnowledgeSearchResult(BaseModel):
    document: FinancialKnowledgeDocument
    score: float
    matched_terms: list[str] = Field(default_factory=list)
