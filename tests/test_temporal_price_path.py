"""Tests for TemporalPricePathRunner (§1 row-5 round 29 — price-only temporal
LSTM, the kittenCN architecture's temporal core trained on real daily bars)."""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from investment_research.domain.trusted_market import RawDataBatch, VersionedMarketBar
from investment_research.repository.sqlite import SQLiteUnitOfWork


def _add_bars(repo, symbol: str, n: int, *, start_price: float = 100.0) -> None:
    """n synthetic daily bars with a sinusoidal price so returns vary."""
    batch = RawDataBatch(
        provider="test", request_id=f"t-{symbol}", dataset="t",
        payload_ref="mem", payload_hash=hashlib.sha256(symbol.encode()).hexdigest(),
        schema_version="1", symbol=symbol, interval="1d",
        fetched_at=datetime.now(timezone.utc), available_at=datetime.now(timezone.utc),
        time_semantics="test_fixture", data_tier="test_fixture",
    )
    repo.add_raw_batch(batch)
    d0 = date(2020, 1, 2)
    for i in range(n):
        d = d0 + timedelta(days=i)
        bs = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        c = start_price * (1.0 + 0.15 * math.sin(i / 5.0) + 0.05 * math.sin(i / 1.7))
        repo.add_bar(VersionedMarketBar(
            raw_batch_id=batch.id, symbol=symbol, provider="test", interval="1d",
            bar_start=bs, trade_date=d, calendar_code="XSHG", adjustment_mode="qfq",
            open=c * 0.999, high=c * 1.01, low=c * 0.99, close=c,
            volume=1e6 + i * 1000.0, source_time=bs, ingest_time=datetime.now(timezone.utc),
            available_at=datetime.now(timezone.utc), as_of=bs,
            normalized_hash=hashlib.sha256(f"{symbol}-{d.isoformat()}".encode()).hexdigest(),
        ))


def _six_symbols() -> list[str]:
    return ["600519", "600547", "600522", "000001", "000002", "000333"]


def test_build_dataset_and_train_produces_temporal_weight(tmp_path: Path) -> None:
    """build_dataset emits (20-return sequence, next-day return) pairs; train
    fits the LSTM with MSE + saves the .pt + accuracy artifact (训练说清楚)."""
    from investment_research.training.price_path.temporal_runner import (
        TemporalPricePathRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "tp.db")
    repo = uow.trusted_market
    try:
        for sym in _six_symbols():
            _add_bars(repo, sym, 60)
        runner = TemporalPricePathRunner(tmp_path)
        rows = runner.build_dataset(repo, _six_symbols())
        assert len(rows) > 200
        assert rows[0][0].shape == (20, 1)  # 20-return sequence
        acc = runner.train(rows, epochs=1)
        assert acc["status"] == "ok"
        assert isinstance(acc["directional_accuracy"], float)
        assert runner.is_available()  # .pt written
    finally:
        uow.close()


def test_forecast_path_returns_points_shape(tmp_path: Path) -> None:
    """forecast_path_for_symbol returns the points list (drop-in compatible with
    build_price_path_projection): anchor point carries the actual latest close;
    forecast points carry predicted=q50 + q10/q90 fan, actual=None."""
    from investment_research.training.price_path.temporal_runner import (
        TemporalPricePathRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "tp2.db")
    repo = uow.trusted_market
    try:
        for sym in _six_symbols():
            _add_bars(repo, sym, 60)
        runner = TemporalPricePathRunner(tmp_path)
        rows = runner.build_dataset(repo, _six_symbols())
        runner.train(rows, epochs=1)
        out = runner.forecast_path_for_symbol(repo, "600519", horizon=10)
        assert out is not None and out["status"] == "ok"
        assert out["model"] == "temporal_lstm (kittenCN price-only)"
        pts = out["points"]
        assert len(pts) == 11  # horizon + 1
        assert pts[0]["actual"] is not None  # anchor
        assert all(p["actual"] is None for p in pts[1:])  # forecast points
        assert all("q10" in p and "q90" in p and "predicted" in p for p in pts)
    finally:
        uow.close()


def test_forecast_degrades_when_no_model(tmp_path: Path) -> None:
    """Without the trained .pt, forecast returns None (is_available False) —
    never synthesizes a path."""
    from investment_research.training.price_path.temporal_runner import (
        TemporalPricePathRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "tp3.db")
    try:
        runner = TemporalPricePathRunner(tmp_path)
        assert runner.is_available() is False
        assert runner.forecast_path_for_symbol(uow.trusted_market, "600519") is None
    finally:
        uow.close()
