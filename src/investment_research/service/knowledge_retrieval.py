"""Local, owner-aware hybrid retrieval for the financial knowledge catalog."""
from __future__ import annotations

from array import array
import hashlib
import importlib.util
import math
import os
import re
from datetime import datetime
from typing import Protocol
from uuid import UUID

from investment_research.domain.knowledge import (
    FinancialKnowledgeDocument,
    KnowledgeChunk,
    KnowledgeEmbedding,
    KnowledgeRetrievalSnapshot,
    KnowledgeSearchResult,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
EMBEDDING_REVISION = "v1.5"


class KnowledgeEmbedder(Protocol):
    model_name: str
    model_revision: str

    @property
    def available(self) -> bool: ...

    def encode_query(self, text: str) -> list[float]: ...

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...


class LocalBGEEmbedder:
    """Lazy local BGE adapter. It never invokes a paid or remote inference API."""

    _shared_models: dict[str, object] = {}

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.getenv("KNOWLEDGE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        self.model_revision = EMBEDDING_REVISION
        self._model = None
        self._error: str | None = None

    @property
    def installed(self) -> bool:
        """Report dependency presence without loading or downloading a model."""
        return importlib.util.find_spec("sentence_transformers") is not None

    @property
    def status(self) -> dict[str, object]:
        return {
            "installed": self.installed,
            "loaded": self._model is not None,
            "available": self._model is not None,
            "model": self.model_name,
            "reason": self._error if self._error else None if self.installed else "sentence_transformers_not_installed",
        }

    @property
    def available(self) -> bool:
        return self._load() is not None

    @property
    def unavailable_reason(self) -> str | None:
        self._load()
        return self._error

    def encode_query(self, text: str) -> list[float]:
        model = self._require()
        if hasattr(model, "encode_query"):
            value = model.encode_query(text, normalize_embeddings=True)
        else:
            value = model.encode(text, normalize_embeddings=True)
        return [float(item) for item in value]

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._require()
        if hasattr(model, "encode_document"):
            values = model.encode_document(texts, normalize_embeddings=True)
        else:
            values = model.encode(texts, normalize_embeddings=True)
        return [[float(item) for item in value] for value in values]

    def _require(self):
        model = self._load()
        if model is None:
            raise RuntimeError(self._error or "local embedding model unavailable")
        return model

    def _load(self):
        if self._model is not None or self._error is not None:
            return self._model
        if self.model_name in self._shared_models:
            self._model = self._shared_models[self.model_name]
            return self._model
        try:
            from sentence_transformers import SentenceTransformer

            # Background reindexing may download the public model. API coverage
            # checks never call this loader and therefore never block on network.
            self._model = SentenceTransformer(self.model_name)
            self._shared_models[self.model_name] = self._model
        except Exception as exc:  # optional dependency/model download failure
            self._error = f"{type(exc).__name__}:{exc}"
        return self._model


class KnowledgeChunker:
    def __init__(self, *, chunk_chars: int = 600, overlap_chars: int = 80) -> None:
        if chunk_chars < 160 or overlap_chars < 0 or overlap_chars >= chunk_chars:
            raise ValueError("invalid knowledge chunk configuration")
        self.chunk_chars = chunk_chars
        self.overlap_chars = overlap_chars

    def split(self, document: FinancialKnowledgeDocument) -> list[KnowledgeChunk]:
        sections = self._sections(document.content, document.document_type)
        chunks: list[KnowledgeChunk] = []
        index = 0
        for section, page, content in sections:
            normalized = re.sub(r"[ \t]+", " ", content).strip()
            if not normalized:
                continue
            start = 0
            while start < len(normalized):
                end = min(len(normalized), start + self.chunk_chars)
                if end < len(normalized):
                    boundary = max(normalized.rfind("。", start, end), normalized.rfind("\n", start, end))
                    if boundary > start + self.chunk_chars // 2:
                        end = boundary + 1
                value = normalized[start:end].strip()
                if value:
                    chunks.append(KnowledgeChunk(
                        document_id=document.id, revision=document.revision, chunk_index=index,
                        content=value, section=section, page_start=page, page_end=page,
                        token_estimate=max(1, len(value) // 2),
                        content_hash=hashlib.sha256(value.encode()).hexdigest(),
                        owner_user_id=document.owner_user_id, access_scope=document.access_scope,
                    ))
                    index += 1
                if end >= len(normalized):
                    break
                start = max(start + 1, end - self.overlap_chars)
        return chunks

    @staticmethod
    def _sections(content: str, document_type: str) -> list[tuple[str | None, int | None, str]]:
        page_matches = list(re.finditer(r"\[page\s+(\d+)\]\s*", content, flags=re.IGNORECASE))
        if page_matches:
            output = []
            for index, match in enumerate(page_matches):
                end = page_matches[index + 1].start() if index + 1 < len(page_matches) else len(content)
                output.append((None, int(match.group(1)), content[match.end():end]))
            return output
        if document_type in {"regulation", "market_rule", "disclosure_rule"}:
            pattern = re.compile(r"(?=第[一二三四五六七八九十百千0-9]+[章节条])")
            parts = [part.strip() for part in pattern.split(content) if part.strip()]
            if len(parts) > 1:
                return [(part.splitlines()[0][:120], None, part) for part in parts]
        sections = re.split(r"\n(?=(?:一、|二、|三、|四、|五、|六、|七、|八、|九、|十、|\d+[.、]))", content)
        return [((part.splitlines()[0][:120] if "\n" in part else None), None, part) for part in sections if part.strip()]


class KnowledgeRetrievalService:
    def __init__(
        self, uow: SQLiteUnitOfWork, *, embedder: KnowledgeEmbedder | None = None,
        chunker: KnowledgeChunker | None = None,
        reranker: "KnowledgeReranker | None" = None,
    ) -> None:
        self.uow = uow
        self.embedder = embedder or LocalBGEEmbedder()
        self.chunker = chunker or KnowledgeChunker()
        self._reranker = reranker
        self._reranker_model: str | None = None

    def index_document(self, document: FinancialKnowledgeDocument) -> list[KnowledgeChunk]:
        chunks = self.chunker.split(document)
        self.uow.financial_knowledge.replace_chunks(document, chunks)
        if self.embedder.available and chunks:
            vectors = self.embedder.encode_documents([chunk.content for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                blob = array("f", vector).tobytes()
                metadata = KnowledgeEmbedding(
                    chunk_id=chunk.id, model_name=self.embedder.model_name,
                    model_revision=self.embedder.model_revision, dimension=len(vector),
                    vector_hash=hashlib.sha256(blob).hexdigest(),
                    shard_key=f"{document.market.lower()}/{document.published_at.year}/{document.document_type}",
                )
                self.uow.financial_knowledge.add_embedding(metadata, vector)
        return chunks

    def search(
        self, query: str, *, as_of: datetime, market: str = "CN", symbol: str | None = None,
        owner_user_id: UUID | None = None, document_type: str | None = None,
        source: str | None = None, limit: int = 6, offset: int = 0,
    ) -> tuple[list[KnowledgeSearchResult], KnowledgeRetrievalSnapshot]:
        lexical = self.uow.financial_knowledge.search(
            query, as_of=as_of, market=market, symbol=symbol, owner_user_id=owner_user_id,
            document_type=document_type, source=source, limit=max(limit * 8, 80), offset=0,
        )
        by_chunk = {str(item.chunk_id): item for item in lexical if item.chunk_id is not None}
        mode = "lexical"
        if self.embedder.available:
            candidates = self.uow.financial_knowledge.candidate_chunks(
                as_of=as_of, market=market, symbol=symbol, owner_user_id=owner_user_id,
                document_type=document_type, source=source,
            )[:2000]
            self._ensure_embeddings(candidates)
            ids = [str(chunk.id) for _, chunk in candidates]
            stored = self.uow.financial_knowledge.embeddings_for_chunks(ids, model_name=self.embedder.model_name)
            query_vector = self.embedder.encode_query(query)
            terms = self.uow.financial_knowledge._query_terms(query)
            for document, chunk in candidates:
                vector = stored.get(str(chunk.id))
                if vector is None:
                    continue
                semantic = self._cosine(query_vector, vector)
                current = by_chunk.get(str(chunk.id))
                lexical_score = 0.0 if current is None else current.lexical_score
                authority = document.authority_level / 5.0
                symbol_bonus = 0.08 if symbol and document.symbol == symbol else 0.0
                lexical_norm = min(1.0, lexical_score / max(1.0, len(terms) * 2.0))
                final = 0.42 * lexical_norm + 0.43 * max(0.0, semantic) + 0.10 * authority + symbol_bonus
                by_chunk[str(chunk.id)] = KnowledgeSearchResult(
                    document=document, score=final, matched_terms=[] if current is None else current.matched_terms,
                    chunk_id=chunk.id, citation_id=f"kb:{chunk.id}:{chunk.content_hash[:12]}",
                    snippet=chunk.content[:900], page_or_section=self.uow.financial_knowledge._page_or_section(chunk),
                    lexical_score=lexical_score, semantic_score=semantic, authority_score=authority,
                    final_score=final,
                    coverage_status="complete" if document.content_scope == "full_text" else "partial",
                    pit_status="assumed" if document.visibility_assumption else "proven",
                )
            mode = "hybrid"
        ranked = sorted(by_chunk.values(), key=lambda item: (item.final_score, item.document.published_at), reverse=True)
        # Second-stage cross-encoder rerank over the top-N first-stage hits so a
        # high-lexical but less-relevant chunk is pushed below a more relevant one.
        rerank_pool = ranked[: max(limit * 5, 30)]
        reranker = self._resolve_reranker()
        if reranker is not None and rerank_pool:
            reranked = reranker.rerank(query, rerank_pool, top_k=len(rerank_pool), as_of=as_of)
            # Re-merge reranked head with any tail items the reranker did not see,
            # preserving the first-stage order for the tail and the rerank order
            # for the head.
            reranked_ids = {str(item.chunk_id) for item in reranked if item.chunk_id is not None}
            tail = [item for item in ranked if str(item.chunk_id) not in reranked_ids]
            results = self._diversify(reranked + tail)[offset:offset + limit]
            self._reranker_model = reranker.model_name
        else:
            results = self._diversify(ranked)[offset:offset + limit]
        snapshot = KnowledgeRetrievalSnapshot(
            owner_user_id=owner_user_id, query_hash=hashlib.sha256(query.encode()).hexdigest(),
            query_text=query, market=market, symbol=symbol, as_of=as_of,
            retrieval_mode=mode, embedding_model=self.embedder.model_name if mode == "hybrid" else None,
            rerank_model=self._reranker_model,
            result_chunk_ids=[item.chunk_id for item in results if item.chunk_id is not None],
            result_citation_ids=[item.citation_id for item in results if item.citation_id is not None],
        )
        self.uow.financial_knowledge.add_retrieval_snapshot(snapshot)
        return results, snapshot

    def _resolve_reranker(self) -> "KnowledgeReranker | None":
        """Lazily resolve a reranker once; failures stick to deterministic fallback."""
        if self._reranker is not None:
            return self._reranker
        from investment_research.service.knowledge_reranker import resolve_reranker
        self._reranker = resolve_reranker()
        self._reranker_model = self._reranker.model_name
        return self._reranker

    def _ensure_embeddings(self, candidates: list[tuple[FinancialKnowledgeDocument, KnowledgeChunk]]) -> None:
        ids = [str(chunk.id) for _, chunk in candidates]
        existing = self.uow.financial_knowledge.embeddings_for_chunks(ids, model_name=self.embedder.model_name)
        missing = [(document, chunk) for document, chunk in candidates if str(chunk.id) not in existing]
        for batch_start in range(0, len(missing), 64):
            batch = missing[batch_start:batch_start + 64]
            vectors = self.embedder.encode_documents([chunk.content for _, chunk in batch])
            for (document, chunk), vector in zip(batch, vectors, strict=True):
                blob = array("f", vector).tobytes()
                self.uow.financial_knowledge.add_embedding(KnowledgeEmbedding(
                    chunk_id=chunk.id, model_name=self.embedder.model_name,
                    model_revision=self.embedder.model_revision, dimension=len(vector),
                    vector_hash=hashlib.sha256(blob).hexdigest(),
                    shard_key=f"{document.market.lower()}/{document.published_at.year}/{document.document_type}",
                ), vector)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        ln = math.sqrt(sum(a * a for a in left))
        rn = math.sqrt(sum(b * b for b in right))
        return 0.0 if ln == 0 or rn == 0 else dot / (ln * rn)

    @staticmethod
    def _diversify(results: list[KnowledgeSearchResult]) -> list[KnowledgeSearchResult]:
        counts: dict[str, int] = {}
        output: list[KnowledgeSearchResult] = []
        for item in results:
            key = item.document.source_name
            if counts.get(key, 0) >= 3:
                continue
            counts[key] = counts.get(key, 0) + 1
            output.append(item)
        return output
