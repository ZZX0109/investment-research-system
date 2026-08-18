#!/usr/bin/env python3
"""Rebuild deterministic chunks and optional local BGE embeddings."""
from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import create_unit_of_work
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService


def main() -> int:
    output = PROJECT / "artifacts/financial_knowledge/latest-reindex.json"
    uow = create_unit_of_work()
    failures: list[str] = []
    indexed = 0
    chunk_count = 0
    try:
        retrieval = KnowledgeRetrievalService(uow)
        documents = uow.financial_knowledge.list_all_for_reindex(market="CN")
        for document in documents:
            try:
                chunks = retrieval.index_document(document)
                indexed += 1
                chunk_count += len(chunks)
            except Exception as exc:
                failures.append(f"{document.id}:{type(exc).__name__}:{exc}")
        semantic = retrieval.embedder.available
        reason = None if semantic else getattr(retrieval.embedder, "unavailable_reason", "embedding_unavailable")
    finally:
        uow.close()
    report = {
        "schema_version": "financial-knowledge-reindex-v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if not failures else "partial", "indexed_documents": indexed,
        "chunk_count": chunk_count, "failures": failures, "semantic_search_available": semantic,
        "semantic_search_reason": reason, "data_tier": "research_pit", "deployment_ready": False,
    }
    # The database remains the local vector store; this deterministic manifest
    # is the portable audit index for market/year/document_type shards.
    from investment_research.repository.sqlite import create_unit_of_work as _open_uow
    manifest_uow = _open_uow()
    try:
        rows = manifest_uow.connection.execute(
            "SELECT shard_key,model_name,model_revision,vector_hash FROM knowledge_embeddings ORDER BY shard_key,chunk_id"
        ).fetchall()
    finally:
        manifest_uow.close()
    shards: dict[str, dict[str, object]] = {}
    for row in rows:
        key = str(row[0])
        entry = shards.setdefault(key, {"count": 0, "model": str(row[1]), "revision": str(row[2]), "vector_hashes": []})
        entry["count"] = int(entry["count"]) + 1
        entry["vector_hashes"].append(str(row[3]))
    for entry in shards.values():
        hashes = entry.pop("vector_hashes")
        entry["content_hash"] = hashlib.sha256("|".join(hashes).encode()).hexdigest()
    report["embedding_manifest"] = {"schema_version": "knowledge-embedding-shards-v1", "shards": shards}
    report["embedding_manifest_hash"] = hashlib.sha256(json.dumps(report["embedding_manifest"], sort_keys=True).encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0 if indexed else 2


if __name__ == "__main__":
    raise SystemExit(main())
