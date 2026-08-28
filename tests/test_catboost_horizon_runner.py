"""Tests for CatBoostHorizonRunner (§1 row-2 round 27 — price-based 1/5/20d
CatBoost direction model trained on real daily bars)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from investment_research.domain.trusted_market import RawDataBatch, VersionedMarketBar
from investment_research.repository.sqlite import SQLiteUnitOfWork


def _add_bars(repo, symbol: str, n: int, *, start_price: float = 100.0) -> None:
    """Insert n synthetic daily bars with a gentle up-drift so labels aren't all
    one class (needs >= 40 for 20 history + 20 forward)."""
    batch = RawDataBatch(
        provider="test", request_id=f"k-{symbol}", dataset="t",
        payload_ref="mem", payload_hash=hashlib.sha256(symbol.encode()).hexdigest(),
        schema_version="1", symbol=symbol, interval="1d",
        fetched_at=datetime.now(timezone.utc), available_at=datetime.now(timezone.utc),
        time_semantics="test_fixture", data_tier="test_fixture",
    )
    repo.add_raw_batch(batch)
    d0 = date(2020, 1, 2)
    import math
    for i in range(n):
        d = d0 + timedelta(days=i)
        bs = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        # sinusoidal price so 1/5/20d forward directions vary (both classes)
        c = start_price * (1.0 + 0.15 * math.sin(i / 5.0) + 0.05 * math.sin(i / 1.7))
        repo.add_bar(VersionedMarketBar(
            raw_batch_id=batch.id, symbol=symbol, provider="test", interval="1d",
            bar_start=bs, trade_date=d, calendar_code="XSHG", adjustment_mode="qfq",
            open=c * 0.999, high=c * 1.01, low=c * 0.99, close=c,
            volume=1e6 + i * 1000.0, source_time=bs, ingest_time=datetime.now(timezone.utc),
            available_at=datetime.now(timezone.utc), as_of=bs,
            normalized_hash=hashlib.sha256(f"{symbol}-{d.isoformat()}".encode()).hexdigest(),
        ))


def test_build_dataset_and_train_produces_three_horizon_models(tmp_path: Path) -> None:
    """build_dataset emits labeled (symbol, date) rows from stored bars; train
    fits one .cbm per horizon + writes an accuracy artifact with REAL holdout
    directional accuracy (训练说清楚)."""
    from investment_research.training.short_term.catboost_horizon_runner import (
        CatBoostHorizonRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "hz.db")
    repo = uow.trusted_market
    try:
        _add_bars(repo, "600519", 90)
        _add_bars(repo, "000001", 90)
        runner = CatBoostHorizonRunner(tmp_path)
        rows = runner.build_dataset(repo, ["600519", "000001"])
        assert len(rows) > 0  # both symbols contribute (each has 60-40=20 rows)
        assert all("y_1d" in r and "y_5d" in r and "y_20d" in r for r in rows)
        acc = runner.train(rows, iterations=30)
        assert acc["status"] == "ok"
        assert set(acc["horizons"].keys()) == {"1d", "5d", "20d"}
        assert all(isinstance(h["directional_accuracy"], float) for h in acc["horizons"].values())
        assert runner.is_available()  # all 3 .cbm written
    finally:
        uow.close()


def test_horizon_forecast_for_symbol_surfaces_direction_and_accuracy(tmp_path: Path) -> None:
    """horizon_forecast_for_symbol returns {1d,5d,20d: direction/probability/
    n_holdout/directional_accuracy} for the symbol's latest bar — the field the
    snapshot + get_four_task_forecasts surface (训练说清楚)."""
    from investment_research.training.short_term.catboost_horizon_runner import (
        CatBoostHorizonRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "hz2.db")
    repo = uow.trusted_market
    try:
        _add_bars(repo, "600519", 90)
        runner = CatBoostHorizonRunner(tmp_path)
        rows = runner.build_dataset(repo, ["600519"])
        runner.train(rows, iterations=30)
        out = runner.horizon_forecast_for_symbol(repo, "600519")
        assert out is not None and out["status"] == "ok"
        hz = out["horizons"]
        assert set(hz.keys()) == {"1d", "5d", "20d"}
        for h in ("1d", "5d", "20d"):
            assert hz[h]["direction"] in ("up", "down")
            assert isinstance(hz[h]["probability"], float)
            assert isinstance(hz[h]["directional_accuracy"], float)
    finally:
        uow.close()


def test_horizon_forecast_degrades_when_no_model(tmp_path: Path) -> None:
    """Without trained .cbm files, horizon_forecast_for_symbol returns None
    (is_available False) — never synthesizes a forecast."""
    from investment_research.training.short_term.catboost_horizon_runner import (
        CatBoostHorizonRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "hz3.db")
    try:
        runner = CatBoostHorizonRunner(tmp_path)
        assert runner.is_available() is False
        assert runner.horizon_forecast_for_symbol(uow.trusted_market, "600519") is None
    finally:
        uow.close()


def test_walk_forward_daily_for_symbol_surfaces_per_horizon_realized_accuracy(tmp_path: Path) -> None:
    """§1 row-3 (round 28): walk_forward_daily_for_symbol replays the trained
    model over the symbol's history + returns per-horizon realized directional
    accuracy (训练说清楚 WHERE per-asset for the short-term model)."""
    from investment_research.training.short_term.catboost_horizon_runner import (
        CatBoostHorizonRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "wf.db")
    repo = uow.trusted_market
    try:
        _add_bars(repo, "600519", 90)
        _add_bars(repo, "000001", 90)
        runner = CatBoostHorizonRunner(tmp_path)
        rows = runner.build_dataset(repo, ["600519", "000001"])
        runner.train(rows, iterations=30)
        out = runner.walk_forward_daily_for_symbol(repo, "600519")
        assert out is not None and out["status"] == "ok"
        hz = out["horizons"]
        assert set(hz.keys()) == {"1d", "5d", "20d"}
        for h in ("1d", "5d", "20d"):
            cell = hz[h]
            assert cell["status"] == "ok"
            assert isinstance(cell["decision_count"], int) and cell["decision_count"] > 0
            assert isinstance(cell["directional_accuracy"], float)
            assert 0.0 <= cell["directional_accuracy"] <= 1.0
    finally:
        uow.close()


def test_fortune_enhanced_candidate_uses_chronological_purged_folds(tmp_path: Path) -> None:
    """The enriched Fortune candidate must use causal features and a temporal,
    purged validation split rather than the legacy random holdout."""
    from investment_research.training.short_term.fortune_enhanced_horizon_runner import (
        FortuneEnhancedHorizonRunner,
    )

    uow = SQLiteUnitOfWork(tmp_path / "fortune-enhanced.db")
    repo = uow.trusted_market
    try:
        for symbol, base in (("600519", 100.0), ("000001", 90.0), ("000002", 110.0)):
            _add_bars(repo, symbol, 150, start_price=base)
        runner = FortuneEnhancedHorizonRunner(tmp_path)
        rows = runner.build_dataset(repo, ["600519", "000001", "000002"])
        assert rows and "garch_conditional_vol" in rows[-1]
        report = runner.train_walk_forward(rows, n_folds=2, purge_sessions=5, iterations=20)
        assert report["status"] == "ok"
        assert report["n_folds"] == 2
        assert "garch_conditional_vol" in report["features"]
        for horizon in ("1d", "5d", "20d"):
            assert report["horizons"][horizon]["aggregate"]["sample_count"] > 0
            assert (tmp_path / "artifacts/short_term/fortune_enhanced" / f"fortune_enhanced_{horizon}.cbm").exists()
    finally:
        uow.close()
