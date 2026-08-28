"""Tests for scripts.seed_fundamentals_from_fortune (§6 ③ real roe/roa line_items
from the fortune indicator adapter)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService


def test_seed_symbol_ingests_real_roe_roa_as_line_items(tmp_path: Path) -> None:
    """_seed_symbol ingests the fortune adapter's roe/roa as real line_items,
    and fundamental_coverage then sees them present (50%→83% for a stock that
    had only revenue/net_profit/gross_margin)."""
    import scripts.seed_fundamentals_from_fortune as mod

    uow = SQLiteUnitOfWork(tmp_path / "sf.db")
    service = FinancialKnowledgeService(uow)
    # Seed the 3 demo pillars first (mirror the existing demo seed).
    from investment_research.domain.knowledge import FinancialLineItem
    pub = datetime(2025, 8, 30, tzinfo=timezone.utc)
    for metric, value, unit in [("revenue", 1743.0, "亿元"), ("net_profit", 820.0, "亿元"), ("gross_margin", 0.91, "ratio")]:
        hk = dict(symbol="600519", period="2025FY", metric=metric, source_url=f"https://ex.com/600519",
                  value=value, unit=unit, scale=1.0, published_at=pub, metric_label=metric)
        service.ingest_line_item(FinancialLineItem(market="CN", source_name="seed", available_at=pub,
                                                    valid_from=pub, content_hash=FinancialLineItem.content_hash_of(**hk), **hk))
    # Mock the fortune fetch to return real roe/roa (no network in test).
    class _FR:
        status = "ok"; degraded = False; error = None
        data = {"roe": 9.18, "roa": 8.9016, "gross_margin": None, "net_margin": 7.603}
    _orig_fetch = mod.fetch_fundamentals
    _orig_stmts = mod._seed_statements
    mod.fetch_fundamentals = lambda sym: _FR()
    mod._seed_statements = lambda svc, sym, as_of: 0  # isolate ratio ingest (no akshare)
    try:
        n = mod._seed_symbol(service, "600519", pub)
        assert n == 3  # roe + roa + net_margin (gross_margin None → skipped)
        # fundamental_coverage now sees roe/roa present (5/6, missing operating_profit).
        res = service.retrieve_line_items(symbol="600519", as_of=datetime(2026, 8, 19, tzinfo=timezone.utc), market="CN")
        from investment_research.agent.evaluation import fundamental_coverage
        items = [li.model_dump() for li in res.line_items]
        cov = fundamental_coverage(items)
        assert cov["coverage_pct"] >= 80.0
        assert "roe" in cov["present"] and "roa" in cov["present"]
        assert "operating_profit" in cov["missing"]  # absolute, not from indicators
    finally:
        uow.close()
        mod.fetch_fundamentals = _orig_fetch
        mod._seed_statements = _orig_stmts


def test_seed_symbol_skips_gracefully_when_fetch_degrades(tmp_path: Path) -> None:
    """When the fortune fetch degrades (network gated), _seed_symbol skips
    gracefully (0 ingested, no crash) — the §6 ③ path never blocks."""
    import scripts.seed_fundamentals_from_fortune as mod

    class _FR:
        status = "network_unavailable"; degraded = True; error = "ReadTimeout"; data = None
    _orig_fetch = mod.fetch_fundamentals
    _orig_stmts = mod._seed_statements
    mod.fetch_fundamentals = lambda sym: _FR()
    mod._seed_statements = lambda svc, sym, as_of: 0  # isolate ratio-degrade path (no akshare)
    uow = SQLiteUnitOfWork(tmp_path / "sf2.db")
    try:
        service = FinancialKnowledgeService(uow)
        n = mod._seed_symbol(service, "600519", datetime(2025, 8, 30, tzinfo=timezone.utc))
        assert n == 0  # graceful degrade, no fabrication
    finally:
        uow.close()
        mod.fetch_fundamentals = _orig_fetch
        mod._seed_statements = _orig_stmts


def test_seed_statements_ingests_operating_profit_revenue_net_profit(tmp_path: Path) -> None:
    """_seed_statements ingests REAL SINA statement absolutes
    (operating_profit/revenue/net_profit) as line_items — closes the last 1/6
    gap (operating_profit) with real data, not demo seed."""
    import scripts.seed_fundamentals_from_fortune as mod
    import pandas as pd

    # Mock akshare's SINA income-statement endpoint (no network in test).
    class _FakeAK:
        @staticmethod
        def stock_financial_report_sina(stock, symbol):
            return pd.DataFrame({
                "营业利润": [61411291686.27],
                "营业收入": [90703260964.48],
                "净利润": [46033330566.78],
            })
    import sys
    sys.modules["akshare"] = _FakeAK()
    uow = SQLiteUnitOfWork(tmp_path / "ss.db")
    try:
        service = FinancialKnowledgeService(uow)
        n = mod._seed_statements(service, "600519", datetime(2025, 8, 30, tzinfo=timezone.utc))
        assert n == 3  # operating_profit + revenue + net_profit
        res = service.retrieve_line_items(symbol="600519", as_of=datetime(2026, 8, 19, tzinfo=timezone.utc), market="CN")
        from investment_research.agent.evaluation import fundamental_coverage
        cov = fundamental_coverage([li.model_dump() for li in res.line_items])
        assert "operating_profit" in cov["present"]
        assert "revenue" in cov["present"] and "net_profit" in cov["present"]
    finally:
        uow.close()
        sys.modules.pop("akshare", None)
