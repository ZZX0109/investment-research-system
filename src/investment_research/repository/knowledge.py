from __future__ import annotations

import re
from datetime import datetime

from investment_research.domain.knowledge import FinancialKnowledgeDocument, KnowledgeSearchResult


class FinancialKnowledgeRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add(self, document: FinancialKnowledgeDocument) -> FinancialKnowledgeDocument:
        existing = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_documents WHERE content_hash=?",
            (document.content_hash,),
        ).fetchone()
        if existing is not None:
            return FinancialKnowledgeDocument.model_validate_json(str(existing[0]))
        self.connection.execute(
            "INSERT INTO financial_knowledge_documents "
            "(id,market,symbol,document_type,published_at,available_at,status,content_hash,payload_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(document.id), document.market, document.symbol, document.document_type,
                document.published_at.isoformat(), document.available_at.isoformat(),
                document.status, document.content_hash, document.model_dump_json(),
            ),
        )
        self.connection.commit()
        return document

    def get(self, document_id: str) -> FinancialKnowledgeDocument | None:
        row = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_documents WHERE id=?",
            (document_id,),
        ).fetchone()
        return None if row is None else FinancialKnowledgeDocument.model_validate_json(str(row[0]))

    def list(self, *, market: str = "CN", symbol: str | None = None) -> list[FinancialKnowledgeDocument]:
        if symbol:
            rows = self.connection.execute(
                "SELECT payload_json FROM financial_knowledge_documents "
                "WHERE market=? AND (symbol IS NULL OR symbol=?) ORDER BY published_at DESC",
                (market, symbol),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM financial_knowledge_documents WHERE market=? ORDER BY published_at DESC",
                (market,),
            ).fetchall()
        return [FinancialKnowledgeDocument.model_validate_json(str(row[0])) for row in rows]

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        market: str = "CN",
        symbol: str | None = None,
        limit: int = 6,
    ) -> list[KnowledgeSearchResult]:
        terms = self._query_terms(query)
        candidates = self.list(market=market, symbol=symbol)
        scored: list[KnowledgeSearchResult] = []
        for document in candidates:
            if document.status != "active" or document.available_at > as_of:
                continue
            if document.effective_from > as_of or (document.effective_to and document.effective_to < as_of):
                continue
            title = document.title.lower()
            content = document.content.lower()
            matched = [term for term in terms if term in title or term in content]
            if not matched and terms:
                continue
            score = sum(3.0 if term in title else 1.0 for term in matched)
            if document.symbol and symbol and document.symbol == symbol:
                score += 2.0
            scored.append(KnowledgeSearchResult(document=document, score=score, matched_terms=matched))
        return sorted(scored, key=lambda item: (item.score, item.document.published_at), reverse=True)[:limit]

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        """Create useful bounded terms for both Chinese and Latin text.

        Treating a complete Chinese sentence as one token makes an otherwise
        valid knowledge search return nothing.  Short n-grams keep this simple,
        deterministic and dependency-free.
        """
        value = query.lower()
        terms: list[str] = re.findall(r"[a-z0-9_]{2,}", value)
        for segment in re.findall(r"[\u4e00-\u9fff]+", value):
            if len(segment) <= 4:
                terms.append(segment)
            for size in (2, 3, 4):
                terms.extend(segment[index:index + size] for index in range(max(0, len(segment) - size + 1)))
        return list(dict.fromkeys(terms))[:80]
