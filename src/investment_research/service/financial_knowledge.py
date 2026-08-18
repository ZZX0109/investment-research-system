"""Validated ingestion boundary for the research assistant knowledge catalog."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Iterable
from uuid import UUID

from investment_research.domain.knowledge import (
    FinancialKnowledgeDocument,
    FinancialLineItem,
    FinancialLineItemQueryResult,
    LongTermFactCardQueryResult,
    LongTermResearchFactCard,
)
from investment_research.domain.models import DocumentArtifact, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService


class FinancialKnowledgeService:
    def __init__(self, uow: SQLiteUnitOfWork, *, retrieval: KnowledgeRetrievalService | None = None) -> None:
        self.uow = uow
        self.retrieval = retrieval or KnowledgeRetrievalService(uow)

    def ingest(self, document: FinancialKnowledgeDocument) -> FinancialKnowledgeDocument:
        if document.data_tier != "research_pit":
            raise ValueError("financial knowledge ingestion is research_pit only")
        expected_hash = self.content_hash(
            title=document.title, content=document.content, source_url=document.source_url,
            owner_user_id=document.owner_user_id if document.access_scope == "private" else None,
        )
        if document.content_hash != expected_hash:
            raise ValueError("content_hash does not match title/content/source_url")
        if document.available_at < document.published_at:
            raise ValueError("available_at cannot precede published_at")
        first_observed = document.first_observed_at or document.collected_at
        effective_available = max(document.published_at, first_observed, document.available_at)
        latest = self.uow.financial_knowledge.latest_by_identity(
            market=document.market, symbol=document.symbol, source_url=document.source_url,
            title=document.title, owner_user_id=document.owner_user_id,
        )
        if latest is not None and latest.content_hash != document.content_hash:
            updates: dict[str, object] = {
                "revision": latest.revision + 1,
                "previous_revision_id": latest.id,
                "first_observed_at": first_observed,
                "available_at": effective_available,
            }
            if document.fact_card is not None:
                updates["fact_card"] = document.fact_card.model_copy(update={
                    "revision": latest.revision + 1,
                    "previous_revision_id": latest.id,
                    "available_at": effective_available,
                })
            document = document.model_copy(update=updates)
            self.uow.financial_knowledge.supersede(
                str(latest.id), effective_to=effective_available,
            )
        else:
            updates = {
                "first_observed_at": first_observed,
                "available_at": effective_available,
            }
            if document.fact_card is not None:
                updates["fact_card"] = document.fact_card.model_copy(
                    update={"available_at": effective_available}
                )
            document = document.model_copy(update=updates)
        stored = self.uow.financial_knowledge.add(document)
        if stored.id == document.id:
            self.retrieval.index_document(stored)
        return stored

    def ingest_metadata(
        self, *, title: str, summary: str, source_name: str, source_url: str,
        market: str, published_at: datetime, available_at: datetime, symbol: str | None = None,
    ) -> FinancialKnowledgeDocument:
        """Create a copyright-aware metadata entry for public news/reports."""
        content = summary[:2_000]
        content_hash = self.content_hash(title=title, content=content, source_url=source_url)
        return self.ingest(FinancialKnowledgeDocument(
            title=title, content=content, source_name=source_name, source_url=source_url,
            market=market.upper(), symbol=symbol, document_type="news_metadata",
            published_at=published_at, effective_from=published_at, available_at=available_at,
            content_hash=content_hash, data_tier="research_pit", source_kind="news_report",
            copyright_status="metadata_only", content_scope="metadata_excerpt",
        ))

    def ingest_user_artifact(
        self, artifact: DocumentArtifact, *, user: User,
    ) -> FinancialKnowledgeDocument:
        if artifact.user_id != user.id:
            raise ValueError("document owner mismatch")
        if artifact.parse_status != "parsed" or not artifact.text_summary:
            raise ValueError("document must be parsed before knowledge indexing")
        asset = None if artifact.asset_id is None else self.uow.assets.get(str(artifact.asset_id))
        now = artifact.provenance.observed_at
        title = artifact.filename
        content_hash = self.content_hash(
            title=title, content=artifact.text_summary, source_url=artifact.source_url,
            owner_user_id=user.id,
        )
        return self.ingest(FinancialKnowledgeDocument(
            title=title, content=artifact.text_summary, source_name="用户资料",
            source_url=artifact.source_url, market="CN",
            symbol=None if asset is None else asset.ticker,
            document_type="user_document", published_at=now, effective_from=now,
            collected_at=now, available_at=now, first_observed_at=now,
            content_hash=content_hash, data_tier="research_pit",
            source_kind="user_upload", copyright_status="user_owned",
            content_scope="full_text", owner_user_id=user.id, access_scope="private",
            authority_level=2, raw_payload_ref=artifact.storage_path,
            raw_payload_hash=artifact.sha256,
        ))

    def ingest_fact_card(
        self, card: LongTermResearchFactCard,
    ) -> LongTermResearchFactCard:
        """Persist and index a sourced long-term fact using the PIT catalog.

        ``fact_key`` is the stable identity across revisions.  A changed claim,
        stance, confidence or validity window therefore becomes a new revision
        without overwriting what an earlier decision could have observed.
        """
        card = card.model_copy(update={"market": card.market.upper()})
        title = f"{card.symbol}｜{card.topic}｜{card.fact_key}"
        content = self._fact_card_content(card)
        content_hash = self.content_hash(
            title=title, content=content, source_url=card.source_url,
        )
        stored = self.ingest(FinancialKnowledgeDocument(
            id=card.revision_id,
            title=title,
            content=content,
            source_name=card.source_name,
            source_url=card.source_url,
            market=card.market.upper(),
            symbol=card.symbol,
            document_type="long_term_fact_card",
            published_at=card.published_at,
            effective_from=card.valid_from,
            effective_to=card.valid_to,
            collected_at=card.available_at,
            first_observed_at=card.available_at,
            available_at=card.available_at,
            revision=card.revision,
            previous_revision_id=card.previous_revision_id,
            content_hash=content_hash,
            data_tier="research_pit",
            source_kind="official_public",
            copyright_status="official_public",
            content_scope="metadata_excerpt",
            authority_level=card.authority_level,
            status=card.status,
            parser_version="long-term-fact-card-v1",
            fact_card=card,
        ))
        if stored.fact_card is None:  # defensive: enforced by the domain model
            raise RuntimeError("stored long-term fact card metadata is unavailable")
        return stored.fact_card

    def retrieve_fact_cards(
        self, *, symbol: str, as_of: datetime, market: str = "CN",
        topics: Iterable[str] | None = None,
        stances: Iterable[str] | None = None,
        owner_user_id: UUID | None = None,
        coverage_dataset: str = "long_term_fact_cards",
    ) -> LongTermFactCardQueryResult:
        """Return only cards visible at ``as_of`` with explicit absence semantics."""
        if as_of.utcoffset() is None:
            raise ValueError("fact-card as_of must be timezone-aware")
        topic_filter = {item.strip().lower() for item in (topics or []) if item.strip()}
        stance_filter = {item.strip().lower() for item in (stances or []) if item.strip()}
        unknown_stances = stance_filter - {"supporting", "contrary", "uncertain"}
        if unknown_stances:
            raise ValueError(f"unknown fact-card stances: {sorted(unknown_stances)}")
        candidates = self.uow.financial_knowledge.candidate_chunks(
            as_of=as_of, market=market.upper(), symbol=symbol,
            owner_user_id=owner_user_id, document_type="long_term_fact_card",
        )
        cards: list[LongTermResearchFactCard] = []
        seen: set[UUID] = set()
        for document, _chunk in candidates:
            card = document.fact_card
            if card is None or card.symbol != symbol or card.revision_id in seen:
                continue
            if topic_filter and card.topic.lower() not in topic_filter:
                continue
            if stance_filter and card.stance not in stance_filter:
                continue
            seen.add(card.revision_id)
            cards.append(card)
        cards.sort(key=lambda item: (item.available_at, item.revision), reverse=True)
        if cards:
            return LongTermFactCardQueryResult(
                symbol=symbol, as_of=as_of, cards=cards,
                coverage_status="events_present", absence_is_evidence=False,
            )

        coverages = [
            item for item in self.uow.financial_knowledge.latest_coverage(
                market=market.upper(), symbol=symbol, as_of=as_of,
            )
            if item.symbol == symbol and item.dataset == coverage_dataset
        ]
        if (
            not topic_filter and not stance_filter
            and any(item.event_coverage_status == "confirmed_none" for item in coverages)
        ):
            reasons = [reason for item in coverages for reason in item.reasons]
            return LongTermFactCardQueryResult(
                symbol=symbol, as_of=as_of, coverage_status="confirmed_none",
                absence_is_evidence=True, coverage_reasons=list(dict.fromkeys(reasons)),
            )
        if coverages:
            reasons = [reason for item in coverages for reason in item.reasons]
            if topic_filter or stance_filter:
                reasons.append("filtered_fact_card_absence_not_proven")
            return LongTermFactCardQueryResult(
                symbol=symbol, as_of=as_of, coverage_status="coverage_incomplete",
                absence_is_evidence=False, coverage_reasons=list(dict.fromkeys(reasons)),
            )
        return LongTermFactCardQueryResult(
            symbol=symbol, as_of=as_of, coverage_status="unknown",
            absence_is_evidence=False,
            coverage_reasons=["fact_card_coverage_not_recorded"],
        )

    def ingest_line_item(self, item: "FinancialLineItem") -> "FinancialLineItem":
        """Persist a revisioned structured financial figure (PIT, hash-dedup)."""
        expected = self._line_item_hash(item)
        if item.content_hash != expected:
            raise ValueError("line-item content_hash does not match payload")
        latest = self.uow.financial_knowledge.latest_line_item_by_identity(
            market=item.market, symbol=item.symbol, period=item.period, metric=item.metric,
        )
        if latest is not None and latest.content_hash != item.content_hash:
            revised = item.model_copy(update={
                "revision": latest.revision + 1,
                "previous_revision_id": latest.id,
            })
            self.uow.financial_knowledge.supersede_line_item(str(latest.id), effective_to=revised.available_at)
            return self.uow.financial_knowledge.add_line_item(revised)
        return self.uow.financial_knowledge.add_line_item(item)

    def retrieve_line_items(
        self, *, symbol: str, as_of: datetime, market: str = "CN",
        metrics: Iterable[str] | None = None, periods: Iterable[str] | None = None,
    ) -> "FinancialLineItemQueryResult":
        """Return PIT-visible line items; absence means "未披露", never zero."""
        if as_of.utcoffset() is None:
            raise ValueError("line-item as_of must be timezone-aware")
        metric_list = [item.strip() for item in (metrics or []) if item.strip()]
        period_list = [item.strip() for item in (periods or []) if item.strip()]
        items = self.uow.financial_knowledge.line_items_for(
            market=market.upper(), symbol=symbol, as_of=as_of,
            metrics=metric_list or None, periods=period_list or None,
        )
        if items:
            return FinancialLineItemQueryResult(
                symbol=symbol, as_of=as_of, line_items=items,
                coverage_status="figures_present",
            )
        return FinancialLineItemQueryResult(
            symbol=symbol, as_of=as_of, coverage_status="unknown",
            coverage_reasons=["line_item_coverage_not_recorded"],
        )

    @staticmethod
    def _line_item_hash(item: "FinancialLineItem") -> str:
        # Phase 7: delegate to the single source on the domain model so the
        # seeder and the service can never drift on the hash formula (a drift
        # would silently break PIT dedup / supersede-by-revision and let the
        # dashboard render two revisions of the same figure at once).
        return item.compute_content_hash()

    @staticmethod
    def _fact_card_content(card: LongTermResearchFactCard) -> str:
        valid_to = "持续有效" if card.valid_to is None else card.valid_to.isoformat()
        return "\n".join((
            f"主题：{card.topic}",
            f"证据立场：{card.stance}",
            f"事实陈述：{card.claim}",
            f"有效期：{card.valid_from.isoformat()} 至 {valid_to}",
            f"证据状态分数：{card.confidence:.6f}",
            f"来源权威等级：{card.authority_level}",
        ))

    @staticmethod
    def content_hash(
        *, title: str, content: str, source_url: str | None,
        owner_user_id: UUID | None = None,
    ) -> str:
        owner = "" if owner_user_id is None else f"{owner_user_id}|"
        return hashlib.sha256(f"{owner}{title}|{content}|{source_url or ''}".encode()).hexdigest()
