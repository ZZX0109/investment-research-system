#!/usr/bin/env python3
"""Assemble one release-style manifest for the full optimization objective.

This is an evidence index, not an activation command.  It keeps the requested
data, model, Shadow, Agent and frontend deliverables in one place and remains
``research_only`` until every required gate is actually proven.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _artifact(root: Path, relative: str, *, status: str, required: bool = True, evidence: dict | None = None) -> dict:
    path = root / relative
    return {
        "id": relative.replace("/", ":"),
        "path": str(path),
        "exists": path.exists(),
        "required": required,
        "status": status if path.exists() else "missing",
        "evidence": evidence or {},
    }


def build_manifest(project_root: Path = PROJECT) -> dict:
    root = project_root.resolve()
    plan = _read(root / "artifacts/cn_data_completion_plan/latest.json")
    completion = _read(root / "artifacts/project_completion/latest.json")
    readiness = _read(root / "artifacts/long_term_readiness/latest.json")
    candidate = _read(root / "artifacts/long_term_training/candidate-suite/evaluation-contract.json")
    shadow = _read(root / "artifacts/research_shadow/summary.json")
    agent = _read(root / "artifacts/agent_acceptance/latest.json")
    active = root / "var/cn-research/active.json"
    frontend = root / "dist-workbench/index.html"

    active_check = next((item for item in readiness.get("checks", []) if item.get("name") == "active_snapshot_gate"), {})
    # The requirement is independent valid trading dates.  Older summaries
    # called this field valid_session_count, so retain a compatibility
    # fallback while preferring the explicit date-count field.
    shadow_valid_dates = int(shadow.get("valid_trade_date_count", shadow.get("valid_session_count", 0)) or 0)
    agent_metrics = agent.get("metrics") if isinstance(agent.get("metrics"), dict) else {}
    gates = {
        "full_data_plan": plan.get("status") == "complete",
        "project_completion": completion.get("status") == "complete",
        "active_snapshot": active.is_file() and active_check.get("status") == "passed",
        "model_evaluation": next((item.get("status") for item in readiness.get("checks", []) if item.get("name") == "long_term_model_evaluation_contract"), "blocked") == "passed",
        "shadow_60": shadow_valid_dates >= 60,
        "agent_citations": float(agent_metrics.get("claim_citation_coverage", 0) or 0) >= 1.0 and float(agent_metrics.get("supported_evidence_rate", 0) or 0) >= 0.98,
        "frontend_build": frontend.is_file(),
    }
    deliverables = [
        _artifact(root, "docs/data-source-resource-matrix.md", status="delivered", evidence={"kind": "source_and_license_matrix"}),
        _artifact(root, "artifacts/cn_data_completion_plan/latest.json", status=plan.get("status", "blocked"), evidence={"missing_steps": plan.get("p0_missing_steps", [])}),
        _artifact(root, "artifacts/cn_data_completion_audit/latest.json", status=_read(root / "artifacts/cn_data_completion_audit/latest.json").get("status", "blocked"), evidence={"scope": "current_cn_security_master_universe"}),
        _artifact(root, "artifacts/project_completion/latest.json", status=completion.get("status", "blocked"), evidence=completion.get("summary", {})),
        _artifact(root, "artifacts/long_term_training/candidate-suite/evaluation-contract.json", status=candidate.get("status", "blocked"), evidence={"blocking_reasons": candidate.get("blocking_reasons", [])}),
        _artifact(root, "artifacts/long_term_readiness/latest.json", status=readiness.get("status", "blocked"), evidence={"blocking_reasons": readiness.get("blocking_reasons", [])}),
        _artifact(root, "artifacts/agent_acceptance/latest.json", status=agent.get("status", "missing"), evidence=agent_metrics),
        _artifact(root, "dist-workbench/index.html", status="delivered", evidence={"build_artifact": True}),
    ]
    missing = sorted(name for name, passed in gates.items() if not passed)
    return {
        "schema_version": "investment-research-optimization-delivery-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if not missing else "blocked",
        "release_channel": "professional" if not missing else "research_only",
        "formal_pit_eligible": bool(gates["active_snapshot"] and gates["full_data_plan"]),
        "deployment_ready": False,
        "gates": gates,
        "missing_gates": missing,
        "shadow_evidence": {
            "valid_trade_date_count": shadow_valid_dates,
            "minimum_required_trade_dates": 60,
            "real_prediction_count": int(shadow.get("real_prediction_count", 0) or 0),
            "empty_prediction_count": int(shadow.get("empty_prediction_count", 0) or 0),
            "real_prediction_trade_date_count": int(shadow.get("real_prediction_trade_date_count", 0) or 0),
            "prediction_trade_date_coverage": float(shadow.get("prediction_trade_date_coverage", 0.0) or 0.0),
            "prediction_state_counts": shadow.get("prediction_state_counts", {}),
            "abstain_reason_counts": shadow.get("abstain_reason_counts", {}),
            "summary_ref": str(root / "artifacts/research_shadow/summary.json"),
        },
        "deliverables": deliverables,
        "next_actions": [
            item.get("id")
            for item in plan.get("steps", [])
            if isinstance(item, dict) and item.get("status") != "complete"
        ] + list(completion.get("blocking_reasons", [])),
        "non_activation_rule": "This manifest never writes active.json and never promotes a research model.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/optimization_delivery/latest.json")
    args = parser.parse_args()
    payload = build_manifest(args.project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"status": payload["status"], "release_channel": payload["release_channel"], "missing_gates": payload["missing_gates"]}, ensure_ascii=False))
    return 0 if payload["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
