"""Tests for structured financial line items (Phase 2).

Guards the "no structured facts" hardening: line items are PIT-visible,
revisioned, and a missing period surfaces as "未披露" (unknown), never as
zero — preventing lookahead bias and fabricated figures.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from investment_research.domain.knowledge import FinancialLineItem
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService

AS_OF = datetime(2026, 8, 16, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 6, 30, tzinfo=timezone.utc)


def _hash(symbol: str, period: str, metric: str, value: float) -> str:
    payload = "|".join((
        symbol, period, metric, f"https://example-exchange.com/{symbol}",
        f"{value:.6f}", "亿元", "1.000000", PUBLISHED.isoformat(), metric,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _item(*, period: str, metric: str, value: float, symbol: str = "600519",
          published_at: datetime = PUBLISHED, available_at: datetime = PUBLISHED) -> FinancialLineItem:
    return FinancialLineItem(
        id=uuid4(), market="CN", symbol=symbol, period=period, metric=metric,
        metric_label=metric, value=value, unit="亿元", scale=1.0, yoy_pct=8.0,
        source_name="交易所公告", source_url=f"https://example-exchange.com/{symbol}",
        published_at=published_at, available_at=available_at, valid_from=published_at,
        authority_level=4, data_tier="research_pit",
        content_hash=_hash(symbol, period, metric, value),
    )


def test_line_items_are_pit_visible_and_missing_period_is_unknown(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "li.db")
    service = FinancialKnowledgeService(uow)
    service.ingest_line_item(_item(period="2025FY", metric="revenue", value=1743.0))

    present = service.retrieve_line_items(symbol="600519", as_of=AS_OF)
    assert present.coverage_status == "figures_present"
    assert present.line_items[0].value == 1743.0

    before_publication = service.retrieve_line_items(
        symbol="600519", as_of=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert before_publication.coverage_status == "unknown"
    assert before_publication.line_items == []
    uow.close()


def test_revised_line_item_supersedes_the_prior_revision(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "li.db")
    service = FinancialKnowledgeService(uow)
    original = _item(period="2025FY", metric="revenue", value=1700.0)
    service.ingest_line_item(original)
    # A restated figure (different value -> different hash) must supersede.
    restated = _item(period="2025FY", metric="revenue", value=1743.0)
    stored = service.ingest_line_item(restated)
    assert stored.revision == 2
    assert stored.previous_revision_id == original.id
    results = service.retrieve_line_items(symbol="600519", as_of=AS_OF)
    assert len(results.line_items) == 1
    assert results.line_items[0].value == 1743.0
    uow.close()


def test_retrieve_filters_by_metric_and_period(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "li.db")
    service = FinancialKnowledgeService(uow)
    service.ingest_line_item(_item(period="2025FY", metric="revenue", value=1743.0))
    service.ingest_line_item(_item(period="2026H1", metric="revenue", value=905.0))
    service.ingest_line_item(_item(period="2025FY", metric="net_profit", value=892.0))

    revenue = service.retrieve_line_items(
        symbol="600519", as_of=AS_OF, metrics=["revenue"]
    )
    assert {item.period for item in revenue.line_items} == {"2025FY", "2026H1"}
    assert all(item.metric == "revenue" for item in revenue.line_items)

    fy = service.retrieve_line_items(
        symbol="600519", as_of=AS_OF, periods=["2025FY"]
    )
    assert {item.metric for item in fy.line_items} == {"revenue", "net_profit"}
    uow.close()


def test_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "li.db")
    service = FinancialKnowledgeService(uow)
    bad = _item(period="2025FY", metric="revenue", value=1743.0)
    tampered = bad.model_copy(update={"content_hash": "x" * 64})
    with pytest.raises(ValueError, match="content_hash"):
        service.ingest_line_item(tampered)
    uow.close()
