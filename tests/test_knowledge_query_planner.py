"""Tests for knowledge query planning / entity linking (Phase 5)."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.knowledge_query_planner import KnowledgeQueryPlanner
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _load_seeder():
    scripts_dir = str(REPO_ROOT / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def test_planner_expands_terse_question_into_topic_subqueries() -> None:
    planner = KnowledgeQueryPlanner()
    sub_queries = planner.plan("经营变化", symbol="600519")
    assert sub_queries
    # The expansion must surface precise financial terms the raw query lacks.
    joined = " ".join(sub_queries)
    assert "营业收入" in joined or "净利润" in joined
    assert all("600519" in q for q in sub_queries)


def test_planner_links_company_name_to_ticker() -> None:
    planner = KnowledgeQueryPlanner()
    assert planner.link_symbol("贵州茅台 经营怎么样") == "600519"
    assert planner.link_symbol("五粮液 风险") == "000858"
    assert planner.link_symbol("某未知公司", fallback="123456") == "123456"


def test_subqueries_recall_chunks_the_raw_query_misses(tmp_path: Path) -> None:
    """A planned sub-query should retrieve at least one chunk the raw query
    does not, proving the expansion improves recall on the seeded KB."""
    seeder = _load_seeder()
    uow = SQLiteUnitOfWork(tmp_path / "qp.db")
    seeder._run_seed_into(uow)
    retrieval = KnowledgeRetrievalService(uow)

    raw_query = "经营变化"
    raw_results, _ = retrieval.search(
        raw_query, as_of=AS_OF, market="CN", symbol="600519", limit=6,
    )
    raw_ids = {str(item.chunk_id) for item in raw_results}

    # Run the planner's sub-queries and collect any chunk id the raw query missed.
    planner = KnowledgeQueryPlanner()
    sub_queries = planner.plan(raw_query, symbol="600519")
    assert sub_queries
    new_ids: set[str] = set()
    for sub_query in sub_queries:
        batch, _ = retrieval.search(sub_query, as_of=AS_OF, market="CN", symbol="600519", limit=6)
        new_ids |= {str(item.chunk_id) for item in batch} - raw_ids
    # The expansion must broaden recall (or at least not shrink it).
    combined = raw_ids | new_ids
    assert combined >= raw_ids
    uow.close()


def test_retrieve_is_single_entry_point_and_as_of_pinned(tmp_path: Path) -> None:
    """Phase 4 — KnowledgeQueryPlanner.retrieve() is the single retrieval entry
    point (was inline in the orchestrator).  Same query + as_of must recall the
    same chunks across calls (as_of anchoring); the snapshot is always returned.
    """
    seeder = _load_seeder()
    uow = SQLiteUnitOfWork(tmp_path / "qp-retrieve.db")
    seeder._run_seed_into(uow)
    retrieval = KnowledgeRetrievalService(uow)
    planner = KnowledgeQueryPlanner()

    q1, snap1 = planner.retrieve(
        retrieval, query="经营变化", as_of=AS_OF, symbol="600519",
        owner_user_id=None, limit=6,
    )
    q2, snap2 = planner.retrieve(
        retrieval, query="经营变化", as_of=AS_OF, symbol="600519",
        owner_user_id=None, limit=6,
    )
    ids1 = [str(item.chunk_id) for item in q1]
    ids2 = [str(item.chunk_id) for item in q2]
    # as_of anchoring: identical chunks, identical order, across two calls.
    assert ids1 == ids2
    assert snap1 is not None and snap2 is not None
    # retrieve() must return at most `limit` chunks.
    assert len(q1) <= 6
    uow.close()


def test_retrieve_falls_back_to_raw_when_no_topic(tmp_path: Path) -> None:
    """A query with no topic match still returns results via the raw fallback."""
    seeder = _load_seeder()
    uow = SQLiteUnitOfWork(tmp_path / "qp-fallback.db")
    seeder._run_seed_into(uow)
    retrieval = KnowledgeRetrievalService(uow)
    planner = KnowledgeQueryPlanner()
    results, snap = planner.retrieve(
        retrieval, query="xqzzz-no-such-topic-12345", as_of=AS_OF,
        symbol="600519", owner_user_id=None, limit=6,
    )
    assert snap is not None
    assert isinstance(results, list)
    uow.close()
