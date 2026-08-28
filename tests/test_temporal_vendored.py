"""Tests for TemporalVendoredRunner (§1 row-5 round 31 — the VENDORED kittenCN
``TemporalHybridNet``, the named depthwise-conv + attention hybrid trained
price-only on real daily bars)."""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from investment_research.domain.trusted_market import RawDataBatch, VersionedMarketBar
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.training.price_path.temporal_vendored_runner import (
    TemporalVendoredRunner,
)


def _add_bars(repo, symbol: str, n: int, *, start_price: float = 100.0) -> None:
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


# The vendored ``vendor/kittencn/src`` tree lives at the real repo root, not in
# the per-test tmp_path; point ``vendored_root`` there while keeping artifacts
# (the trained .pt) in tmp_path so tests never clobber real weights.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_build_dataset_and_train_produces_vendored_weight(tmp_path: Path) -> None:
    """build_dataset emits (20-return sequence, next-day return) pairs; train
    fits the VENDORED TemporalHybridNet + writes the .pt + accuracy artifact.
    Needs >= 200 rows → 6 symbols × 60 bars (= 234 pairs > 200)."""
    uow = SQLiteUnitOfWork(tmp_path / "t.db")
    repo = uow.trusted_market
    for sym in _six_symbols():
        _add_bars(repo, sym, 60)
    runner = TemporalVendoredRunner(tmp_path, vendored_root=_REPO_ROOT)
    rows = runner.build_dataset(repo, _six_symbols())
    assert len(rows) >= 200
    acc = runner.train(rows, epochs=1, batch_size=64, seed=42)
    assert acc["status"] == "ok", acc
    assert acc["n_val"] > 0
    assert "directional_accuracy" in acc
    assert "mean_abs_error" in acc
    assert (tmp_path / "artifacts" / "price_path" / "temporal_hybrid.pt").exists()
    assert (tmp_path / "artifacts" / "price_path" / "temporal_hybrid_accuracy.json").exists()


def test_forecast_produces_vendored_points(tmp_path: Path) -> None:
    """After training, forecast_path_for_symbol returns a daily q10/q50/q90 path
    with the vendored model tag + honest directional accuracy."""
    uow = SQLiteUnitOfWork(tmp_path / "t.db")
    repo = uow.trusted_market
    for sym in _six_symbols():
        _add_bars(repo, sym, 60)
    runner = TemporalVendoredRunner(tmp_path, vendored_root=_REPO_ROOT)
    rows = runner.build_dataset(repo, _six_symbols())
    runner.train(rows, epochs=1, batch_size=64, seed=42)
    out = runner.forecast_path_for_symbol(repo, "600519", horizon=10)
    assert out is not None and out["status"] == "ok"
    assert out["model"] == "temporal_hybrid (vendored kittenCN, price-only)"
    pts = out["points"]
    assert len(pts) == 11  # anchor + 10 forecast days
    assert pts[0]["actual"] is not None  # anchor carries latest close
    assert all(p["predicted"] is not None for p in pts)
    assert pts[0]["q10"] <= pts[0]["predicted"] <= pts[0]["q90"]
    tms = out["temporal_model_status"]
    assert tms["vendored_source"] is True and tms["trained_weights"] is True
    assert tms["ready"] is True


def test_forecast_degrades_when_untrained(tmp_path: Path) -> None:
    """With no trained weights, forecast returns None (→ quantile fan fallback)."""
    uow = SQLiteUnitOfWork(tmp_path / "t.db")
    repo = uow.trusted_market
    _add_bars(repo, "600519", 40)
    runner = TemporalVendoredRunner(tmp_path, vendored_root=_REPO_ROOT)
    assert runner.forecast_path_for_symbol(repo, "600519") is None


def test_ptft_vssm_build_and_forecast(tmp_path: Path) -> None:
    """§1 row-5 round 31: the OTHER named model ``ptft_vssm`` (PTFTVSSMEnsemble)
    also trains + forecasts via the configurable runner."""
    uow = SQLiteUnitOfWork(tmp_path / "t.db")
    repo = uow.trusted_market
    for sym in _six_symbols():
        _add_bars(repo, sym, 60)
    runner = TemporalVendoredRunner(tmp_path, vendored_root=_REPO_ROOT, model_kind="ptft_vssm")
    rows = runner.build_dataset(repo, _six_symbols())
    assert len(rows) >= 200
    acc = runner.train(rows, epochs=1, batch_size=64, seed=42)
    assert acc["status"] == "ok", acc
    assert "ptft_vssm" in acc["architecture"]
    out = runner.forecast_path_for_symbol(repo, "600519", horizon=8)
    assert out is not None and out["status"] == "ok"
    assert out["model"] == "ptft_vssm (vendored kittenCN, price-only)"
    assert len(out["points"]) == 9
    # the ptft_vssm weight is a SEPARATE artifact (does not clobber temporal_hybrid)
    assert (tmp_path / "artifacts" / "price_path" / "temporal_ptft_vssm.pt").exists()
