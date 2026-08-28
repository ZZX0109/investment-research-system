"""§3 数据可信度细化 — get_long_term_data_trust now surfaces per-asset
fundamental gaps (which of the §6③ six pillars THIS asset is missing),
not just a system-level completeness number.

Tests the ``_fundamental_coverage_for_research_pit`` helper the handler now
calls — it mirrors the snapshot builder's readout (retrieve_line_items →
fundamental_coverage) + degrades gracefully.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from investment_research.agent.service import AgentOrchestrator


def _result(items):
    return SimpleNamespace(line_items=items)


def test_fundamental_coverage_helper_surfaces_per_asset_gaps() -> None:
    """§3: the helper returns WHICH pillars are present/missing for this
    asset, so get_long_term_data_trust can cite "茅台 缺 ROE/ROA/营业利润"
    instead of a blank completeness number."""
    run = SimpleNamespace(as_of=datetime(2026, 8, 19, tzinfo=timezone.utc))
    pit = {"symbol": "600519"}
    stub = SimpleNamespace(uow=object())  # opaque — the knowledge service is patched
    items = [
        {"metric": "revenue", "metric_label": "营业收入", "value": 1743.0},
        {"metric": "net_profit", "metric_label": "归母净利润", "value": 862.0},
    ]
    fake_ks = SimpleNamespace(retrieve_line_items=lambda **kw: _result(items))
    with patch("investment_research.agent.service.FinancialKnowledgeService", return_value=fake_ks):
        cov = AgentOrchestrator._fundamental_coverage_for_research_pit(stub, pit, run)
    assert cov is not None
    assert cov["status"] == "ok"
    assert cov["coverage_pct"] == 33.3  # 2 of 6
    assert set(cov["present"]) == {"revenue", "net_profit"}
    assert set(cov["missing"]) == {"gross_margin", "operating_profit", "roe", "roa"}


def test_fundamental_coverage_helper_full_coverage_when_all_pillars_present() -> None:
    run = SimpleNamespace(as_of=datetime(2026, 8, 19, tzinfo=timezone.utc))
    pit = {"symbol": "000001"}
    stub = SimpleNamespace(uow=object())
    items = [
        {"metric": "revenue"},
        {"metric": "net_profit"},
        {"metric": "gross_margin"},
        {"metric": "operating_profit"},
        {"metric": "roe"},
        {"metric": "roa"},
    ]
    fake_ks = SimpleNamespace(retrieve_line_items=lambda **kw: _result(items))
    with patch("investment_research.agent.service.FinancialKnowledgeService", return_value=fake_ks):
        cov = AgentOrchestrator._fundamental_coverage_for_research_pit(stub, pit, run)
    assert cov["coverage_pct"] == 100.0
    assert cov["missing"] == []


def test_fundamental_coverage_helper_degrades_without_symbol() -> None:
    run = SimpleNamespace(as_of=datetime(2026, 8, 19, tzinfo=timezone.utc))
    stub = SimpleNamespace(uow=object())
    assert AgentOrchestrator._fundamental_coverage_for_research_pit(stub, {}, run) is None


def test_fundamental_coverage_helper_degrades_when_retrieval_fails() -> None:
    """When the knowledge service raises (db down / no line_items table), the
    helper returns None so the tool degrades instead of crashing."""
    run = SimpleNamespace(as_of=datetime(2026, 8, 19, tzinfo=timezone.utc))
    pit = {"symbol": "600519"}
    stub = SimpleNamespace(uow=object())

    def _raise(**_kw):
        raise RuntimeError("db unavailable")

    fake_ks = SimpleNamespace(retrieve_line_items=_raise)
    with patch("investment_research.agent.service.FinancialKnowledgeService", return_value=fake_ks):
        assert AgentOrchestrator._fundamental_coverage_for_research_pit(stub, pit, run) is None
