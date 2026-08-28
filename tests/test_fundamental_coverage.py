"""§3 数据可信度细化 — per-asset fundamental coverage regression tests.

``fundamental_coverage`` checks the snapshot's ``line_items`` against the
§6③ six core fundamental pillars so the LLM can cite concrete per-asset
data-trust gaps ("茅台 缺 ROE/ROA") instead of a blank completeness=100.
"""
from __future__ import annotations

from investment_research.agent.evaluation import fundamental_coverage


def test_fundamental_coverage_partial() -> None:
    # 600519-style line_items: revenue + net_profit + gross_margin present,
    # operating_profit/roe/roa missing.
    line_items = [
        {"metric": "revenue", "metric_label": "营业总收入", "value": 1743.0},
        {"metric": "net_profit", "metric_label": "归母净利润", "value": 892.0},
        {"metric": "gross_margin", "metric_label": "毛利率", "value": 91.5},
    ]
    cov = fundamental_coverage(line_items)
    assert cov["status"] == "ok"
    assert cov["expected_count"] == 6
    assert set(cov["present"]) == {"revenue", "net_profit", "gross_margin"}
    assert set(cov["missing"]) == {"operating_profit", "roe", "roa"}
    assert cov["coverage_pct"] == 50.0


def test_fundamental_coverage_resolves_aliases() -> None:
    # ROE/ROA surfaced under their Chinese metric_label, not the metric key.
    line_items = [
        {"metric": "total_revenue", "metric_label": "营业收入"},
        {"metric": "x", "metric_label": "归母净利润"},
        {"metric": "y", "metric_label": "毛利率"},
        {"metric": "z", "metric_label": "营业利润"},
        {"metric": "a", "metric_label": "加权净资产收益率"},  # roe alias
        {"metric": "b", "metric_label": "总资产收益率"},  # roa alias
    ]
    cov = fundamental_coverage(line_items)
    assert cov["status"] == "ok"
    assert cov["missing"] == []
    assert cov["coverage_pct"] == 100.0


def test_fundamental_coverage_degrades_when_empty() -> None:
    cov = fundamental_coverage([])
    assert cov["status"] == "unavailable"
    assert cov["reason"] == "no_line_items"
    assert cov["coverage_pct"] == 0.0
    assert len(cov["missing"]) == 6
