"""Direct 60-session -> 20-session path model tests."""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from investment_research.domain.trusted_market import RawDataBatch, VersionedMarketBar
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.training.price_path.direct_multihorizon_runner import DirectMultiHorizonPricePathRunner


_ROOT = Path(__file__).resolve().parent.parent
_SYMBOLS = ["600519", "600547", "600522", "000001", "000002", "000333"]


def _add_bars(repo, symbol: str, count: int) -> None:
    batch = RawDataBatch(
        provider="test", request_id=f"direct-{symbol}", dataset="direct", payload_ref="mem",
        payload_hash=hashlib.sha256(symbol.encode()).hexdigest(), schema_version="1", symbol=symbol,
        interval="1d", fetched_at=datetime.now(timezone.utc), available_at=datetime.now(timezone.utc),
        time_semantics="test_fixture", data_tier="test_fixture",
    )
    repo.add_raw_batch(batch)
    start = date(2020, 1, 2)
    for index in range(count):
        day = start + timedelta(days=index)
        stamp = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        # A deterministic but non-flat daily path lets direct outputs vary.
        close = 100.0 * (1 + 0.08 * math.sin(index / 6.0) + 0.04 * math.sin(index / 1.9))
        repo.add_bar(VersionedMarketBar(
            raw_batch_id=batch.id, symbol=symbol, provider="test", interval="1d", bar_start=stamp,
            trade_date=day, calendar_code="XSHG", adjustment_mode="qfq", open=close * 0.998,
            high=close * 1.018, low=close * 0.982, close=close,
            volume=1_000_000 + index * 5000.0 + 40000 * math.cos(index / 4.0),
            amount=100_000_000 + index * 10000.0, turnover_rate=0.8 + 0.1 * math.sin(index / 8.0),
            source_time=stamp, ingest_time=datetime.now(timezone.utc), available_at=datetime.now(timezone.utc),
            as_of=stamp, normalized_hash=hashlib.sha256(f"{symbol}-{day}".encode()).hexdigest(),
        ))


def _trained_runner(tmp_path: Path):
    uow = SQLiteUnitOfWork(tmp_path / "market.db")
    for symbol in _SYMBOLS:
        _add_bars(uow.trusted_market, symbol, 150)
    runner = DirectMultiHorizonPricePathRunner(tmp_path, vendored_root=_ROOT)
    samples, market_features, _ = runner.build_dataset(uow.trusted_market, _SYMBOLS)
    assert samples and samples[0].sequence.shape == (60, 10)
    outcome = runner.train(samples, market_features, epochs=1, batch_size=128)
    assert outcome["status"] == "ok", outcome
    return uow, runner


def test_direct_model_writes_independent_evaluated_artifacts(tmp_path: Path) -> None:
    uow, runner = _trained_runner(tmp_path)
    try:
        root = tmp_path / "artifacts" / "price_path" / "direct_multihorizon"
        assert runner.is_available()
        assert (root / "model.pt").exists()
        assert (root / "feature_contract.json").exists()
        assert (root / "evaluation.json").exists()
        assert (root / "manifest.json").exists()
    finally:
        uow.close()


def test_direct_forecast_is_20_sessions_ordered_and_non_recursive(tmp_path: Path) -> None:
    uow, runner = _trained_runner(tmp_path)
    try:
        result = runner.forecast_path_for_symbol(uow.trusted_market, "600519")
        assert result is not None and result["status"] == "ok"
        assert result["model"] == "direct_multihorizon"
        assert result["path_mode"] == "direct_20d"
        assert len(result["points"]) == 21
        assert len(result["historical_points"]) == 63
        predicted = np.asarray([point["predicted"] for point in result["points"][1:]], dtype=float)
        assert len(np.unique(np.round(predicted, 5))) > 1
        for point in result["points"]:
            assert point["q10"] <= point["predicted"] <= point["q90"]
        # Future points never land on Saturday/Sunday.
        for point in result["points"][1:]:
            assert date.fromisoformat(point["date"]).weekday() < 5
        metrics = result["metrics"]["test"]
        assert set(metrics) == {"1d", "5d", "20d"}
    finally:
        uow.close()


def test_direct_forecast_supports_close_only_frozen_dashboard_series(tmp_path: Path) -> None:
    uow, runner = _trained_runner(tmp_path)
    try:
        original = uow.trusted_market.active_bars("600519", "1d")

        class FrozenRepo:
            def active_bars(self, _symbol, _interval):
                return [
                    type("FrozenBar", (), {"bar_start": item.bar_start, "trade_date": item.trade_date, "close": item.close})()
                    for item in original
                ]

        result = runner.forecast_path_for_symbol(FrozenRepo(), "600519")
        assert result is not None and result["status"] == "ok"
        assert len(result["points"]) == 21
    finally:
        uow.close()


def test_direct_model_does_not_claim_availability_without_all_artifacts(tmp_path: Path) -> None:
    runner = DirectMultiHorizonPricePathRunner(tmp_path, vendored_root=_ROOT)
    assert runner.is_available() is False
    assert runner.forecast_path_for_symbol(object(), "600519") is None
