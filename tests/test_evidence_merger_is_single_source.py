"""Phase 1 acceptance: PlainAnswerBuilder delegates to EvidenceMerger as the
single evidence layer.

Before Phase 1 the builder kept a parallel ``_classify_evidence`` /
``_collect_sources`` path that classified evidence and collected sources
independently of ``EvidenceMerger``, so the dashboard snapshot and the AI
answer could disagree on what counts as a confirmed fact / conflict / missing
item.  These tests pin the single-source contract:

* the parallel methods are gone;
* ``build()`` routes evidence + sources + arbitrations through
  ``EvidenceMerger.merge`` exactly once;
* the evidence / sources / arbitrations on the returned answer are byte-for-byte
  what the merger produces directly (no divergent second pass).
"""
from __future__ import annotations

import investment_research.agent.plain_answer as pa
from investment_research.agent.evidence_merge import EvidenceMerger
from investment_research.agent.plain_answer import PlainAnswerBuilder

from test_plain_answer import _builder, _full_readings, _full_scorecard

_KNOWLEDGE = [
    {
        "snippet": "公司净利润同比增长，盈利改善",
        "document": {
            "title": "季报",
            "source_name": "知识库",
            "source_url": "https://kb.example/1",
            "published_at": "2026-06-30",
        },
        "citation_id": "kb:1",
    }
]
_WEB = [
    {
        "title": "行业承压",
        "source": "新闻",
        "url": "https://news.example/1",
        "published_at": "2026-08-10",
        "snippet": "公司利润下滑，行业承压",
    }
]
_PRICE = {"latest_close": 1680.0, "trade_date": "2026-08-15"}


def test_parallel_evidence_path_methods_are_removed() -> None:
    """The stale parallel classification / source-collection methods are gone."""
    for name in (
        "_classify_evidence",
        "_collect_sources",
        "_detect_conflict",
        "_source_from_knowledge",
        "_source_from_web",
        "_iso_date",
    ):
        assert not hasattr(PlainAnswerBuilder, name), (
            f"stale parallel method {name!r} still present on PlainAnswerBuilder"
        )


def test_build_delegates_to_evidence_merger_exactly_once(monkeypatch) -> None:
    """build() must route evidence + sources + arbitrations through EvidenceMerger."""
    calls: list[dict[str, object]] = []

    class _SpyingMerger(EvidenceMerger):
        def merge(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            return super().merge(**kwargs)

    monkeypatch.setattr(pa, "EvidenceMerger", _SpyingMerger)

    answer = _builder().build(
        symbol="600519",
        asset_name="示例公司",
        task_text="经营变化",
        scorecard=_full_scorecard(),
        model_readings=_full_readings(),
        knowledge_results=_KNOWLEDGE,
        web_results=_WEB,
        price_facts=_PRICE,
        data_as_of="2026-08-15",
        abstain_reasons=None,
    )

    assert len(calls) == 1, (
        f"EvidenceMerger.merge should be called exactly once, got {len(calls)}"
    )
    call = calls[0]
    assert call["scorecard"] == _full_scorecard()
    assert call["price_facts"] == _PRICE
    assert call["knowledge"] == _KNOWLEDGE
    assert call["web"] == _WEB

    # The evidence / sources / arbitrations on the answer must equal what the
    # merger produces directly — build() must not run a divergent second pass.
    direct = EvidenceMerger().merge(
        knowledge=_KNOWLEDGE,
        web=_WEB,
        readings=_full_readings(),
        price_facts=_PRICE,
        scorecard=_full_scorecard(),
        abstain_reasons=None,
    )
    assert [e.model_dump(mode="json") for e in answer.evidence] == [
        e.model_dump(mode="json") for e in direct.evidence
    ]
    assert [s.model_dump(mode="json") for s in answer.sources] == [
        s.model_dump(mode="json") for s in direct.sources
    ]
    assert answer.arbitrations == [a.model_dump(mode="json") for a in direct.arbitrations]


def test_no_conflict_case_still_single_sourced(monkeypatch) -> None:
    """Without a knowledge/web conflict the builder still goes through the merger."""
    calls: list[dict[str, object]] = []

    class _SpyingMerger(EvidenceMerger):
        def merge(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)
            return super().merge(**kwargs)

    monkeypatch.setattr(pa, "EvidenceMerger", _SpyingMerger)

    answer = _builder().build(
        symbol="600519",
        asset_name="示例公司",
        task_text="经营怎么样",
        scorecard=None,
        model_readings=_full_readings(),
        knowledge_results=None,
        web_results=None,
        price_facts=_PRICE,
        data_as_of="2026-08-15",
    )
    assert len(calls) == 1
    # No conflict present -> no arbitration, but the missing-scorecard evidence
    # still flows from the single merger layer (not a parallel classifier).
    assert answer.arbitrations == []
    assert any(item.classification == "missing" for item in answer.evidence)
