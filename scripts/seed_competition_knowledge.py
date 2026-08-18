#!/usr/bin/env python3
"""Seed the competition-demo knowledge base into the local research store.

Reads the curated seed in ``competition_kb_seed_data`` and ingests documents
and long-term fact cards via the existing, validated ingestion boundary
(``FinancialKnowledgeService``).  The repository dedups by ``content_hash``
and fact cards carry deterministic ``revision_id``s, so this script is
idempotent: re-running neither duplicates rows nor overwrites active training
data.

Run: ``python3 scripts/seed_competition_knowledge.py``
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from competition_kb_seed_data import ANNOUNCEMENT_AT, AS_OF, COMPANIES, PUBLISHED_AT, seed_payload  # noqa: E402

import hashlib  # noqa: E402
from uuid import UUID  # noqa: E402

from investment_research.domain.base import utc_now  # noqa: E402
from investment_research.domain.knowledge import (  # noqa: E402
    FinancialKnowledgeDocument,
    FinancialLineItem,
    LongTermResearchFactCard,
)
from investment_research.repository.sqlite import create_unit_of_work  # noqa: E402
from investment_research.service.financial_knowledge import FinancialKnowledgeService  # noqa: E402
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService  # noqa: E402


def _deterministic_uuid(seed: str) -> UUID:
    """Stable UUID from a seed so re-running never creates duplicate revisions."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return UUID(bytes=digest[:16])


def _content_hash(service: FinancialKnowledgeService, *, title: str, content: str, source_url: str) -> str:
    return service.content_hash(title=title, content=content, source_url=source_url)


def _ingest_documents(service: FinancialKnowledgeService, company: dict) -> list[str]:
    ingested: list[str] = []
    for doc in company["documents"]:
        published = _parse_dt(doc.get("published_at", PUBLISHED_AT))
        available = _parse_dt(doc.get("available_at", AS_OF))
        content_hash = _content_hash(service, title=doc["title"], content=doc["content"], source_url=doc["source_url"])
        document = FinancialKnowledgeDocument(
            title=doc["title"],
            content=doc["content"],
            source_name=doc["source_name"],
            source_url=doc["source_url"],
            market="CN",
            symbol=company["symbol"],
            document_type=doc["document_type"],
            published_at=published,
            effective_from=published,
            collected_at=available,
            first_observed_at=available,
            available_at=available,
            content_hash=content_hash,
            data_tier="research_pit",
            source_kind="official_public",
            copyright_status="official_public",
            content_scope="full_text",
            authority_level=doc.get("authority_level", 3),
            announcement_category=doc.get("announcement_category"),
            report_period=doc.get("report_period"),
            parser_version="competition-demo-seed-v1",
            visibility_assumption="research_demonstration",
        )
        stored = service.ingest(document)
        ingested.append(str(stored.id))
    return ingested


def _ingest_fact_cards(service: FinancialKnowledgeService, company: dict) -> list[str]:
    ingested: list[str] = []
    for index, card in enumerate(company.get("fact_cards", [])):
        published = _parse_dt(card.get("published_at", PUBLISHED_AT))
        available = _parse_dt(card.get("available_at", AS_OF))
        revision_id = _deterministic_uuid(f"{company['symbol']}|{card['fact_key']}")
        fact_card = LongTermResearchFactCard(
            revision_id=revision_id,
            market="CN",
            symbol=company["symbol"],
            fact_key=card["fact_key"],
            topic=card["topic"],
            claim=card["claim"],
            stance=card["stance"],
            source_name=company.get("card_source_name", "研究展示事实卡"),
            source_url=f"https://example-exchange.com/{company['symbol']}-factcard-{card['fact_key'].replace('.', '-')}",
            published_at=published,
            available_at=available,
            valid_from=published,
            confidence=card.get("confidence", 0.7),
            authority_level=card.get("authority_level", 3),
        )
        stored = service.ingest_fact_card(fact_card)
        ingested.append(str(stored.revision_id))
    return ingested


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _ingest_line_items(service: FinancialKnowledgeService, company: dict) -> list[str]:
    ingested: list[str] = []
    for entry in company.get("line_items", []):
        published = _parse_dt(entry.get("published_at", PUBLISHED_AT))
        available = _parse_dt(entry.get("available_at", AS_OF))
        content_hash = _line_item_hash(
            symbol=company["symbol"], period=entry["period"], metric=entry["metric"],
            source_url=entry["source_url"], value=entry["value"], unit=entry["unit"],
            scale=entry.get("scale", 1.0), published_at=published,
            metric_label=entry["metric_label"],
        )
        item = FinancialLineItem(
            id=_deterministic_uuid(f"{company['symbol']}|{entry['period']}|{entry['metric']}"),
            market="CN",
            symbol=company["symbol"],
            period=entry["period"],
            metric=entry["metric"],
            metric_label=entry["metric_label"],
            value=entry["value"],
            unit=entry["unit"],
            scale=entry.get("scale", 1.0),
            yoy_pct=entry.get("yoy_pct"),
            qoq_pct=entry.get("qoq_pct"),
            source_name="交易所公告",
            source_url=entry["source_url"],
            published_at=published,
            available_at=available,
            valid_from=published,
            authority_level=entry.get("authority_level", 3),
            data_tier="research_pit",
            content_hash=content_hash,
        )
        stored = service.ingest_line_item(item)
        ingested.append(str(stored.id))
    return ingested


def _line_item_hash(
    *, symbol: str, period: str, metric: str, source_url: str,
    value: float, unit: str, scale: float, published_at: datetime, metric_label: str,
) -> str:
    # Phase 7: delegate to the single source on the domain model so the
    # seeder and FinancialKnowledgeService.ingest_line_item can never drift on
    # the hash formula (a drift would silently break PIT dedup /
    # supersede-by-revision and let the dashboard render two revisions of the
    # same figure at once).
    return FinancialLineItem.content_hash_of(
        symbol=symbol, period=period, metric=metric, source_url=source_url,
        value=value, unit=unit, scale=scale,
        published_at=published_at, metric_label=metric_label,
    )


def _run_seed_into(uow) -> list[dict]:
    """Seed the competition KB into a unit of work and return a per-company summary.

    Injecting the unit of work lets tests use a throwaway DB while the CLI
    uses the configured store.  Idempotent: content-hash dedup and
    deterministic fact-card revision ids mean re-running never duplicates.
    """
    service = FinancialKnowledgeService(uow)
    retrieval = KnowledgeRetrievalService(uow)
    summary: list[dict] = []
    for company in COMPANIES:
        doc_ids = _ingest_documents(service, company)
        card_ids = _ingest_fact_cards(service, company)
        item_ids = _ingest_line_items(service, company)
        summary.append({
            "symbol": company["symbol"], "name": company["name"],
            "documents": len(doc_ids), "fact_cards": len(card_ids),
            "line_items": len(item_ids),
        })
    # Re-index deterministically so chunks/embeddings exist immediately.
    for document in uow.financial_knowledge.list_all_for_reindex(market="CN"):
        if document.parser_version == "competition-demo-seed-v1":
            retrieval.index_document(document)
    return summary


def main() -> int:
    uow = create_unit_of_work()
    try:
        summary = _run_seed_into(uow)
        reindexed = len([
            doc for doc in uow.financial_knowledge.list_all_for_reindex(market="CN")
            if doc.parser_version == "competition-demo-seed-v1"
        ])
    finally:
        uow.close()

    manifest = {
        "schema_version": "competition-knowledge-seed-manifest-v1",
        "data_tier": "research_demo",
        "validation_status": "research_demonstration_not_validated",
        "generated_at": utc_now().isoformat(),
        "companies": summary,
        "reindexed_documents": reindexed,
    }
    out = PROJECT / "artifacts" / "competition_demo" / "knowledge_seed_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fixture = PROJECT / "artifacts" / "competition_demo" / "knowledge_seed.json"
    fixture.write_text(json.dumps(seed_payload(generated_at=utc_now()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"seeded {sum(item['documents'] for item in summary)} documents, "
          f"{sum(item['fact_cards'] for item in summary)} fact cards; reindexed {reindexed}")
    print(f"manifest -> {out.relative_to(PROJECT)}")
    print(f"fixture  -> {fixture.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
