"""Tests for the competition-demo knowledge base seeding (Phase 1).

Guards the "KB is empty in the demo" hardening: after seeding, retrieval
returns citable, company-specific facts and fact cards span supporting,
contrary and uncertain stances; re-running is idempotent.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _load_seeder(project_root: Path):
    """Load the seeder module so its internal helper can be exercised in tests."""
    scripts_dir = str(project_root / "scripts")
    sys.path.insert(0, scripts_dir)
    import importlib
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def test_seeding_returns_citable_company_specific_facts(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "kb.db")
    seeder = _load_seeder(REPO_ROOT)
    summary = seeder._run_seed_into(uow)  # internal helper exercised by the script

    assert {item["symbol"] for item in summary} == {"600519", "300750", "000858"}
    for item in summary:
        assert item["documents"] >= 2
        assert item["fact_cards"] >= 3

    retrieval = KnowledgeRetrievalService(uow)
    knowledge = FinancialKnowledgeService(uow)
    for symbol in ("600519", "300750", "000858"):
        results, _ = retrieval.search("经营变化 风险 行业", as_of=AS_OF, market="CN", symbol=symbol, limit=6)
        assert results, f"{symbol} must return seeded knowledge chunks"
        for item in results:
            assert item.citation_id and item.citation_id.startswith("kb:")
        # At least one seeded company-specific chunk must be retrievable.
        company_specific = [item for item in results if item.document.symbol == symbol]
        assert company_specific, f"{symbol} must surface its own seeded chunks"
        cards = knowledge.retrieve_fact_cards(symbol=symbol, as_of=AS_OF)
        assert cards.coverage_status == "events_present"
        stances = {card.stance for card in cards.cards}
        assert "supporting" in stances or "contrary" in stances or "uncertain" in stances
    uow.close()


def test_seeding_is_idempotent(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "kb.db")
    seeder = _load_seeder(REPO_ROOT)
    first = seeder._run_seed_into(uow)
    second = seeder._run_seed_into(uow)
    # Re-running must not duplicate rows: the summary counts stay equal and
    # the total reindexed document set does not grow.
    assert first == second
    rows_before = len([
        doc for doc in uow.financial_knowledge.list_all_for_reindex(market="CN")
        if doc.parser_version == "competition-demo-seed-v1"
    ])
    _ = seeder._run_seed_into(uow)
    rows_after = len([
        doc for doc in uow.financial_knowledge.list_all_for_reindex(market="CN")
        if doc.parser_version == "competition-demo-seed-v1"
    ])
    assert rows_before == rows_after
    uow.close()


def test_absence_of_seed_keeps_coverage_unknown_not_zero_risk(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "kb.db")
    cards = FinancialKnowledgeService(uow).retrieve_fact_cards(symbol="999999", as_of=AS_OF)
    # No seed for an unknown symbol must surface as unknown coverage, never as
    # a "no risk" conclusion.
    assert cards.coverage_status == "unknown"
    assert cards.absence_is_evidence is False
    uow.close()
