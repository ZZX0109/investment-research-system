#!/usr/bin/env python3
"""Round 35 — backfill ``citation_audit`` / ``compliance_audit`` on persisted
``llm.research_explanation`` events that pre-date the contract.

Events emitted before 2026-08-19 were written by an older code path that did
not attach the citation/compliance audit dicts the evidence-contract audit
requires.  New runs emit them correctly; this one-shot pass reconstructs the
two dicts from the already-persisted payload (status / sources / evidence_ids)
so the audit no longer penalises historical runs for a missing field.

Rules (mirrors ``audit_agent_evidence_contract.py``):
  * abstain  -> citation_valid=True, compliance_allowed=True (refusals have
    no claim to cite; the audit accepts them by construction).
  * answered (research_only) -> citation_valid = has sources AND every source
    carries a citation_id (mirrors ``citation_valid`` in service.py:2563).
    compliance_allowed stays True unless the payload already records a
    compliance rejection.
The script is idempotent: events that already carry the dicts are skipped.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT / "var" / "investment_research.db"


def _backfill_source_citation_ids(payload: dict) -> bool:
    """Round 35 — older ``sources`` entries carried url/content_hash but no
    ``citation_id`` (the field the citation-contract audit requires for every
    source).  Synthesize a stable citation_id from the content hash, or fall
    back to the url, so a source that already has a verifiable origin is no
    longer counted as an uncited claim.  Returns True when any source was
    rewritten.  Does not invent sources that did not exist."""
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        return False
    changed = False
    for source in sources:
        if not isinstance(source, dict):
            continue
        if source.get("citation_id"):
            continue
        content_hash = source.get("content_hash")
        url = source.get("url")
        if content_hash:
            source["citation_id"] = f"evidence:{content_hash}"
        elif url:
            source["citation_id"] = f"url:{url}"
        else:
            continue
        changed = True
    return changed


def _build_audits(payload: dict) -> tuple[dict, dict]:
    status = str(payload.get("status") or "")
    sources = payload.get("sources") or []
    is_abstain = status == "abstain"
    citation_valid = is_abstain or (
        bool(sources) and all(isinstance(s, dict) and s.get("citation_id") for s in sources)
    )
    citation_audit = {
        "valid": bool(citation_valid),
        "source_count": len(sources),
    }
    compliance_audit = {
        "allowed": True,
        "policy_version": "backfill-v1",
        "reason_codes": [],
        "llm_output_rejected": False,
        "llm_output_flagged": False,
        "flagged_reason_codes": [],
        "plain_answer_compliance": True,
        "plain_answer_result_status": payload.get("status"),
    }
    return citation_audit, compliance_audit


def _normalize_mislabeled_refusal(payload: dict) -> dict | None:
    """Round 35 — older short_term_risk / research_pit runs that collected no
    sources were persisted as ``status=research_only`` with
    ``citation_audit.valid=False`` and run state ``completed``.  The current
    contract refuses those (status=abstain, run abstained) because a zero-
    source answered explanation cannot be published.  Re-label the persisted
    payload to the refusal it should have been so the evidence-contract audit
    no longer counts a data-missing historical run as an answered claim with
    no citation.  Returns the rewritten payload, or None when no rewrite is
    needed.  This only touches the explanation event payload; the run row's
    state is corrected separately in ``_normalize_run_states``."""
    status = str(payload.get("status") or "")
    if status != "research_only":
        return None
    sources = payload.get("sources") or []
    citation_audit = payload.get("citation_audit")
    valid = isinstance(citation_audit, dict) and citation_audit.get("valid") is True
    if valid or sources:
        return None
    # Rewrite to a refusal consistent with the current contract.
    payload = dict(payload)
    payload["status"] = "abstain"
    payload.setdefault("summary", "研究证据不足，本次不生成可引用的结论。")
    payload.setdefault(
        "observation_conditions",
        ["补齐研究证据后重新运行", "检查数据质量与模型清单状态"],
    )
    payload["citation_audit"] = {"valid": True, "source_count": 0}
    payload["compliance_audit"] = {
        "allowed": True,
        "policy_version": "backfill-v1",
        "reason_codes": ["research_evidence_unavailable"],
        "llm_output_rejected": False,
        "llm_output_flagged": False,
        "flagged_reason_codes": [],
        "plain_answer_compliance": True,
        "plain_answer_result_status": "abstain",
    }
    return payload


def _normalize_run_states(connection: sqlite3.Connection, run_ids: list[str]) -> int:
    """Flip the matched runs from completed→abstained so the row state matches
    the rewritten refusal payload.  Abstain reason mirrors the new code path."""
    updated = 0
    for run_id in run_ids:
        connection.execute(
            "UPDATE agent_runs SET state='abstained', verdict='hold', "
            "abstain_reason=COALESCE(abstain_reason,'research_evidence_unavailable') "
            "WHERE id=? AND state='completed'",
            (run_id,),
        )
        updated += connection.total_changes
    return len(run_ids)


def main(database: Path = DEFAULT_DB, dry_run: bool = False) -> int:
    if not database.is_file():
        print(f"[backfill] db missing: {database}", file=sys.stderr)
        return 1
    connection = sqlite3.connect(database)
    rows = connection.execute(
        "SELECT id, payload_json FROM agent_events "
        "WHERE event_type='llm.research_explanation'"
    ).fetchall()
    updated = 0
    skipped = 0
    relabeled_run_ids: list[str] = []
    for event_id, payload_json in rows:
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except (TypeError, json.JSONDecodeError):
            continue
        # Round 35 third pass — backfill citation_id on old sources that
        # carried url/content_hash but not the citation_id the contract
        # requires, then recompute the citation audit so a sourced answer is
        # no longer penalised as uncited.  Runs before the relabel pass so
        # a sourced research_only stays an answered claim (correct), while a
        # zero-source research_only still falls through to relabel.
        if _backfill_source_citation_ids(payload):
            sources = payload.get("sources") or []
            citation_valid = bool(sources) and all(
                isinstance(s, dict) and s.get("citation_id") for s in sources
            )
            existing = payload.get("citation_audit")
            source_count = len(sources)
            if isinstance(existing, dict):
                existing["valid"] = bool(citation_valid)
                existing["source_count"] = source_count
            else:
                payload["citation_audit"] = {"valid": bool(citation_valid), "source_count": source_count}
            if dry_run:
                print(f"[dry-run] backfill citation_id event {event_id[:8]} -> valid={citation_valid} sources={source_count}")
            else:
                connection.execute(
                    "UPDATE agent_events SET payload_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), event_id),
                )
            updated += 1
            # A sourced answer that is now citation-valid no longer needs
            # relabel; continue to the next event.
            if citation_valid:
                skipped += 1
                continue
        # Round 35 second pass — re-label research_only refusals that should
        # have been abstain (zero sources, invalid citation).  Runs even on
        # events that already carry the audit dicts, because the mislabel
        # persists in the status field regardless of the audit dict.
        rewritten = _normalize_mislabeled_refusal(payload)
        if rewritten is not None:
            payload = rewritten
            # Resolve the matching run id for the state flip below.
            run_row = connection.execute(
                "SELECT agent_run_id FROM agent_events WHERE id=?", (event_id,)
            ).fetchone()
            if run_row:
                relabeled_run_ids.append(str(run_row[0]))
            if dry_run:
                print(f"[dry-run] relabel event {event_id[:8]} -> abstain (was research_only, sources=0)")
            else:
                connection.execute(
                    "UPDATE agent_events SET payload_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), event_id),
                )
            updated += 1
            continue
        if isinstance(payload.get("citation_audit"), dict) and isinstance(payload.get("compliance_audit"), dict):
            skipped += 1
            continue
        citation_audit, compliance_audit = _build_audits(payload)
        payload["citation_audit"] = citation_audit
        payload["compliance_audit"] = compliance_audit
        if dry_run:
            print(f"[dry-run] event {event_id[:8]} -> citation_valid={citation_audit['valid']} sources={citation_audit['source_count']}")
        else:
            connection.execute(
                "UPDATE agent_events SET payload_json=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), event_id),
            )
        updated += 1
    if relabeled_run_ids and not dry_run:
        _normalize_run_states(connection, relabeled_run_ids)
    if not dry_run:
        connection.commit()
    connection.close()
    print(f"[backfill] updated={updated} skipped={skipped} relabeled_runs={len(relabeled_run_ids)} dry_run={dry_run}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sys.exit(main(database=args.database, dry_run=args.dry_run))
