"""Per-asset fundamental coverage (§3 数据可信度细化).

The system-level ``get_long_term_data_trust`` reports ``evidence_completeness``
(a single 0-100 number) + ``data_as_of``.  The §3 gap wants this refined to
"this stock is missing *which* fundamentals" so the LLM can cite concrete
data-trust gaps per asset (e.g. "茅台 缺 ROE/ROA/营业利润") rather than a
blank "completeness=100".

This helper reads the snapshot's ``line_items`` (raw financial figures, each
with a ``metric`` + ``metric_label``) and checks them against the §6③ six
core fundamental pillars.  Pure + dependency-free so it is unit-testable and
callable from the snapshot builder without a network or a trained model.
"""
from __future__ import annotations

from typing import Iterable, Mapping

# The §6③ six core fundamental pillars + the alias sets they may appear under
# in ``line_items`` (``metric`` key or ``metric_label`` text).  These are the
# pillars the long-term fundamental scoring treats as backend evidence.
EXPECTED_FUNDAMENTALS: list[tuple[str, tuple[str, ...]]] = [
    ("revenue", ("revenue", "total_revenue", "营业收入", "营业总收入", "营收")),
    ("net_profit", ("net_profit", "归母净利润", "净利润", "parent_net_profit")),
    ("gross_margin", ("gross_margin", "毛利率", "销售毛利率")),
    ("operating_profit", ("operating_profit", "营业利润", "营业利润率")),
    ("roe", ("roe", "净资产收益率", "加权净资产收益率", "return_on_equity")),
    ("roa", ("roa", "总资产收益率", "return_on_assets")),
]


def _matches(present_keys: frozenset[str], aliases: Iterable[str]) -> bool:
    return any(alias in present_keys for alias in aliases)


def fundamental_coverage(line_items: Iterable[Mapping[str, object]]) -> dict:
    """Compute which of the §6③ core fundamentals are present for this asset.

    Returns ``{status, expected_count, present, missing, coverage_pct}`` where
    ``present``/``missing`` are the canonical pillar names (revenue, net_profit,
    gross_margin, operating_profit, roe, roa).  Degrades to
    ``status="unavailable"`` when there are no line_items.
    """
    items = [li for li in line_items if isinstance(li, Mapping)] if line_items else []
    if not items:
        return {
            "status": "unavailable",
            "reason": "no_line_items",
            "expected_count": len(EXPECTED_FUNDAMENTALS),
            "present": [],
            "missing": [name for name, _ in EXPECTED_FUNDAMENTALS],
            "coverage_pct": 0.0,
        }

    # Collect every key the line_items expose (metric + metric_label) so aliases
    # resolve regardless of which field the upstream populate chose.
    present_keys: set[str] = set()
    for item in items:
        metric = item.get("metric")
        if isinstance(metric, str) and metric:
            present_keys.add(metric)
        label = item.get("metric_label")
        if isinstance(label, str) and label:
            present_keys.add(label)

    present: list[str] = []
    missing: list[str] = []
    for name, aliases in EXPECTED_FUNDAMENTALS:
        if _matches(frozenset(present_keys), aliases):
            present.append(name)
        else:
            missing.append(name)

    expected = len(EXPECTED_FUNDAMENTALS)
    coverage = (len(present) / expected) if expected else 0.0
    return {
        "status": "ok",
        "expected_count": expected,
        "present": present,
        "missing": missing,
        "coverage_pct": round(coverage * 100, 1),
    }
