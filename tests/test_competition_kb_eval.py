"""Tests for the competition KB golden evaluation (Phase 6).

A CI gate: the seeded demo KB must reach a recall@3 threshold with 100%
citation validity.  This guards retrieval reliability for the demo.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.knowledge_retrieval import KnowledgeRetrievalService
from investment_research.service.knowledge_reranker import DeterministicReranker

REPO_ROOT = Path(__file__).resolve().parent.parent
AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _load_seeder():
    scripts_dir = str(REPO_ROOT / "scripts")
    sys.path.insert(0, scripts_dir)
    module = importlib.import_module("seed_competition_knowledge")
    sys.path.remove(scripts_dir)
    return module


def test_seeded_kb_meets_recall_and_citation_threshold(tmp_path: Path) -> None:
    seeder = _load_seeder()
    uow = SQLiteUnitOfWork(tmp_path / "eval.db")
    seeder._run_seed_into(uow)
    retrieval = KnowledgeRetrievalService(uow, reranker=DeterministicReranker())

    questions = json.loads(
        (REPO_ROOT / "config" / "competition_kb_eval_questions.json").read_text(encoding="utf-8")
    )["questions"]

    hits_at_3 = 0
    citation_valid = True
    for item in questions:
        results, _ = retrieval.search(
            item["question"], as_of=AS_OF, market="CN",
            symbol=item["symbol"], limit=5,
        )
        rank = 0
        for index, result in enumerate(results, start=1):
            text = f"{result.document.title}\n{result.snippet or ''}"
            if not rank and any(term in text for term in item["expected_terms"]):
                rank = index
            citation_valid = citation_valid and bool(
                result.citation_id and result.chunk_id and result.document.source_name
            )
        if rank and rank <= 3:
            hits_at_3 += 1

    recall_at_3 = hits_at_3 / len(questions)
    assert recall_at_3 >= 0.8, f"recall@3 {recall_at_3} below threshold"
    assert citation_valid, "every retrieved result must carry a citation_id, chunk_id and source"
    uow.close()
