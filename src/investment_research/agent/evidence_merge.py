"""Evidence merger for the long-term investment AI assistant.

This is the explicit "证据合并" step of the agent tool flow: it takes the
outputs of the knowledge-base search, the live web search, the long-term
model readings and the market calculation, and produces a single, classified
evidence structure that the plain-answer formatter and the audit trail share.

Every returned fact keeps its source.  Facts are classified into four
buckets so the final answer can distinguish what is confirmed, what is an
interpretation, where sources conflict, and what is still missing.  An empty
result is never silently turned into a "no risk" conclusion.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from investment_research.agent.answer_models import (
    ConflictArbitration,
    EvidenceClass,
    EvidenceItem,
    EvidenceMergeResult,
    PlainSource,
)

# Re-export shared models for backward-compatible imports.
__all__ = [
    "EvidenceMerger",
    "ConflictArbitration",
    "EvidenceMergeResult",
    "EvidenceClass",
    "EvidenceItem",
    "PlainSource",
]


_EXCESS_RETURN_TASKS = ("excess_return_120d", "excess_return_240d")
_DRAWDOWN_TASKS = ("future_max_drawdown_120d", "future_max_drawdown_240d")
_ALL_LONG_TERM_TASKS = (*_EXCESS_RETURN_TASKS, *_DRAWDOWN_TASKS)
_HORIZON_LABEL = {
    "excess_return_120d": "约 6 个月",
    "excess_return_240d": "约 12 个月",
    "future_max_drawdown_120d": "约 6 个月",
    "future_max_drawdown_240d": "约 12 个月",
}

_POSITIVE_CUES = ("增长", "回升", "改善", "超预期", "盈利提升", "扩张")
_NEGATIVE_CUES = ("下滑", "下降", "亏损", "不及预期", "承压", "收缩")


class EvidenceMerger:
    """Merge multi-source research outputs into classified, sourced evidence."""

    def merge(
        self,
        *,
        knowledge: Iterable[Mapping[str, object]] | None,
        web: Iterable[Mapping[str, object]] | None,
        readings: Mapping[str, Mapping[str, object]] | None,
        price_facts: Mapping[str, object] | None,
        scorecard: Mapping[str, object] | None,
        abstain_reasons: Iterable[str] | None = None,
    ) -> EvidenceMergeResult:
        knowledge_list = list(knowledge or [])
        web_list = list(web or [])
        readings_map = dict(readings or {})
        price = dict(price_facts or {})
        card = dict(scorecard or {})

        items: list[EvidenceItem] = []
        sources: list[PlainSource] = []
        seen_urls: set[str] = set()

        for entry in knowledge_list:
            text = _snippet(entry)
            if not text:
                continue
            source = _source_from_knowledge(entry)
            items.append(EvidenceItem(classification="confirmed_fact", text=text, sources=[source]))
            if source.url and source.url not in seen_urls:
                sources.append(source)
                seen_urls.add(source.url)

        for entry in web_list:
            text = _snippet(entry)
            if not text:
                continue
            verified = bool(entry.get("verified"))
            source = _source_from_web(entry)
            items.append(EvidenceItem(
                classification="confirmed_fact" if verified else "explanation",
                text=text, sources=[source],
            ))
            if source.url and source.url not in seen_urls:
                sources.append(source)
                seen_urls.add(source.url)

        for task in _ALL_LONG_TERM_TASKS:
            reading = readings_map.get(task)
            if isinstance(reading, Mapping) and reading.get("artifact_hash"):
                sources.append(PlainSource(
                    title=f"长期模型读数（{_HORIZON_LABEL[task]}）",
                    source="长期模型研究产物",
                    url=f"artifact://{str(reading.get('artifact_hash'))[:16]}",
                    published_at=_reading_date(reading),
                    kind="model",
                    citation_id=f"artifact:{str(reading.get('artifact_hash'))[:16]}",
                    note="研究展示读数，非验证预测结果。",
                ))

        if price.get("latest_close") is not None and price.get("trade_date"):
            sources.append(PlainSource(
                title="收盘行情与波动计算",
                source="平台行情计算",
                url="internal://market-observation",
                published_at=str(price.get("trade_date")),
                kind="calculation",
                note="基于免费公开收盘数据。",
            ))

        if not card:
            items.append(EvidenceItem(
                classification="missing",
                text="基本面评分尚未生成，本次回答不基于缺失评分强行下结论。",
            ))
        absent = set(_ALL_LONG_TERM_TASKS) - set(readings_map.keys())
        if absent:
            items.append(EvidenceItem(
                classification="missing",
                text="部分长期模型读数尚未生成，等待补齐后再解释。",
            ))
        abstain_list = [str(item) for item in (abstain_reasons or []) if item]
        if abstain_list:
            items.append(EvidenceItem(
                classification="missing",
                text="研究门禁暂未通过，已保留拒答原因供后续补齐。",
            ))

        conflict = False
        arbitration: ConflictArbitration | None = None
        if knowledge_list and web_list:
            arbitration = _arbitrate_conflict(knowledge_list, web_list)
            if arbitration is not None:
                items.append(EvidenceItem(
                    classification="conflict",
                    text=arbitration.reasoning,
                    sources=[
                        _source_from_knowledge(knowledge_list[0]),
                        _source_from_web(web_list[0]),
                    ],
                ))
                conflict = True

        return EvidenceMergeResult(
            evidence=items,
            sources=sources,
            conflict_present=conflict,
            missing_present=any(item.classification == "missing" for item in items),
            confirmed_count=sum(1 for item in items if item.classification == "confirmed_fact"),
            explanation_count=sum(1 for item in items if item.classification == "explanation"),
            arbitrations=[arbitration] if arbitration is not None else [],
        )


def _arbitrate_conflict(
    knowledge: list[Mapping[str, object]], web: list[Mapping[str, object]]
) -> ConflictArbitration | None:
    """Resolve a knowledge/web conflict by authority > recency > corroboration.

    Returns None when there is no actual directional conflict (see
    ``_detect_conflict``).  When sources tie on every axis the arbitration is
    ``unresolved`` and both views are preserved rather than silently picked.
    """
    if not _detect_conflict(knowledge, web):
        return None
    k_auth = max(_authority(entry) for entry in knowledge)
    w_auth = max(_authority(entry) for entry in web)
    k_date = max(_date_value(entry) for entry in knowledge)
    w_date = max(_date_value(entry) for entry in web)
    k_corr = len(knowledge)
    w_corr = len(web)

    authority_basis = f"知识库来源权威约 {k_auth:.2f}，联网来源约 {w_auth:.2f}"
    recency_basis = (
        f"知识库最新 {k_date or '未知'}，联网最新 {w_date or '未知'}"
    )
    corroboration_basis = f"知识库来源 {k_corr} 条，联网来源 {w_corr} 条"

    if k_auth > w_auth + 0.15:
        resolved = "knowledge"
        unresolved = False
        reasoning = (
            "知识库的历史资料与最新公开信息在经营方向上存在分歧；按权威优先，"
            "以权威更高的官方披露为参考方向，同时保留联网信息的发布日期与分歧。"
        )
    elif w_auth > k_auth + 0.15:
        resolved = "web"
        unresolved = False
        reasoning = (
            "知识库的历史资料与最新公开信息在经营方向上存在分歧；按权威优先，"
            "以权威更高的最新公开信息为参考方向，同时保留历史资料的发布日期。"
        )
    elif k_date and w_date and k_date != w_date:
        newer = "knowledge" if k_date > w_date else "web"
        resolved = newer
        unresolved = False
        reasoning = (
            "双方权威相近但发布日期不同；按时效优先，以更近期来源为参考方向，"
            "另一方仍保留以供交叉核对，不据此下买卖结论。"
        )
    elif k_corr != w_corr:
        side = "knowledge" if k_corr > w_corr else "web"
        resolved = side
        unresolved = False
        reasoning = (
            "权威与时效相近但来源数量不同；按印证度参考数量更多的一方，"
            "分歧未消除，仍保留双方观点。"
        )
    else:
        resolved = "unresolved"
        unresolved = True
        reasoning = (
            "知识库的历史资料与最新公开信息在经营方向上存在分歧，且权威、"
            "时效与印证度均相近；本次不偏向任一方，保留双方来源与发布日期，"
            "需后续更权威或更及时的披露再下判断。"
        )

    return ConflictArbitration(
        topic="经营方向",
        resolved_stance=resolved,
        reasoning=reasoning,
        authority_basis=authority_basis,
        recency_basis=recency_basis,
        corroboration_basis=corroboration_basis,
        unresolved=unresolved,
        sources=[
            str((entry.get("document") or entry).get("source_url") or entry.get("url") or "")
            for entry in (*knowledge, *web)
        ],
    )


def _authority(entry: Mapping[str, object]) -> float:
    """Normalized source authority for arbitration (0..1)."""
    for key in ("authority_score", "authority_level"):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            return min(1.0, float(value) / 5.0 if key == "authority_level" else float(value))
    verified = entry.get("verified")
    if verified:
        return 0.7
    # Knowledge docs default to 0.6 (official disclosure); web news to 0.2.
    return 0.6 if entry.get("document_type") or entry.get("source_name") else 0.2


def _date_value(entry: Mapping[str, object]) -> str | None:
    for key in ("published_at", "available_at", "date", "published_date"):
        value = entry.get(key)
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, str) and value:
            return value[:10]
    return None


def _detect_conflict(knowledge: list[Mapping[str, object]], web: list[Mapping[str, object]]) -> str | None:
    k_text = " ".join(_snippet(item) for item in knowledge)
    w_text = " ".join(_snippet(item) for item in web)
    k_pos = any(cue in k_text for cue in _POSITIVE_CUES)
    w_neg = any(cue in w_text for cue in _NEGATIVE_CUES)
    k_neg = any(cue in k_text for cue in _NEGATIVE_CUES)
    w_pos = any(cue in w_text for cue in _POSITIVE_CUES)
    if (k_pos and w_neg) or (k_neg and w_pos):
        return "知识库的历史资料与最新公开信息在经营方向上存在分歧，需要交叉核对来源与发布日期后再下判断。"
    return None


def _snippet(entry: Mapping[str, object]) -> str:
    for key in ("snippet", "content", "summary", "text"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:400]
    return ""


def _source_from_knowledge(entry: Mapping[str, object]) -> PlainSource:
    document = entry.get("document") if isinstance(entry.get("document"), Mapping) else entry
    return PlainSource(
        title=str(document.get("title") or entry.get("title") or "金融知识资料")[:200],
        source=str(document.get("source_name") or entry.get("source") or "知识库")[:120],
        url=str(document.get("source_url") or entry.get("url") or "internal://knowledge")[:500],
        published_at=_iso_date(document.get("published_at") or entry.get("published_at")),
        kind="knowledge",
        citation_id=str(entry.get("citation_id") or "") or None,
    )


def _source_from_web(entry: Mapping[str, object]) -> PlainSource:
    return PlainSource(
        title=str(entry.get("title") or "联网检索资料")[:200],
        source=str(entry.get("source") or entry.get("publisher") or "联网搜索")[:120],
        url=str(entry.get("url") or "internal://web-search")[:500],
        published_at=_iso_date(entry.get("published_at") or entry.get("date")),
        kind="news",
        citation_id=str(entry.get("citation_id") or "") or None,
        note="来自联网搜索，需结合发布日期与来源权威性理解。" if not entry.get("verified") else None,
    )


def _reading_date(reading: Mapping[str, object]) -> str | None:
    for key in ("data_as_of", "as_of_date"):
        value = reading.get(key)
        if isinstance(value, str) and value:
            return value[:10]
    return None


def _iso_date(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None
