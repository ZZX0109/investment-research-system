#!/usr/bin/env python3
"""Fetch one already-cataloged official document body by immutable ID."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import create_unit_of_work
from investment_research.service.knowledge_ingestion import OfficialKnowledgeIngestionService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/financial_knowledge/latest-document-fetch.json")
    args = parser.parse_args()
    uow = create_unit_of_work()
    try:
        try:
            document = OfficialKnowledgeIngestionService(uow).fetch_and_ingest_full_text(args.document_id)
            report = {
                "status": "complete", "requested_document_id": args.document_id,
                "document_id": str(document.id), "revision": document.revision,
                "content_hash": document.content_hash, "content_scope": document.content_scope,
            }
        except Exception as exc:
            report = {
                "status": "blocked", "requested_document_id": args.document_id,
                "reason": f"{type(exc).__name__}:{exc}",
            }
    finally:
        uow.close()
    report.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_tier": "research_pit", "deployment_ready": False,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
