"""Tests for scripts.seed_market_bars_from_akshare (§6 ② + §1 data-root unblock —
real daily bars in versioned_market_bars)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from investment_research.repository.sqlite import SQLiteUnitOfWork


def test_seed_symbol_stores_daily_bars(tmp_path: Path) -> None:
    """_seed_symbol fetches akshare kline + stores VersionedMarketBar rows —
    populates the previously-empty versioned_market_bars (data-root unblock)."""
    import scripts.seed_market_bars_from_akshare as mod

    # Mock akshare's SINA kline (no network in test).
    class _FakeAK:
        @staticmethod
        def stock_zh_a_daily(symbol, start_date, end_date, adjust):
            return pd.DataFrame({
                "date": [pd.Timestamp("2024-12-30").date(), pd.Timestamp("2024-12-31").date()],
                "open": [1437.0, 1437.02], "high": [1450.0, 1455.49],
                "low": [1430.0, 1433.83], "close": [1440.0, 1435.7],
                "volume": [3000000.0, 3935445.0], "amount": [4e9, 6e9], "turnover": [0.002, 0.003],
            })
    import sys
    sys.modules["akshare"] = _FakeAK()
    uow = SQLiteUnitOfWork(tmp_path / "mb.db")
    try:
        repo = uow.trusted_market
        n = mod._seed_symbol(repo, "600519", start="20240101", end="20241231")
        assert n == 2  # both bars stored
        bars = repo.active_bars("600519", "1d")
        assert len(bars) == 2
        assert all(b.symbol == "600519" and b.interval == "1d" for b in bars)
        assert all(b.adjustment_mode == "qfq" for b in bars)
    finally:
        uow.close()
        sys.modules.pop("akshare", None)


def test_seed_symbol_skips_gracefully_when_kline_fails(tmp_path: Path) -> None:
    """When the kline fetch degrades (network gated), _seed_symbol returns 0
    gracefully (no crash, no fabrication)."""
    import scripts.seed_market_bars_from_akshare as mod

    class _FakeAK:
        @staticmethod
        def stock_zh_a_daily(*a, **k):
            raise RuntimeError("ProxyError")
    import sys
    sys.modules["akshare"] = _FakeAK()
    uow = SQLiteUnitOfWork(tmp_path / "mb2.db")
    try:
        n = mod._seed_symbol(uow.trusted_market, "600519", start="20240101", end="20241231")
        assert n == 0  # graceful degrade
    finally:
        uow.close()
        sys.modules.pop("akshare", None)
