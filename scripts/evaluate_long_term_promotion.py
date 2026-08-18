#!/usr/bin/env python3
"""Evaluate long-term model evidence without promoting or mutating a roster."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.research_shadow import FileResearchShadowStore
from investment_research.training.long_term_config import load_long_term_training_config
from investment_research.training.long_term_promotion import evaluate_long_term_promotion


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--shadow-directory", type=Path, default=PROJECT / "artifacts/research_shadow")
    parser.add_argument("--config", type=Path, default=PROJECT / "config/long_term_training.yaml")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/long_term_training/promotion.json")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    config = load_long_term_training_config(args.config)
    summary = FileResearchShadowStore(args.shadow_directory).summarize(market="cn", decision_context="close_confirmed")
    result = evaluate_long_term_promotion(report, valid_shadow_sessions=summary.valid_session_count, config=config)
    result["training_report_ref"] = str(args.report)
    result["shadow_directory"] = str(args.shadow_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "candidate_for_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
