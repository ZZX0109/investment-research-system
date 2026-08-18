"""Tests for the cross-encoder rerank stage (Phase 3).

Guards the "no rerank -> precision" hardening: a second stage re-scores the
first-stage candidates, every returned item carries a ``rerank_score``, the
retrieval snapshot records which model was used, and the optional local
cross-encoder degrades to a deterministic fallback without crashing.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_research.domain.knowledge import FinancialKnowledgeDocument, KnowledgeSearchResult
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService
from investment_research.service.knowledge_reranker import (
    DeterministicReranker,
    LocalBGEReranker,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _load_seeder():
    scripts_dir = str(REPO_ROOT / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def _result(*, title: str, snippet: str, final_score: float, published_at: datetime) -> KnowledgeSearchResult:
    document = FinancialKnowledgeDocument(
        title=title, content=snippet, source_name="交易所公告",
        source_url=f"https://example-exchange.com/{title}", market="CN", symbol="600519",
        document_type="annual_report_excerpt", published_at=published_at, effective_from=published_at,
        collected_at=published_at, available_at=published_at, first_observed_at=published_at,
        content_hash="x" * 64, data_tier="research_pit", source_kind="official_public",
        copyright_status="official_public", content_scope="full_text", authority_level=4,
    )
    return KnowledgeSearchResult(
        document=document, score=final_score, matched_terms=[], chunk_id=None,
        citation_id="kb:test", snippet=snippet, page_or_section=None,
        lexical_score=final_score, semantic_score=None, authority_score=0.8,
        final_score=final_score,
    )


def test_deterministic_reranker_promotes_query_overlap() -> None:
    # High first-stage score but the snippet does not mention the query topic.
    high_lexical = _result(
        title="公司章程修订", snippet="本次修订涉及治理结构条款，不涉及经营。",
        final_score=2.5, published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    # Lower first-stage score but the snippet directly discusses 经营变化.
    on_topic = _result(
        title="经营情况讨论", snippet="2025 年公司经营变化：营收同比增长约 9.5%。",
        final_score=0.3, published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    reranked = DeterministicReranker().rerank("经营变化 风险", [high_lexical, on_topic], top_k=2)
    assert reranked[0].document.title == "经营情况讨论"
    assert reranked[0].rerank_score is not None
    assert reranked[0].rerank_score > reranked[1].rerank_score  # type: ignore[operator]


def test_rerank_is_recorded_on_retrieval_snapshot(tmp_path: Path) -> None:
    seeder = _load_seeder()
    uow = SQLiteUnitOfWork(tmp_path / "rerank.db")
    seeder._run_seed_into(uow)
    # Inject a fake reranker that tags every item so we can prove the head was
    # re-scored by the second stage and recorded on the snapshot.
    class _TaggingReranker:
        model_name = "fake-tagging-reranker"
        available = True

        def rerank(self, query, candidates, *, top_k, as_of=None):  # noqa: ANN001
            return [item.model_copy(update={"rerank_score": 0.99}) for item in candidates[:top_k]]

    retrieval = KnowledgeRetrievalService(uow, reranker=_TaggingReranker())  # type: ignore[arg-type]
    results, snapshot = retrieval.search("经营变化 风险", as_of=AS_OF, market="CN", symbol="600519", limit=4)
    assert snapshot.rerank_model == "fake-tagging-reranker"
    assert results
    for item in results:
        assert item.rerank_score == 0.99
    uow.close()


def test_unavailable_local_reranker_falls_back_to_deterministic() -> None:
    reranker = LocalBGEReranker()
    reranker._load()  # noqa: SLF001 — probe availability
    # Whether or not FlagEmbedding is installed, rerank must never raise and
    # every returned item must carry a rerank_score.
    item = _result(
        title="经营情况讨论", snippet="公司经营变化与风险讨论。",
        final_score=0.5, published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    result = reranker.rerank("经营变化", [item], top_k=1)
    assert result and result[0].rerank_score is not None
