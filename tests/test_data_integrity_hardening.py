"""Phase 7 — data-integrity hardening that the persistent dashboard depends on.

Guards two latent bugs the spec flagged as 承重 under the "持久仪表盘 +
对话式 AI" chain:

* #2 — ``DeterministicReranker`` anchored recency on wall-clock
  ``datetime.now()``, so the same query at the same ``as_of`` re-ranked
  differently across turns (the dashboard would surface different chunks for
  the same question).  Now anchored on ``as_of``.
* #3 — the line-item ``content_hash`` formula was copied verbatim in the
  seeder and the ingest service; a drift would silently break PIT dedup /
  supersede-by-revision and let the dashboard render two revisions of the same
  figure at once.  Now a single source on ``FinancialLineItem``.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_research.domain.knowledge import FinancialLineItem
from investment_research.service.financial_knowledge import FinancialKnowledgeService
from investment_research.service.knowledge_reranker import DeterministicReranker

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _candidate(*, title: str, snippet: str, final_score: float, published_at: datetime):
    from investment_research.domain.knowledge import FinancialKnowledgeDocument, KnowledgeSearchResult

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


def test_deterministic_reranker_anchors_recency_on_as_of() -> None:
    """as_of controls the recency anchor: a later as_of makes an older chunk
    score lower (more aged) — proving the anchor is the pinned as_of, not the
    wall-clock time the run happened to execute at."""
    candidate = _candidate(
        title="经营情况讨论", snippet="2025 年公司经营变化：营收同比增长约 9.5%。",
        final_score=0.3, published_at=datetime(2026, 2, 17, tzinfo=timezone.utc),  # 180 days before AS_OF
    )
    early = DeterministicReranker().rerank("经营变化", [candidate], top_k=1, as_of=AS_OF)[0]
    later_as_of = datetime(2026, 12, 1, tzinfo=timezone.utc)  # ~288 days after publication
    later = DeterministicReranker().rerank("经营变化", [candidate], top_k=1, as_of=later_as_of)[0]

    assert early.rerank_score > later.rerank_score  # older anchor -> more aged -> lower recency
    # The recency contribution at AS_OF (180 days) is exactly 1/(1+180/180)=0.5.
    early_recency = 1.0 / (1.0 + 180.0 / 180.0)
    overlap_norm = 1.0  # "经营变化" fully matches
    expected_early = 0.55 * overlap_norm + 0.20 * 0.8 + 0.15 * early_recency + 0.10 * 0.3
    assert abs(early.rerank_score - expected_early) < 1e-9


def test_deterministic_reranker_is_reproducible_across_wall_clock() -> None:
    """The persistent-dashboard guarantee: the same query at the same as_of
    re-ranks identically regardless of when the run executes."""
    candidates = [
        _candidate(
            title="经营情况讨论", snippet="2025 年公司经营变化：营收同比增长约 9.5%。",
            final_score=0.3, published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        ),
        _candidate(
            title="公司章程修订", snippet="本次修订涉及治理结构条款，不涉及经营。",
            final_score=2.5, published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ),
    ]
    first = DeterministicReranker().rerank("经营变化 风险", candidates, top_k=2, as_of=AS_OF)
    second = DeterministicReranker().rerank("经营变化 风险", candidates, top_k=2, as_of=AS_OF)
    assert [c.document.title for c in first] == [c.document.title for c in second]
    assert [c.rerank_score for c in first] == [c.rerank_score for c in second]


def _load_seeder(project_root: Path):
    scripts_dir = str(project_root / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def test_line_item_content_hash_is_single_source() -> None:
    """The seeder's hash, the service's hash, the static factory, and the
    instance recompute are all the same single source — a drift in any one
    would silently break PIT dedup / supersede-by-revision."""
    seeder = _load_seeder(REPO_ROOT)
    kwargs = dict(
        symbol="600519", period="2025FY", metric="revenue",
        source_url="https://example-exchange.com/600519",
        value=1743.0, unit="亿元", scale=1.0,
        published_at=datetime(2025, 8, 30, tzinfo=timezone.utc),
        metric_label="营业收入",
    )
    seeder_hash = seeder._line_item_hash(**kwargs)
    static_hash = FinancialLineItem.content_hash_of(**kwargs)

    item = FinancialLineItem(
        market="CN", symbol="600519", period="2025FY", metric="revenue", metric_label="营业收入",
        value=1743.0, unit="亿元", scale=1.0, yoy_pct=8.0, qoq_pct=3.0,
        source_name="交易所公告", source_url="https://example-exchange.com/600519",
        published_at=datetime(2025, 8, 30, tzinfo=timezone.utc),
        available_at=datetime(2025, 8, 30, tzinfo=timezone.utc),
        valid_from=datetime(2025, 8, 30, tzinfo=timezone.utc),
        content_hash=static_hash,
    )
    assert seeder_hash == static_hash == item.compute_content_hash()
    # The service's ingest-time validation uses the same single source.
    assert FinancialKnowledgeService._line_item_hash(item) == static_hash


def test_line_item_rejects_mismatched_content_hash() -> None:
    """A hand-typed hash that does not match the single-source formula is
    rejected at construction — catches future drift early rather than letting
    dedup silently break."""
    import pytest

    with pytest.raises(ValueError, match="content_hash does not match"):
        FinancialLineItem(
            market="CN", symbol="600519", period="2025FY", metric="revenue", metric_label="营业收入",
            value=1743.0, unit="亿元", scale=1.0, yoy_pct=8.0,
            source_name="交易所公告", source_url="https://example-exchange.com/600519",
            published_at=datetime(2025, 8, 30, tzinfo=timezone.utc),
            available_at=datetime(2025, 8, 30, tzinfo=timezone.utc),
            valid_from=datetime(2025, 8, 30, tzinfo=timezone.utc),
            content_hash="0" * 64,  # wrong
        )
