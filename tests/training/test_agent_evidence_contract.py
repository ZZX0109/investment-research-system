from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit_agent_evidence_contract.py"
    spec = importlib.util.spec_from_file_location("agent_evidence_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_audit_requires_citations_for_answered_runs(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "agent.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
      CREATE TABLE agent_runs (id TEXT, state TEXT, abstain_reason TEXT, created_at TEXT);
      CREATE TABLE agent_events (agent_run_id TEXT, event_type TEXT, sequence INTEGER, payload_json TEXT);
    """)
    connection.execute("INSERT INTO agent_runs VALUES ('a','completed',NULL,'2026-01-01')")
    connection.execute("INSERT INTO agent_events VALUES ('a','llm.research_explanation',1,'{\"status\":\"research_only\",\"citation_audit\":{\"valid\":true,\"source_count\":2},\"compliance_audit\":{\"allowed\":true}}')")
    connection.commit(); connection.close()
    report = module.build_report(database)
    assert report["status"] == "complete"
    assert report["metrics"]["claim_citation_coverage"] == 1.0


def test_agent_audit_allows_explicit_refusal_without_fake_support(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "agent.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
      CREATE TABLE agent_runs (id TEXT, state TEXT, abstain_reason TEXT, created_at TEXT);
      CREATE TABLE agent_events (agent_run_id TEXT, event_type TEXT, sequence INTEGER, payload_json TEXT);
    """)
    connection.execute("INSERT INTO agent_runs VALUES ('a','abstained','missing PIT evidence','2026-01-01')")
    connection.execute("INSERT INTO agent_events VALUES ('a','llm.research_explanation',1,'{\"status\":\"abstain\",\"observation_conditions\":[\"补齐证据后重试\"]}')")
    connection.commit(); connection.close()
    report = module.build_report(database)
    assert report["status"] == "blocked"
    assert report["metrics"]["abstain_contract_rate"] == 1.0
    assert "agent_answered_explanation_not_recorded" in report["blocking_reasons"]
