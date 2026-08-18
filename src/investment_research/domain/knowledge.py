from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.base import utc_now


class LongTermResearchFactCard(BaseModel):
    """A point-in-time evidence unit used by long-term research narratives.

    A card is deliberately a sourced claim rather than an inferred investment
    conclusion.  Opposing and uncertain evidence remain first-class records so
    callers cannot silently turn retrieval gaps into positive evidence.
    """

    revision_id: UUID = Field(default_factory=uuid4)
    previous_revision_id: UUID | None = None
    revision: int = Field(default=1, ge=1)
    market: str = "CN"
    symbol: str = Field(min_length=2, max_length=32)
    fact_key: str = Field(min_length=2, max_length=160, pattern=r"^[a-zA-Z0-9_.:-]+$")
    topic: str = Field(min_length=2, max_length=120)
    claim: str = Field(min_length=2, max_length=20_000)
    stance: Literal["supporting", "contrary", "uncertain"]
    source_name: str = Field(min_length=2, max_length=160)
    source_url: str = Field(min_length=8, max_length=2_000)
    published_at: datetime
    available_at: datetime
    valid_from: datetime
    valid_to: datetime | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    authority_level: int = Field(default=3, ge=0, le=5)
    status: Literal["active", "superseded", "withdrawn"] = "active"

    @model_validator(mode="after")
    def validate_pit_contract(self) -> "LongTermResearchFactCard":
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must use https")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must follow valid_from")
        if any(
            value.utcoffset() is None
            for value in (self.published_at, self.available_at, self.valid_from)
        ):
            raise ValueError("fact-card PIT timestamps must be timezone-aware")
        if self.valid_to is not None and self.valid_to.utcoffset() is None:
            raise ValueError("fact-card PIT timestamps must be timezone-aware")
        return self


class LongTermFactCardQueryResult(BaseModel):
    symbol: str
    as_of: datetime
    cards: list[LongTermResearchFactCard] = Field(default_factory=list)
    coverage_status: Literal[
        "events_present", "confirmed_none", "coverage_incomplete", "unknown"
    ] = "unknown"
    # False is the safe default: an empty result normally means "not covered",
    # not "the company had no relevant event".
    absence_is_evidence: bool = False
    coverage_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_absence_semantics(self) -> "LongTermFactCardQueryResult":
        if self.cards and self.coverage_status != "events_present":
            raise ValueError("non-empty fact-card results must be events_present")
        if self.absence_is_evidence and (
            self.cards or self.coverage_status != "confirmed_none"
        ):
            raise ValueError("absence is evidence only for explicitly confirmed-none coverage")
        return self


class FinancialKnowledgeDocument(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=2, max_length=2_000_000)
    source_name: str = Field(min_length=2, max_length=160)
    source_url: str | None = Field(default=None, max_length=2_000)
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
    # The catalog distinguishes authoritative full text, user-owned uploads,
    # and copyright-aware public metadata.  A news/analyst source never turns
    # into a silently copied full-text corpus.
    source_kind: Literal["official_public", "user_upload", "news_report"] = "official_public"
    copyright_status: Literal["official_public", "user_owned", "metadata_only"] = "official_public"
    content_scope: Literal["full_text", "metadata_excerpt"] = "full_text"
    owner_user_id: UUID | None = None
    access_scope: Literal["public", "private"] = "public"
    exchange: str | None = None
    issuer_name: str | None = None
    announcement_category: str | None = None
    report_period: str | None = None
    language: str = "zh-CN"
    authority_level: int = Field(default=3, ge=0, le=5)
    first_observed_at: datetime | None = None
    previous_revision_id: UUID | None = None
    raw_payload_ref: str | None = None
    raw_payload_hash: str | None = Field(default=None, min_length=64, max_length=64)
    parser_version: str = "financial-knowledge-parser-v1"
    visibility_assumption: str | None = None
    fact_card: LongTermResearchFactCard | None = None

    @model_validator(mode="after")
    def validate_content_rights(self) -> "FinancialKnowledgeDocument":
        if self.source_kind == "news_report" and (
            self.copyright_status != "metadata_only" or self.content_scope != "metadata_excerpt"
        ):
            raise ValueError("news_report knowledge is metadata_excerpt only unless separately licensed")
        if self.source_kind == "user_upload" and self.copyright_status != "user_owned":
            raise ValueError("user_upload knowledge must be marked user_owned")
        if self.source_kind == "user_upload" and (
            self.owner_user_id is None or self.access_scope != "private"
        ):
            raise ValueError("user_upload knowledge must be private and owned")
        if self.access_scope == "private" and self.owner_user_id is None:
            raise ValueError("private knowledge requires owner_user_id")
        if self.source_url is not None and not self.source_url.startswith("https://"):
            raise ValueError("source_url must use https")
        if self.document_type == "long_term_fact_card" and self.fact_card is None:
            raise ValueError("long_term_fact_card documents require fact_card metadata")
        if self.fact_card is not None:
            card = self.fact_card
            if self.document_type != "long_term_fact_card":
                raise ValueError("fact_card metadata is only valid on long_term_fact_card documents")
            if (
                card.revision_id != self.id
                or card.market != self.market
                or card.symbol != self.symbol
                or card.source_name != self.source_name
                or card.source_url != self.source_url
                or card.published_at != self.published_at
                or card.available_at != self.available_at
                or card.valid_from != self.effective_from
                or card.valid_to != self.effective_to
                or card.revision != self.revision
                or card.previous_revision_id != self.previous_revision_id
                or card.authority_level != self.authority_level
                or card.status != self.status
            ):
                raise ValueError("fact_card metadata must match its knowledge document envelope")
        return self


class KnowledgeSearchResult(BaseModel):
    document: FinancialKnowledgeDocument
    score: float
    matched_terms: list[str] = Field(default_factory=list)
    chunk_id: UUID | None = None
    citation_id: str | None = None
    snippet: str | None = None
    page_or_section: str | None = None
    lexical_score: float = 0.0
    semantic_score: float | None = None
    authority_score: float = 0.0
    final_score: float = 0.0
    rerank_score: float | None = None
    coverage_status: Literal[
        "complete", "partial", "fetch_failed", "unsupported", "unknown"
    ] = "unknown"
    pit_status: Literal["proven", "assumed", "unavailable"] = "assumed"


class KnowledgeSource(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    provider: str
    name: str
    base_url: str
    source_kind: Literal["official_public", "user_upload", "news_report"]
    authority_level: int = Field(default=3, ge=0, le=5)
    content_policy: Literal["full_text", "metadata_only", "user_owned"]
    update_frequency: Literal["daily", "weekly", "monthly", "manual"] = "daily"
    enabled: bool = True


class KnowledgeFetchRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    provider: str
    request_params: dict[str, object] = Field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None
    cursor_before: str | None = None
    cursor_after: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "complete", "partial", "fetch_failed", "unsupported"]
    http_status: int | None = None
    target_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    failure_reason: str | None = None


class KnowledgeChunk(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    revision: int = Field(default=1, ge=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    section: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    token_estimate: int = Field(default=0, ge=0)
    content_hash: str = Field(min_length=64, max_length=64)
    owner_user_id: UUID | None = None
    access_scope: Literal["public", "private"] = "public"


class KnowledgeEmbedding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    chunk_id: UUID
    model_name: str
    model_revision: str
    dimension: int = Field(gt=0)
    vector_hash: str = Field(min_length=64, max_length=64)
    shard_key: str
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeCoverageLedger(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    provider: str
    market: str = "CN"
    symbol: str | None = None
    dataset: str
    window_start: datetime | None = None
    window_end: datetime | None = None
    metadata_status: Literal["complete", "partial", "fetch_failed", "unsupported"]
    full_text_status: Literal["complete", "partial", "fetch_failed", "unsupported"]
    event_coverage_status: Literal[
        "events_present", "confirmed_none", "unsupported", "fetch_failed", "pending_update", "partial"
    ] = "partial"
    target_count: int = Field(default=0, ge=0)
    metadata_count: int = Field(default=0, ge=0)
    full_text_count: int = Field(default=0, ge=0)
    checked_at: datetime = Field(default_factory=utc_now)
    reasons: list[str] = Field(default_factory=list)


class KnowledgeRetrievalSnapshot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID | None = None
    query_hash: str = Field(min_length=64, max_length=64)
    query_text: str
    market: str = "CN"
    symbol: str | None = None
    as_of: datetime
    retrieval_mode: Literal["lexical", "hybrid"]
    embedding_model: str | None = None
    rerank_model: str | None = None
    result_chunk_ids: list[UUID] = Field(default_factory=list)
    result_citation_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class FinancialLineItem(BaseModel):
    """A point-in-time, revisioned numeric financial fact (revenue, margin...).

    Like fact cards, line items are sourced claims rather than conclusions.
    They carry period, metric, value, unit and YoY/QoQ deltas so the research
    assistant can cite structured figures ("2025H1 营收 X 亿 同比 Y%").  A
    missing period surfaces as "未披露", never as zero.
    """

    id: UUID = Field(default_factory=uuid4)
    previous_revision_id: UUID | None = None
    revision: int = Field(default=1, ge=1)
    market: str = "CN"
    symbol: str = Field(min_length=2, max_length=32)
    period: str = Field(min_length=2, max_length=24, pattern=r"^[0-9]{4}(FY|H1|H2|Q[1-4])$")
    metric: str = Field(min_length=2, max_length=64, pattern=r"^[a-z_]+$")
    metric_label: str = Field(min_length=2, max_length=64)
    value: float
    unit: str = Field(min_length=1, max_length=16)
    scale: float = Field(default=1.0)
    yoy_pct: float | None = None
    qoq_pct: float | None = None
    source_name: str = Field(min_length=2, max_length=160)
    source_url: str = Field(min_length=8, max_length=2_000)
    source_doc_id: UUID | None = None
    published_at: datetime
    available_at: datetime
    valid_from: datetime
    valid_to: datetime | None = None
    authority_level: int = Field(default=3, ge=0, le=5)
    data_tier: Literal["research_pit", "research_demo"] = "research_pit"
    status: Literal["active", "superseded", "withdrawn"] = "active"
    content_hash: str = Field(min_length=64, max_length=64)

    @staticmethod
    def content_hash_of(
        *,
        symbol: str,
        period: str,
        metric: str,
        source_url: str,
        value: float,
        unit: str,
        scale: float,
        published_at: datetime,
        metric_label: str,
    ) -> str:
        """Single source for the line-item content hash.

        The seeder (``scripts/seed_competition_knowledge.py``) and the ingest
        service (``FinancialKnowledgeService._line_item_hash``) MUST both go
        through this method so a hash computed at seed time is byte-identical
        to the hash the service validates against — otherwise PIT dedup /
        supersede-by-revision silently breaks and the dashboard can render two
        revisions of the same figure at once.
        """
        payload = "|".join(
            (
                symbol,
                period,
                metric,
                source_url,
                f"{float(value):.6f}",
                unit,
                f"{float(scale):.6f}",
                published_at.isoformat(),
                metric_label,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def compute_content_hash(self) -> str:
        """Recompute this item's hash from its own fields (single source)."""
        return FinancialLineItem.content_hash_of(
            symbol=self.symbol,
            period=self.period,
            metric=self.metric,
            source_url=self.source_url,
            value=self.value,
            unit=self.unit,
            scale=self.scale,
            published_at=self.published_at,
            metric_label=self.metric_label,
        )

    @model_validator(mode="after")
    def validate_line_item_pit(self) -> "FinancialLineItem":
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must use https")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must follow valid_from")
        for value in (self.published_at, self.available_at, self.valid_from):
            if value.utcoffset() is None:
                raise ValueError("line-item PIT timestamps must be timezone-aware")
        if self.content_hash != self.compute_content_hash():
            raise ValueError("line-item content_hash does not match payload")
        return self


class FinancialLineItemQueryResult(BaseModel):
    symbol: str
    as_of: datetime
    line_items: list[FinancialLineItem] = Field(default_factory=list)
    coverage_status: Literal[
        "figures_present", "confirmed_none", "coverage_incomplete", "unknown"
    ] = "unknown"
    coverage_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_line_item_coverage(self) -> "FinancialLineItemQueryResult":
        if self.line_items and self.coverage_status != "figures_present":
            raise ValueError("non-empty line-item results must be figures_present")
        return self
