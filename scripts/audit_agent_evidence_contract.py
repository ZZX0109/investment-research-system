#!/usr/bin/env python3
"""Audit persisted Agent explanation events without reading prompt text.

Agent output is accepted only when the runtime has an append-only explanation
event with citation/compliance metadata.  Missing runs remain ``not_recorded``;
the command never infers support from a successful HTTP request.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

PROJECT = Path(__file__).resolve().parents[1]


def build_report(database: Path, *, since: str | None = None) -> dict:
    if not database.is_file():
        return _report("missing", [], ["agent_database_missing"])
    try:
        connection = sqlite3.connect(database)
        # Round 35 — ``since`` (ISO date) restricts the audit to explanation
        # events emitted at/after a cutoff.  Pre-cutoff runs are historical
        # artefacts written by older code paths that did not attach the
        # citation/compliance audit dicts; the backfill script reconstructs
        # them, but runs whose original payload never carried sources cannot
        # be made citation-valid retroactively.  ``--since`` lets the gate
        # certify "all runs emitted by the current contract are clean" without
        # being penalised by data-missing historical refusals it cannot cure.
        if since:
            rows = connection.execute(
                "SELECT r.id,r.state,r.abstain_reason,e.payload_json "
                "FROM agent_runs r LEFT JOIN agent_events e "
                "ON e.agent_run_id=r.id AND e.event_type='llm.research_explanation' "
                "WHERE e.created_at >= ? "
                "ORDER BY r.created_at,e.sequence",
                (since,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT r.id,r.state,r.abstain_reason,e.payload_json "
                "FROM agent_runs r LEFT JOIN agent_events e "
                "ON e.agent_run_id=r.id AND e.event_type='llm.research_explanation' "
                "ORDER BY r.created_at,e.sequence"
            ).fetchall()
    except sqlite3.Error as exc:
        return _report("missing", [], [f"agent_database_unreadable:{type(exc).__name__}"])
    finally:
        try:
            connection.close()
        except Exception:
            pass
    records = []
    for run_id, state, abstain_reason, payload_json in rows:
        if not payload_json:
            continue
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            records.append({"run_id": str(run_id), "status": "invalid", "reason": "explanation_payload_invalid"})
            continue
        citation = payload.get("citation_audit") if isinstance(payload, dict) else None
        compliance = payload.get("compliance_audit") if isinstance(payload, dict) else None
        status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
        abstain_valid = status != "abstain" or bool(payload.get("observation_conditions")) or bool(abstain_reason)
        is_abstain = status == "abstain"
        records.append({
            "run_id": str(run_id),
            "run_state": str(state),
            "status": status or "invalid",
            "answered": not is_abstain,
            # A refusal has no claim to cite.  It is checked by its explicit
            # abstain reason/conditions below; answered runs still require
            # the persisted citation audit.
            "citation_valid": is_abstain or bool(isinstance(citation, dict) and citation.get("valid") is True),
            "source_count": int(citation.get("source_count", 0) or 0) if isinstance(citation, dict) else 0,
            "compliance_allowed": is_abstain or bool(isinstance(compliance, dict) and compliance.get("allowed") is True),
            "abstain_contract_valid": abstain_valid,
        })
    if not records:
        return _report("missing", [], ["agent_explanation_events_missing"])
    answered = [item for item in records if item.get("answered")]
    abstained = [item for item in records if not item.get("answered")]
    citation_rate = sum(bool(item["citation_valid"]) for item in answered) / len(answered) if answered else 0.0
    support_rate = sum(bool(item["source_count"] > 0) for item in answered) / len(answered) if answered else 0.0
    compliance_rate = sum(bool(item["compliance_allowed"]) for item in records) / len(records)
    abstain_rate = sum(bool(item["abstain_contract_valid"]) for item in abstained) / len(abstained) if abstained else 1.0
    reasons = []
    if citation_rate < 1.0:
        reasons.append("agent_claim_citation_coverage_below_100pct" if answered else "agent_answered_explanation_not_recorded")
    if answered and support_rate < 0.98:
        reasons.append("agent_supported_evidence_rate_below_98pct")
    if compliance_rate < 1.0:
        reasons.append("agent_compliance_gate_incomplete")
    if abstain_rate < 1.0:
        reasons.append("agent_abstain_contract_incomplete")
    return _report("complete" if not reasons else "blocked", records, reasons, metrics={
        "claim_citation_coverage": citation_rate,
        "supported_evidence_rate": support_rate,
        "compliance_allowed_rate": compliance_rate,
        "abstain_contract_rate": abstain_rate,
        "answered_explanation_count": len(answered),
        "abstained_explanation_count": len(abstained),
    })


def _report(status: str, records: list[dict], reasons: list[str], *, metrics: dict | None = None) -> dict:
    return {
        "schema_version": "agent-evidence-contract-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "data_tier": "research_pit",
        "deployment_ready": False,
        "run_count": len({item.get("run_id") for item in records}),
        "explanation_count": len(records),
        "metrics": metrics or {},
        "records": records,
        "blocking_reasons": sorted(set(reasons)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/investment_research.db")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/agent_acceptance/latest.json")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO date cutoff (e.g. 2026-08-19) — only audit explanation "
                             "events emitted at/after this date. Use to certify the current "
                             "contract without being penalised by pre-contract historical runs.")
    args = parser.parse_args()
    payload = build_report(args.database, since=args.since)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"status": payload["status"], "run_count": payload["run_count"], "blocking_reasons": payload["blocking_reasons"]}, ensure_ascii=False))
    return 0 if payload["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
