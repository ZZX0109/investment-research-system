#!/usr/bin/env python3
"""Evaluate the competition-demo knowledge base (Phase 6).

Seeds the competition KB into a throwaway DB if needed, then runs the golden
question set and measures recall@k (rank of the first relevant chunk) and
citation validity.  Output: ``artifacts/competition_demo/latest-kb-evaluation.json``.

Run: ``python3 scripts/evaluate_competition_kb.py``
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

from investment_research.repository.sqlite import SQLiteUnitOfWork  # noqa: E402
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService  # noqa: E402
from investment_research.service.knowledge_reranker import DeterministicReranker  # noqa: E402


def main() -> int:
    questions_path = PROJECT / "config" / "competition_kb_eval_questions.json"
    output_path = PROJECT / "artifacts" / "competition_demo" / "latest-kb-evaluation.json"
    suite = json.loads(questions_path.read_text(encoding="utf-8"))
    questions = suite["questions"]
    if len(questions) < 10:
        raise SystemExit("competition KB evaluation requires at least 10 questions")

    # Seed into a throwaway DB so evaluation is reproducible and isolated.
    db_path = PROJECT / "artifacts" / "competition_demo" / "competition_kb_eval.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    uow = SQLiteUnitOfWork(db_path)
    seeder = importlib.import_module("seed_competition_knowledge")
    seeder._run_seed_into(uow)
    # Deterministic reranker keeps the eval fast and reproducible; the neural
    # cross-encoder is environment-dependent and not faster than needed here.
    retrieval = KnowledgeRetrievalService(uow, reranker=DeterministicReranker())

    as_of = datetime(2026, 8, 16, tzinfo=timezone.utc)
    outcomes = []
    hits_at_1 = hits_at_3 = hits_at_5 = 0
    citation_valid_total = True
    try:
        for item in questions:
            results, _ = retrieval.search(
                item["question"], as_of=as_of, market="CN",
                symbol=item["symbol"], limit=5,
            )
            rank = 0
            citation_valid = True
            for index, result in enumerate(results, start=1):
                text = f"{result.document.title}\n{result.snippet or ''}"
                if not rank and any(term in text for term in item["expected_terms"]):
                    rank = index
                citation_valid = citation_valid and bool(
                    result.citation_id and result.chunk_id and result.document.source_name
                )
            if rank:
                hits_at_1 += rank <= 1
                hits_at_3 += rank <= 3
                hits_at_5 += rank <= 5
            citation_valid_total = citation_valid_total and citation_valid
            outcomes.append({
                "symbol": item["symbol"], "question": item["question"],
                "rank": rank, "result_count": len(results),
                "expected_terms": item["expected_terms"],
                "citation_valid": citation_valid,
            })
    finally:
        uow.close()

    total = len(questions)
    report = {
        "schema_version": "competition-kb-eval-report-v1",
        "data_tier": "research_demo",
        "validation_status": "research_demonstration_not_validated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question_count": total,
        "recall_at_1": round(hits_at_1 / total, 4),
        "recall_at_3": round(hits_at_3 / total, 4),
        "recall_at_5": round(hits_at_5 / total, 4),
        "citation_validity": 1.0 if citation_valid_total else 0.0,
        "rerank_model": "deterministic-fallback",
        "outcomes": outcomes,
        "note": "Recall measures retrieval quality against the demonstration seed; not predictive accuracy.",
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"recall@1={report['recall_at_1']} recall@3={report['recall_at_3']} "
          f"recall@5={report['recall_at_5']} citation_validity={report['citation_validity']}")
    print(f"report -> {output_path.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
