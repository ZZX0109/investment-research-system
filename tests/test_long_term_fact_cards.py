from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from investment_research.domain.knowledge import (
    KnowledgeCoverageLedger,
    LongTermResearchFactCard,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService


class LexicalOnlyEmbedder:
    model_name = "disabled-fact-card-test"
    model_revision = "v1"
    available = False

    def encode_query(self, text: str) -> list[float]:
        raise AssertionError(text)

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError(texts)


def _service(tmp_path) -> tuple[SQLiteUnitOfWork, FinancialKnowledgeService]:
    uow = SQLiteUnitOfWork(tmp_path / "fact-cards.db")
    retrieval = KnowledgeRetrievalService(uow, embedder=LexicalOnlyEmbedder())
    return uow, FinancialKnowledgeService(uow, retrieval=retrieval)


def _card(
    *, available_at: datetime, fact_key: str, claim: str,
    stance: str = "supporting", topic: str = "盈利质量",
) -> LongTermResearchFactCard:
    return LongTermResearchFactCard(
        symbol="600519",
        fact_key=fact_key,
        topic=topic,
        claim=claim,
        stance=stance,
        source_name="巨潮资讯网",
        source_url=f"https://www.cninfo.com.cn/{fact_key}.pdf",
        published_at=available_at - timedelta(minutes=30),
        available_at=available_at,
        valid_from=available_at - timedelta(minutes=30),
        confidence=0.92,
        authority_level=5,
    )


def test_fact_card_retrieval_is_pit_and_preserves_opposing_evidence(tmp_path) -> None:
    _uow, service = _service(tmp_path)
    first_time = datetime(2026, 7, 1, 8, tzinfo=timezone.utc)
    second_time = first_time + timedelta(days=3)
    service.ingest_fact_card(_card(
        available_at=first_time, fact_key="cash-flow", claim="经营现金流改善",
        stance="supporting",
    ))
    service.ingest_fact_card(_card(
        available_at=second_time, fact_key="inventory", claim="存货周转放缓",
        stance="contrary",
    ))

    historical = service.retrieve_fact_cards(
        symbol="600519", as_of=first_time + timedelta(minutes=1),
    )
    current = service.retrieve_fact_cards(
        symbol="600519", as_of=second_time + timedelta(minutes=1),
    )

    assert [item.fact_key for item in historical.cards] == ["cash-flow"]
    assert {item.stance for item in current.cards} == {"supporting", "contrary"}
    assert current.coverage_status == "events_present"
    assert current.absence_is_evidence is False


def test_fact_card_revision_does_not_rewrite_historical_view(tmp_path) -> None:
    _uow, service = _service(tmp_path)
    first_time = datetime(2026, 7, 1, 8, tzinfo=timezone.utc)
    first = service.ingest_fact_card(_card(
        available_at=first_time, fact_key="margin", claim="毛利率变化尚不确定",
        stance="uncertain",
    ))
    second_time = first_time + timedelta(days=2)
    second = service.ingest_fact_card(_card(
        available_at=second_time, fact_key="margin", claim="经更正后毛利率同比改善",
        stance="supporting",
    ))

    historical = service.retrieve_fact_cards(
        symbol="600519", as_of=first_time + timedelta(hours=1),
    )
    current = service.retrieve_fact_cards(
        symbol="600519", as_of=second_time + timedelta(hours=1),
    )

    assert historical.cards[0].revision_id == first.revision_id
    assert historical.cards[0].stance == "uncertain"
    assert current.cards[0].revision_id == second.revision_id
    assert current.cards[0].revision == 2
    assert current.cards[0].previous_revision_id == first.revision_id
    assert current.cards[0].stance == "supporting"


def test_empty_fact_cards_are_not_treated_as_no_event_without_pit_coverage(tmp_path) -> None:
    uow, service = _service(tmp_path)
    decision_time = datetime(2026, 7, 5, 9, tzinfo=timezone.utc)

    unknown = service.retrieve_fact_cards(symbol="000001", as_of=decision_time)
    assert unknown.cards == []
    assert unknown.coverage_status == "unknown"
    assert unknown.absence_is_evidence is False

    uow.financial_knowledge.add_coverage(KnowledgeCoverageLedger(
        provider="fact-card-builder", market="CN", symbol="000001",
        dataset="long_term_fact_cards", metadata_status="complete",
        full_text_status="complete", event_coverage_status="confirmed_none",
        checked_at=decision_time + timedelta(hours=1),
        reasons=["complete_source_window_confirmed_none"],
    ))

    still_unknown = service.retrieve_fact_cards(symbol="000001", as_of=decision_time)
    confirmed = service.retrieve_fact_cards(
        symbol="000001", as_of=decision_time + timedelta(hours=2),
    )
    filtered = service.retrieve_fact_cards(
        symbol="000001", as_of=decision_time + timedelta(hours=2),
        topics=["治理风险"],
    )
    assert still_unknown.coverage_status == "unknown"
    assert still_unknown.absence_is_evidence is False
    assert confirmed.coverage_status == "confirmed_none"
    assert confirmed.absence_is_evidence is True
    assert filtered.coverage_status == "coverage_incomplete"
    assert filtered.absence_is_evidence is False


def test_fact_card_query_rejects_naive_as_of_and_unknown_stance(tmp_path) -> None:
    _uow, service = _service(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        service.retrieve_fact_cards(
            symbol="600519", as_of=datetime(2026, 7, 1, 8),
        )
    with pytest.raises(ValueError, match="unknown fact-card stances"):
        service.retrieve_fact_cards(
            symbol="600519",
            as_of=datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
            stances=["positive"],
        )
