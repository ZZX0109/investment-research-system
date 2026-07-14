#!/usr/bin/env python3
"""Create the presentation-safe model card from frozen training artifacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
AUDITS = ROOT / "audits"


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> int:
    results = load(OUTPUT / "results.json")
    evaluation = load(OUTPUT / "evaluation.json")
    experiments = load(AUDITS / "trusted_risk_gate_experiments.json")
    events = load(AUDITS / "event_semantic_coverage.json")
    primary = results.get("deployment_roles", {}).get("primary_model", "random-forest")
    card = {
        "schema_version": "trusted-risk-gate-model-card-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "training_run_id": results.get("run_label"),
        "sample_snapshot_hash": results.get("sample_snapshot_hash"),
        "framework_version": "trusted-risk-gate-v1",
        "problem_definition": "Point-in-time drawdown-risk research signal for personal investment research; not automated trading advice.",
        "methodology": ["PIT data governance", "structured event factors", "cross-market walk-forward validation", "regime-aware promotion", "Judge degradation", "immutable ResearchRun replay"],
        "deployment": {"primary": primary, "fallback": results.get("deployment_roles", {}).get("champion_fallback", "linear-baseline"), "research_only": results.get("deployment_roles", {}).get("research_only_models", [])},
        "data": {"source": results.get("data_source"), "markets": results.get("included_markets", []), "sample_count": results.get("sample_count"), "pit_failures": load(AUDITS / "pit_audit.json").get("failure_count")},
        "primary_metrics": evaluation.get("models", {}).get(primary, {}),
        "event_coverage": events.get("feature_coverage", {}),
        "ablation": experiments.get("summary", {}),
        "gate_behavior": experiments.get("gate_comparison", {}),
        "limitations": ["Sparse guidance, regulatory and M&A event factors are not treated as decisive signals.", "Sequence-model challengers remain research-only until their temporal input contract improves.", "A HOLD or BLOCK verdict is a quality restriction, not a market forecast."],
        "rollback": "Use linear-baseline when the approved challenger, feature coverage, source freshness, or Judge gate is not trusted.",
    }
    (OUTPUT / "trusted_risk_gate_model_card.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote output/trusted_risk_gate_model_card.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
