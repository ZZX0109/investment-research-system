from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from investment_research.domain.trusted_market import RawDataBatch, VersionedMarketBar
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.market_quality import MarketDataQualityGate


def _batch(now: datetime) -> RawDataBatch:
    return RawDataBatch(
        provider="licensed-primary",
        request_id="request-1",
        dataset="daily_bars",
        payload_ref="s3://raw/request-1.json",
        payload_hash=hashlib.sha256(b"raw").hexdigest(),
        schema_version="v1",
        fetched_at=now,
        available_at=now,
    )


def _bar(batch: RawDataBatch, now: datetime, *, revision: int = 1, close: float = 10.0) -> VersionedMarketBar:
    return VersionedMarketBar(
        raw_batch_id=batch.id,
        symbol="600519.SH",
        provider=batch.provider,
        interval="1d",
        bar_start=datetime(2026, 7, 14, 15, tzinfo=timezone(timedelta(hours=8))),
        trade_date=date(2026, 7, 14),
        revision=revision,
        open=10,
        high=max(10.5, close),
        low=min(9.5, close),
        close=close,
        volume=1000,
        source_time=now,
        ingest_time=now,
        available_at=now,
        as_of=now,
        normalized_hash=hashlib.sha256(f"{revision}:{close}".encode()).hexdigest(),
    )


def test_market_bar_revision_is_append_only_and_active_pointer_moves(tmp_path) -> None:
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)
    uow = SQLiteUnitOfWork(tmp_path / "trusted.db")
    batch = uow.trusted_market.add_raw_batch(_batch(now))
    uow.trusted_market.add_bar(_bar(batch, now))
    uow.trusted_market.add_bar(_bar(batch, now + timedelta(minutes=1), revision=2, close=10.2))

    active = uow.trusted_market.active_bars("600519.SH", "1d", as_of=now + timedelta(minutes=2))
    rows = uow.connection.execute("SELECT revision,active FROM versioned_market_bars ORDER BY revision").fetchall()
    assert [(row[0], bool(row[1])) for row in rows] == [(1, False), (2, True)]
    assert len(active) == 1 and active[0].revision == 2


def test_quality_gate_rejects_future_and_duplicate_bars() -> None:
    now = datetime(2026, 7, 14, 8, tzinfo=timezone.utc)
    batch = _batch(now)
    bar = _bar(batch, now + timedelta(minutes=1))
    result = MarketDataQualityGate().evaluate_bars([bar, bar], cutoff=now)
    assert result.status == "failed"
    assert any(issue.startswith("future_data") for issue in result.issues)
    assert any(issue.startswith("duplicate_bar") for issue in result.issues)
