#!/usr/bin/env python3
"""Evaluate fixed financial-knowledge retrieval questions without an LLM."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.repository.sqlite import create_unit_of_work
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=PROJECT / "config/financial_knowledge_eval_questions.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/financial_knowledge/latest-evaluation.json")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    suite = json.loads(args.questions.read_text(encoding="utf-8"))
    questions = [
        (item["category"], question, item["expected_terms"])
        for item in suite["categories"] for question in item["questions"]
    ]
    if len(questions) < 120:
        raise SystemExit("financial knowledge evaluation requires at least 120 fixed questions")
    uow = create_unit_of_work()
    outcomes = []
    try:
        retrieval = KnowledgeRetrievalService(uow)
        for category, question, expected_terms in questions:
            results, snapshot = retrieval.search(
                question, as_of=datetime.now(timezone.utc), market="CN", limit=args.limit,
            )
            rank = 0
            citation_valid = True
            for index, result in enumerate(results, start=1):
                text = f"{result.document.title}\n{result.snippet or ''}"
                if not rank and any(term in text for term in expected_terms):
                    rank = index
                citation_valid = citation_valid and bool(
                    result.citation_id and result.chunk_id and result.document.source_name
                )
            outcomes.append({
                "category": category, "question": question, "rank": rank,
                "recall_at_10": 1 if rank else 0,
                "reciprocal_rank": 0.0 if not rank else 1.0 / rank,
                "citation_valid": citation_valid,
                "retrieval_mode": snapshot.retrieval_mode,
            })
    finally:
        uow.close()
    total = len(outcomes)
    recall = sum(item["recall_at_10"] for item in outcomes) / total
    mrr = sum(item["reciprocal_rank"] for item in outcomes) / total
    citation_accuracy = sum(bool(item["citation_valid"]) for item in outcomes) / total
    report = {
        "schema_version": "financial-knowledge-evaluation-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question_count": total, "recall_at_10": recall, "mrr_at_10": mrr,
        "citation_accuracy": citation_accuracy,
        "thresholds": {"recall_at_10": 0.85, "mrr_at_10": 0.65, "citation_accuracy": 1.0},
        "status": "complete" if recall >= 0.85 and mrr >= 0.65 and citation_accuracy == 1.0 else "blocked",
        "data_tier": "research_pit", "deployment_ready": False,
        "outcomes": outcomes,
    }
    report["report_hash"] = hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
