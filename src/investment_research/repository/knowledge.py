from __future__ import annotations

from array import array
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Iterable
from uuid import UUID, uuid4

from investment_research.domain.knowledge import (
    FinancialKnowledgeDocument,
    FinancialLineItem,
    KnowledgeChunk,
    KnowledgeCoverageLedger,
    KnowledgeEmbedding,
    KnowledgeFetchRun,
    KnowledgeRetrievalSnapshot,
    KnowledgeSearchResult,
    KnowledgeSource,
)


class FinancialKnowledgeRepository:
    """Revisioned knowledge catalog with owner-aware lexical and hybrid search."""

    def __init__(self, connection) -> None:
        self.connection = connection

    def add(self, document: FinancialKnowledgeDocument) -> FinancialKnowledgeDocument:
        existing = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_documents WHERE content_hash=?",
            (document.content_hash,),
        ).fetchone()
        if existing is not None:
            value = FinancialKnowledgeDocument.model_validate_json(str(existing[0]))
            if value.access_scope == "private" and value.owner_user_id != document.owner_user_id:
                raise ValueError("private knowledge hash belongs to another owner")
            return value
        self.connection.execute(
            "INSERT INTO financial_knowledge_documents "
            "(id,market,symbol,document_type,published_at,available_at,status,content_hash,payload_json,"
            "owner_user_id,access_scope,source_name,first_observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(document.id), document.market, document.symbol, document.document_type,
                document.published_at.isoformat(), document.available_at.isoformat(),
                document.status, document.content_hash, document.model_dump_json(),
                None if document.owner_user_id is None else str(document.owner_user_id),
                document.access_scope, document.source_name,
                None if document.first_observed_at is None else document.first_observed_at.isoformat(),
            ),
        )
        self._add_revision(document)
        self.connection.commit()
        return document

    def _add_revision(self, document: FinancialKnowledgeDocument) -> None:
        revision_id = str(uuid4())
        self.connection.execute(
            "INSERT OR IGNORE INTO knowledge_document_revisions "
            "(id,document_id,previous_revision_id,revision,available_at,content_hash,raw_payload_ref,raw_payload_hash,payload_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                revision_id, str(document.id),
                None if document.previous_revision_id is None else str(document.previous_revision_id),
                document.revision, document.available_at.isoformat(), document.content_hash,
                document.raw_payload_ref, document.raw_payload_hash, document.model_dump_json(),
            ),
        )

    def replace_chunks(self, document: FinancialKnowledgeDocument, chunks: Iterable[KnowledgeChunk]) -> list[KnowledgeChunk]:
        previous = self.connection.execute(
            "SELECT id FROM knowledge_chunks WHERE document_id=? AND revision=?",
            (str(document.id), document.revision),
        ).fetchall()
        for row in previous:
            self._delete_fts(str(row[0]))
        self.connection.execute(
            "DELETE FROM knowledge_chunks WHERE document_id=? AND revision=?",
            (str(document.id), document.revision),
        )
        values = list(chunks)
        for chunk in values:
            self.connection.execute(
                "INSERT INTO knowledge_chunks "
                "(id,document_id,revision,chunk_index,content,section,page_start,page_end,content_hash,owner_user_id,access_scope,payload_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(chunk.id), str(chunk.document_id), chunk.revision, chunk.chunk_index,
                    chunk.content, chunk.section, chunk.page_start, chunk.page_end, chunk.content_hash,
                    None if chunk.owner_user_id is None else str(chunk.owner_user_id),
                    chunk.access_scope, chunk.model_dump_json(),
                ),
            )
            self._insert_fts(document, chunk)
        self.connection.commit()
        return values

    def add_embedding(self, metadata: KnowledgeEmbedding, vector: list[float]) -> KnowledgeEmbedding:
        if len(vector) != metadata.dimension or any(not math.isfinite(item) for item in vector):
            raise ValueError("embedding vector is invalid")
        blob = array("f", vector).tobytes()
        if hashlib.sha256(blob).hexdigest() != metadata.vector_hash:
            raise ValueError("embedding vector hash mismatch")
        self.connection.execute(
            "INSERT OR REPLACE INTO knowledge_embeddings "
            "(id,chunk_id,model_name,model_revision,dimension,vector_hash,shard_key,vector_blob,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(metadata.id), str(metadata.chunk_id), metadata.model_name, metadata.model_revision,
                metadata.dimension, metadata.vector_hash, metadata.shard_key, blob,
                metadata.created_at.isoformat(),
            ),
        )
        self.connection.commit()
        return metadata

    def embeddings_for_chunks(self, chunk_ids: list[str], *, model_name: str) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self.connection.execute(
            f"SELECT chunk_id,vector_blob FROM knowledge_embeddings WHERE model_name=? AND chunk_id IN ({placeholders})",
            (model_name, *chunk_ids),
        ).fetchall()
        output: dict[str, list[float]] = {}
        for row in rows:
            values = array("f")
            values.frombytes(bytes(row[1]))
            output[str(row[0])] = values.tolist()
        return output

    def get(self, document_id: str, *, owner_user_id: UUID | None = None) -> FinancialKnowledgeDocument | None:
        row = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_documents WHERE id=?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        document = FinancialKnowledgeDocument.model_validate_json(str(row[0]))
        if document.access_scope == "private" and document.owner_user_id != owner_user_id:
            return None
        return document

    def latest_by_identity(
        self, *, market: str, symbol: str | None, source_url: str | None,
        title: str, owner_user_id: UUID | None,
    ) -> FinancialKnowledgeDocument | None:
        access_sql, params = self._access_clause(owner_user_id)
        rows = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_documents "
            f"WHERE market=? AND {access_sql} ORDER BY published_at DESC",
            (market, *params),
        ).fetchall()
        for row in rows:
            item = FinancialKnowledgeDocument.model_validate_json(str(row[0]))
            if item.symbol == symbol and item.source_url == source_url and item.title == title:
                return item
        return None

    def find_by_raw_payload_ref(
        self, raw_payload_ref: str, *, owner_user_id: UUID,
    ) -> FinancialKnowledgeDocument | None:
        for item in self.list(owner_user_id=owner_user_id):
            if item.access_scope == "private" and item.raw_payload_ref == raw_payload_ref:
                return item
        return None

    def supersede(self, document_id: str, *, effective_to: datetime) -> None:
        row = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_documents WHERE id=?", (document_id,),
        ).fetchone()
        if row is None:
            return
        item = FinancialKnowledgeDocument.model_validate_json(str(row[0]))
        updates: dict[str, object] = {
            "status": "superseded", "effective_to": effective_to,
        }
        if item.fact_card is not None:
            updates["fact_card"] = item.fact_card.model_copy(update={
                "status": "superseded", "valid_to": effective_to,
            })
        item = item.model_copy(update=updates)
        self.connection.execute(
            "UPDATE financial_knowledge_documents SET status='superseded',payload_json=? WHERE id=?",
            (item.model_dump_json(), document_id),
        )
        self.connection.commit()

    def chunks_for_document(self, document_id: str, *, owner_user_id: UUID | None = None) -> list[KnowledgeChunk]:
        if self.get(document_id, owner_user_id=owner_user_id) is None:
            return []
        rows = self.connection.execute(
            "SELECT payload_json FROM knowledge_chunks WHERE document_id=? ORDER BY revision DESC,chunk_index",
            (document_id,),
        ).fetchall()
        return [KnowledgeChunk.model_validate_json(str(row[0])) for row in rows]

    def revision_timeline(
        self, document_id: str, *, owner_user_id: UUID | None = None,
    ) -> list[FinancialKnowledgeDocument]:
        current = self.get(document_id, owner_user_id=owner_user_id)
        output: list[FinancialKnowledgeDocument] = []
        seen: set[str] = set()
        while current is not None and str(current.id) not in seen:
            seen.add(str(current.id))
            output.append(current)
            if current.previous_revision_id is None:
                break
            current = self.get(str(current.previous_revision_id), owner_user_id=owner_user_id)
        return sorted(output, key=lambda item: item.revision)

    def list(
        self, *, market: str = "CN", symbol: str | None = None,
        owner_user_id: UUID | None = None,
    ) -> list[FinancialKnowledgeDocument]:
        access_sql, params = self._access_clause(owner_user_id)
        if symbol:
            rows = self.connection.execute(
                "SELECT payload_json FROM financial_knowledge_documents "
                f"WHERE market=? AND (symbol IS NULL OR symbol=?) AND {access_sql} ORDER BY published_at DESC",
                (market, symbol, *params),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM financial_knowledge_documents "
                f"WHERE market=? AND {access_sql} ORDER BY published_at DESC",
                (market, *params),
            ).fetchall()
        return [FinancialKnowledgeDocument.model_validate_json(str(row[0])) for row in rows]

    def list_all_for_reindex(self, *, market: str = "CN") -> list[FinancialKnowledgeDocument]:
        """Internal maintenance read; never expose this method through user-facing APIs."""
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
        owner_user_id: UUID | None = None,
        document_type: str | None = None,
        source: str | None = None,
        offset: int = 0,
    ) -> list[KnowledgeSearchResult]:
        """Dependency-free lexical retrieval; hybrid service may add semantic scores."""
        terms = self._query_terms(query)
        fts_scores = self._fts_scores(query)
        candidates = self._candidate_chunks(
            as_of=as_of, market=market, symbol=symbol, owner_user_id=owner_user_id,
            document_type=document_type, source=source,
        )
        scored: list[KnowledgeSearchResult] = []
        seen_documents: set[str] = set()
        for document, chunk in candidates:
            title = document.title.lower()
            content = chunk.content.lower()
            matched = [term for term in terms if term in title or term in content]
            if not matched and terms and str(chunk.id) not in fts_scores:
                continue
            lexical = sum(3.0 if term in title else 1.0 for term in matched)
            lexical += 4.0 * fts_scores.get(str(chunk.id), 0.0)
            if document.symbol and symbol and document.symbol == symbol:
                lexical += 2.0
            authority = document.authority_level / 5.0
            final = lexical + authority
            citation_id = f"kb:{chunk.id}:{chunk.content_hash[:12]}"
            scored.append(KnowledgeSearchResult(
                document=document, score=final, matched_terms=matched, chunk_id=chunk.id,
                citation_id=citation_id, snippet=chunk.content[:900],
                page_or_section=self._page_or_section(chunk), lexical_score=lexical,
                semantic_score=None, authority_score=authority, final_score=final,
                coverage_status="complete" if document.content_scope == "full_text" else "partial",
                pit_status="assumed" if document.visibility_assumption else "proven",
            ))
        scored.sort(key=lambda item: (item.final_score, item.document.published_at), reverse=True)
        diversified: list[KnowledgeSearchResult] = []
        for item in scored:
            document_id = str(item.document.id)
            if document_id in seen_documents and len(diversified) < max(2, limit // 2):
                continue
            seen_documents.add(document_id)
            diversified.append(item)
        return diversified[offset:offset + limit]

    def _fts_scores(self, query: str) -> dict[str, float]:
        """Use SQLite FTS5/BM25 when available, with deterministic fallback."""
        tokens = re.findall(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}", query)
        if not tokens:
            return {}
        # Quoting each token prevents FTS operators from being injected by a
        # user query. Prefix matching helps securities codes and Latin terms.
        expression = " OR ".join(f'"{token}"' for token in tokens[:16])
        try:
            rows = self.connection.execute(
                "SELECT chunk_id,bm25(knowledge_chunks_fts) AS rank "
                "FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH ? LIMIT 200",
                (expression,),
            ).fetchall()
        except Exception:
            return {}
        return {
            str(row[0]): 1.0 / (1.0 + abs(float(row[1])))
            for row in rows
        }

    def candidate_chunks(
        self, *, as_of: datetime, market: str = "CN", symbol: str | None = None,
        owner_user_id: UUID | None = None, document_type: str | None = None,
        source: str | None = None,
    ) -> list[tuple[FinancialKnowledgeDocument, KnowledgeChunk]]:
        return self._candidate_chunks(
            as_of=as_of, market=market, symbol=symbol, owner_user_id=owner_user_id,
            document_type=document_type, source=source,
        )

    def add_source(self, source: KnowledgeSource) -> KnowledgeSource:
        self.connection.execute(
            "INSERT OR REPLACE INTO financial_knowledge_sources "
            "(id,provider,name,base_url,source_kind,authority_level,content_policy,update_frequency,enabled,payload_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(source.id), source.provider, source.name, source.base_url, source.source_kind,
                source.authority_level, source.content_policy, source.update_frequency,
                source.enabled, source.model_dump_json(),
            ),
        )
        self.connection.commit()
        return source

    def list_sources(self) -> list[KnowledgeSource]:
        rows = self.connection.execute("SELECT payload_json FROM financial_knowledge_sources ORDER BY authority_level DESC,name").fetchall()
        return [KnowledgeSource.model_validate_json(str(row[0])) for row in rows]

    def get_source(self, provider: str) -> KnowledgeSource | None:
        row = self.connection.execute(
            "SELECT payload_json FROM financial_knowledge_sources WHERE provider=?", (provider,),
        ).fetchone()
        return None if row is None else KnowledgeSource.model_validate_json(str(row[0]))

    def add_fetch_run(self, run: KnowledgeFetchRun) -> KnowledgeFetchRun:
        self.connection.execute(
            "INSERT OR REPLACE INTO knowledge_fetch_runs (id,source_id,provider,status,started_at,finished_at,payload_json) VALUES (?,?,?,?,?,?,?)",
            (str(run.id), str(run.source_id), run.provider, run.status, run.started_at.isoformat(),
             None if run.finished_at is None else run.finished_at.isoformat(), run.model_dump_json()),
        )
        self.connection.commit()
        return run

    def latest_fetch_run(self, provider: str) -> KnowledgeFetchRun | None:
        row = self.connection.execute(
            "SELECT payload_json FROM knowledge_fetch_runs WHERE provider=? ORDER BY started_at DESC LIMIT 1",
            (provider,),
        ).fetchone()
        return None if row is None else KnowledgeFetchRun.model_validate_json(str(row[0]))

    def add_coverage(self, coverage: KnowledgeCoverageLedger) -> KnowledgeCoverageLedger:
        self.add_coverages([coverage])
        return coverage

    def add_coverages(self, values: list[KnowledgeCoverageLedger]) -> list[KnowledgeCoverageLedger]:
        for coverage in values:
            self.connection.execute(
                "INSERT INTO knowledge_coverage_ledger (id,provider,market,symbol,dataset,metadata_status,full_text_status,checked_at,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(coverage.id), coverage.provider, coverage.market, coverage.symbol, coverage.dataset,
                 coverage.metadata_status, coverage.full_text_status, coverage.checked_at.isoformat(), coverage.model_dump_json()),
            )
        self.connection.commit()
        return values

    def latest_coverage(
        self, *, market: str = "CN", symbol: str | None = None,
        as_of: datetime | None = None,
    ) -> list[KnowledgeCoverageLedger]:
        cutoff_sql = "" if as_of is None else " AND checked_at<=?"
        cutoff_params: tuple[str, ...] = () if as_of is None else (as_of.isoformat(),)
        if symbol:
            rows = self.connection.execute(
                "SELECT payload_json FROM knowledge_coverage_ledger "
                f"WHERE market=? AND (symbol=? OR symbol IS NULL){cutoff_sql} ORDER BY checked_at DESC",
                (market, symbol, *cutoff_params),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM knowledge_coverage_ledger "
                f"WHERE market=?{cutoff_sql} ORDER BY checked_at DESC",
                (market, *cutoff_params),
            ).fetchall()
        output: list[KnowledgeCoverageLedger] = []
        seen: set[tuple[str, str | None, str]] = set()
        for row in rows:
            item = KnowledgeCoverageLedger.model_validate_json(str(row[0]))
            key = (item.provider, item.symbol, item.dataset)
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output

    def add_retrieval_snapshot(self, snapshot: KnowledgeRetrievalSnapshot) -> KnowledgeRetrievalSnapshot:
        self.connection.execute(
            "INSERT INTO knowledge_retrieval_snapshots (id,owner_user_id,query_hash,as_of,retrieval_mode,created_at,payload_json) VALUES (?,?,?,?,?,?,?)",
            (str(snapshot.id), None if snapshot.owner_user_id is None else str(snapshot.owner_user_id),
             snapshot.query_hash, snapshot.as_of.isoformat(), snapshot.retrieval_mode,
             snapshot.created_at.isoformat(), snapshot.model_dump_json()),
        )
        self.connection.commit()
        return snapshot

    def delete_private_document(self, document_id: str, *, owner_user_id: UUID) -> bool:
        document = self.get(document_id, owner_user_id=owner_user_id)
        if document is None or document.access_scope != "private":
            return False
        chunks = self.connection.execute("SELECT id FROM knowledge_chunks WHERE document_id=?", (document_id,)).fetchall()
        for row in chunks:
            self._delete_fts(str(row[0]))
        cursor = self.connection.execute(
            "DELETE FROM financial_knowledge_documents WHERE id=? AND owner_user_id=? AND access_scope='private'",
            (document_id, str(owner_user_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    # -- financial line items (structured PIT facts) ----------------------

    def latest_line_item_by_identity(
        self, *, market: str, symbol: str, period: str, metric: str,
    ) -> FinancialLineItem | None:
        rows = self.connection.execute(
            "SELECT payload_json FROM financial_line_items "
            "WHERE market=? AND symbol=? AND period=? AND metric=? AND status='active' "
            "ORDER BY available_at DESC LIMIT 1",
            (market, symbol, period, metric),
        ).fetchall()
        if not rows:
            return None
        return FinancialLineItem.model_validate_json(str(rows[0][0]))

    def add_line_item(self, item: FinancialLineItem) -> FinancialLineItem:
        existing = self.connection.execute(
            "SELECT payload_json FROM financial_line_items WHERE content_hash=?",
            (item.content_hash,),
        ).fetchone()
        if existing is not None:
            return FinancialLineItem.model_validate_json(str(existing[0]))
        self.connection.execute(
            "INSERT INTO financial_line_items "
            "(id,market,symbol,period,metric,available_at,status,content_hash,payload_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(item.id), item.market, item.symbol, item.period, item.metric,
                item.available_at.isoformat(), item.status, item.content_hash,
                item.model_dump_json(),
            ),
        )
        self.connection.commit()
        return item

    def supersede_line_item(self, item_id: str, *, effective_to: datetime) -> None:
        self.connection.execute(
            "UPDATE financial_line_items SET status='superseded' WHERE id=?",
            (item_id,),
        )
        self.connection.commit()

    def line_items_for(
        self, *, market: str, symbol: str, as_of: datetime,
        metrics: list[str] | None = None, periods: list[str] | None = None,
    ) -> list[FinancialLineItem]:
        """Return the latest visible line item per (period, metric) at ``as_of``.

        Only items whose ``available_at`` <= ``as_of`` are visible — this is the
        point-in-time boundary that prevents lookahead bias.  Missing periods
        simply do not appear; callers must treat absence as "未披露", not zero.
        """
        query = (
            "SELECT payload_json FROM financial_line_items "
            "WHERE market=? AND symbol=? AND available_at<=? AND status='active'"
        )
        params: list[object] = [market, symbol, as_of.isoformat()]
        if metrics:
            placeholders = ",".join("?" for _ in metrics)
            query += f" AND metric IN ({placeholders})"
            params.extend(metrics)
        if periods:
            placeholders = ",".join("?" for _ in periods)
            query += f" AND period IN ({placeholders})"
            params.extend(periods)
        rows = self.connection.execute(query, params).fetchall()
        latest: dict[tuple[str, str], FinancialLineItem] = {}
        for row in rows:
            item = FinancialLineItem.model_validate_json(str(row[0]))
            key = (item.period, item.metric)
            present = latest.get(key)
            if present is None or item.available_at > present.available_at or item.revision > present.revision:
                latest[key] = item
        return sorted(
            latest.values(),
            key=lambda value: (value.period, value.metric),
        )

    def _candidate_chunks(
        self, *, as_of: datetime, market: str, symbol: str | None, owner_user_id: UUID | None,
        document_type: str | None, source: str | None,
    ) -> list[tuple[FinancialKnowledgeDocument, KnowledgeChunk]]:
        access_sql, access_params = self._access_clause(owner_user_id, alias="d")
        # Superseded rows remain visible for historical as_of queries until the
        # replacement revision became available.  Only withdrawn rows are never
        # eligible.
        conditions = ["d.market=?", "d.status!='withdrawn'", "d.available_at<=?", access_sql]
        params: list[object] = [market, as_of.isoformat(), *access_params]
        if symbol:
            conditions.append("(d.symbol IS NULL OR d.symbol=?)")
            params.append(symbol)
        if document_type:
            conditions.append("d.document_type=?")
            params.append(document_type)
        if source:
            conditions.append("d.source_name=?")
            params.append(source)
        rows = self.connection.execute(
            "SELECT d.payload_json,c.payload_json FROM financial_knowledge_documents d "
            "JOIN knowledge_chunks c ON c.document_id=d.id "
            f"WHERE {' AND '.join(conditions)} ORDER BY d.published_at DESC,c.chunk_index LIMIT 5000",
            tuple(params),
        ).fetchall()
        output: list[tuple[FinancialKnowledgeDocument, KnowledgeChunk]] = []
        for row in rows:
            document = FinancialKnowledgeDocument.model_validate_json(str(row[0]))
            if document.effective_from > as_of or (document.effective_to and document.effective_to <= as_of):
                continue
            output.append((document, KnowledgeChunk.model_validate_json(str(row[1]))))
        return output

    @staticmethod
    def _access_clause(owner_user_id: UUID | None, *, alias: str | None = None) -> tuple[str, list[str]]:
        prefix = "" if alias is None else f"{alias}."
        if owner_user_id is None:
            return f"{prefix}access_scope='public'", []
        return f"({prefix}access_scope='public' OR {prefix}owner_user_id=?)", [str(owner_user_id)]

    def _insert_fts(self, document: FinancialKnowledgeDocument, chunk: KnowledgeChunk) -> None:
        try:
            self.connection.execute(
                "INSERT INTO knowledge_chunks_fts(chunk_id,document_id,title,symbol,section,content) VALUES (?,?,?,?,?,?)",
                (str(chunk.id), str(document.id), document.title, document.symbol or "", chunk.section or "", chunk.content),
            )
        except Exception:
            # PostgreSQL and SQLite builds without FTS5 use deterministic lexical search.
            return

    def _delete_fts(self, chunk_id: str) -> None:
        try:
            self.connection.execute("DELETE FROM knowledge_chunks_fts WHERE chunk_id=?", (chunk_id,))
        except Exception:
            return

    @staticmethod
    def _page_or_section(chunk: KnowledgeChunk) -> str | None:
        if chunk.page_start is not None:
            return f"page:{chunk.page_start}" if chunk.page_end in {None, chunk.page_start} else f"pages:{chunk.page_start}-{chunk.page_end}"
        return chunk.section

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        value = query.lower()
        terms: list[str] = re.findall(r"[a-z0-9_]{2,}", value)
        for segment in re.findall(r"[\u4e00-\u9fff]+", value):
            if len(segment) <= 4:
                terms.append(segment)
            for size in (2, 3, 4):
                terms.extend(segment[index:index + size] for index in range(max(0, len(segment) - size + 1)))
        return list(dict.fromkeys(terms))[:80]
