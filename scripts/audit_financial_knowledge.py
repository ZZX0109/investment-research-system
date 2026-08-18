#!/usr/bin/env python3
"""Generate a machine-readable integrity and coverage audit for knowledge."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import create_unit_of_work


def main() -> int:
    output = PROJECT / "artifacts/financial_knowledge/latest-audit.json"
    uow = create_unit_of_work()
    try:
        connection = uow.connection
        counts = {
            "documents": int(connection.execute("SELECT COUNT(*) FROM financial_knowledge_documents").fetchone()[0]),
            "chunks": int(connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]),
            "embeddings": int(connection.execute("SELECT COUNT(*) FROM knowledge_embeddings").fetchone()[0]),
            "retrieval_snapshots": int(connection.execute("SELECT COUNT(*) FROM knowledge_retrieval_snapshots").fetchone()[0]),
        }
        checks = {
            "orphan_chunks": int(connection.execute("SELECT COUNT(*) FROM knowledge_chunks c LEFT JOIN financial_knowledge_documents d ON d.id=c.document_id WHERE d.id IS NULL").fetchone()[0]),
            "private_without_owner": int(connection.execute("SELECT COUNT(*) FROM financial_knowledge_documents WHERE access_scope='private' AND owner_user_id IS NULL").fetchone()[0]),
            "future_visibility": int(connection.execute("SELECT COUNT(*) FROM financial_knowledge_documents WHERE available_at<published_at").fetchone()[0]),
            "duplicate_chunk_hashes": int(connection.execute("SELECT COUNT(*) FROM (SELECT document_id,revision,content_hash,COUNT(*) n FROM knowledge_chunks GROUP BY document_id,revision,content_hash HAVING n>1)").fetchone()[0]),
        }
        coverage = [item.model_dump(mode="json") for item in uow.financial_knowledge.latest_coverage(market="CN")]
    finally:
        uow.close()
    errors = [key for key, value in checks.items() if value]
    report = {
        "schema_version": "financial-knowledge-audit-v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked" if errors else "complete", "data_tier": "research_pit",
        "deployment_ready": False, "counts": counts, "checks": checks, "errors": errors,
        "coverage": coverage,
    }
    report["report_hash"] = hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
