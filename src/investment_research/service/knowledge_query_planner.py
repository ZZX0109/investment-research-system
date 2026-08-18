"""Query planning and entity linking for knowledge retrieval (Phase 5).

The raw user question ("经营变化") is often too terse to retrieve the precise
financial chunks the answer needs.  The planner expands it into 1-2 topic-aware
sub-queries and links a company name to its ticker so the retrieval stage can
recall chunks the raw query would miss.  It is deterministic and dependency-free;
when planning yields no sub-queries the caller falls back to the raw query.
"""
from __future__ import annotations

from typing import Iterable

# Name -> ticker aliases for the demo universe (handles 曾用名/简称/全称).
# Production would source this from cn_security_name_history; here it is a
# small, auditable alias map for the three demonstration companies.
NAME_ALIASES: dict[str, str] = {
    "贵州茅台": "600519", "茅台": "600519", "示例白酒": "600519", "600519": "600519",
    "宁德时代": "300750", "示例电池": "300750", "300750": "300750",
    "五粮液": "000858", "示例食饮": "000858", "000858": "000858",
}

_TOPIC_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "经营": ("营业收入 同比", "净利润 经营", "毛利率"),
    "经营变化": ("营业收入 同比", "净利润 经营", "毛利率"),
    "风险": ("行业竞争", "毛利率 下滑", "成本 波动", "产能 过剩"),
    "估值": ("估值 行业景气度", "估值位置"),
    "分红": ("分红 股东回报", "现金分红"),
    "行业": ("行业景气度 分歧", "行业竞争"),
    "财务": ("营业总收入", "净利润", "毛利率"),
}


class KnowledgeQueryPlanner:
    """Expand a user question into retrieval sub-queries + link the ticker."""

    def link_symbol(self, text: str, *, fallback: str | None = None) -> str | None:
        """Resolve a company name or code in ``text`` to a ticker."""
        if not text:
            return fallback
        for alias, ticker in NAME_ALIASES.items():
            if alias in text:
                return ticker
        return fallback

    def plan(self, question: str, *, symbol: str | None = None) -> list[str]:
        """Return 1-2 topic-aware sub-queries; empty when no topic matches."""
        if not question:
            return []
        sub_queries: list[str] = []
        seen: set[str] = set()
        for topic, expansion in _TOPIC_EXPANSIONS.items():
            if topic in question:
                for term in expansion:
                    composed = f"{symbol or ''} {term}".strip() if symbol else term
                    if composed not in seen:
                        seen.add(composed)
                        sub_queries.append(composed)
                    if len(sub_queries) >= 2:
                        break
                if len(sub_queries) >= 2:
                    break
        return sub_queries

    def retrieve(
        self,
        retrieval_service,
        *,
        query: str,
        as_of,
        symbol: str | None,
        owner_user_id,
        limit: int = 6,
    ):
        """Phase 4 — single retrieval entry point (was inline in the orchestrator).

        Plan 1-2 topic-aware sub-queries from ``query``, run each through the
        retrieval service (pinned to ``as_of`` so the same question recalls the
        same chunks across runs / wall-clock), merge by chunk id, and fall back
        to a single raw search when planning yields no batches.  Returns
        ``(results, retrieval_snapshot)`` mirroring
        ``KnowledgeRetrievalService.search``.
        """
        queries = plan_retrieval_queries(query, symbol=symbol)
        batches: list[list] = []
        snapshots: list = []
        for sub_query in queries[:3]:
            batch, snap = retrieval_service.search(
                sub_query, as_of=as_of, market="CN", symbol=symbol,
                owner_user_id=owner_user_id, limit=limit,
            )
            if batch:
                batches.append(batch)
                snapshots.append(snap)
        merged = merge_search_results(batches)
        if snapshots:
            return merged[:limit], snapshots[0]
        return retrieval_service.search(
            query, as_of=as_of, market="CN", symbol=symbol,
            owner_user_id=owner_user_id, limit=limit,
        )


def plan_retrieval_queries(
    question: str, *, symbol: str | None = None
) -> list[str]:
    """Convenience: expand a question, falling back to the raw question."""
    planned = KnowledgeQueryPlanner().plan(question, symbol=symbol)
    fallback = (f"{symbol} {question}".strip() if symbol else question)
    queries = list(dict.fromkeys([*planned, fallback]))  # de-dup, preserve order
    return queries


def merge_search_results(results: Iterable[list]) -> list:
    """De-duplicate merged search results by chunk id, preserving best rank."""
    seen: set[str] = set()
    merged = []
    for batch in results:
        for item in batch:
            chunk_key = str(getattr(item, "chunk_id", "") or id(item))
            if chunk_key in seen:
                continue
            seen.add(chunk_key)
            merged.append(item)
    return merged
