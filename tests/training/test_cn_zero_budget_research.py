from datetime import date, datetime, timezone
import json
from types import SimpleNamespace
import importlib.util
from pathlib import Path

from investment_research.training.cn_free_providers import (
    compare_public_daily_payloads,
    deterministic_cross_check,
)
from investment_research.training.cn_research_universe import (
    build_cn_equity_core,
    build_cn_etf_benchmark,
)
from investment_research.training.cn_research_collection import (
    CollectionCursor,
    CursorStore,
    ProviderPolicy,
    ResearchCacheManifest,
    SerialRateLimiter,
    call_with_retry,
)
from investment_research.training.models import PreparedPriceBar


def _load_free_fetcher():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_free_research_data.py"
    spec = importlib.util.spec_from_file_location("free_fetcher_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bar(symbol: str, day: int, amount: float = 1000) -> PreparedPriceBar:
    when = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return PreparedPriceBar(
        symbol=symbol, trade_date=date(2024, 1, day), close_native=10,
        close_normalized=10, volume=100, amount=amount, currency="CNY",
        target_currency="CNY", is_halted=False, is_suspended=False,
        published_at=when, available_at=when, calendar_code="XSHG",
    )


def test_public_provider_comparison_blocks_material_price_or_volume_conflict() -> None:
    primary = json.dumps([
        {"日期": "2024-01-02", "收盘": 10.0, "成交量": 1000},
        {"日期": "2024-01-03", "收盘": 10.0, "成交量": 1000},
    ]).encode()
    backup = json.dumps([
        {"日期": "2024-01-02", "收盘": 10.1, "成交量": 900},
    ]).encode()
    result = compare_public_daily_payloads(primary, backup)
    assert result.severe
    assert result.close_conflicts == 1
    assert result.volume_conflicts == 1
    assert result.missing_dates == 1


def test_cross_check_selection_is_deterministic() -> None:
    first = deterministic_cross_check("600519", date(2026, 7, 14), ratio=0.1)
    assert first == deterministic_cross_check("600519", date(2026, 7, 14), ratio=0.1)
    assert deterministic_cross_check("600519", date(2026, 7, 14), ratio=1)


def test_cn_cohorts_are_separate_and_liquidity_ranked() -> None:
    bars = []
    for symbol, amount in (("600001", 1000), ("000001", 2000)):
        bars.extend(_bar(symbol, (index % 28) + 1, amount) for index in range(260))
    bars.extend(_bar("510300", (index % 28) + 1, 5000) for index in range(30))
    equity = build_cn_equity_core(
        bars, as_of=date(2024, 1, 31), max_symbols=1,
        lookback_sessions=20, minimum_history_sessions=20,
        minimum_coverage_ratio=0.05, minimum_median_amount=0,
    )
    etf = build_cn_etf_benchmark(bars, as_of=date(2024, 1, 31))
    assert [item.symbol for item in equity.members] == ["000001"]
    assert [item.symbol for item in etf.members] == ["510300"]
    assert "historical_universe_incomplete" in equity.blocking_reasons


def test_cursor_replays_five_trading_days_and_is_persistent(tmp_path) -> None:
    store = CursorStore(tmp_path / "cursors.json")
    cursor = CollectionCursor(
        provider="akshare", symbol="600519", adjustment_mode="raw",
        last_successful_trade_date=date(2026, 7, 13),
        updated_at=datetime(2026, 7, 14, tzinfo=timezone.utc), payload_hash="a" * 64,
    )
    store.put(cursor)
    restored = store.get("akshare", "600519", "raw")
    assert restored == cursor
    assert restored.overlap_start == date(2026, 7, 6)


def test_retry_uses_serial_limiter_and_bounded_backoff() -> None:
    clock = iter([0.0, 0.0, 0.5, 0.5])
    sleeps: list[float] = []
    limiter = SerialRateLimiter(2, monotonic=lambda: next(clock), sleep=sleeps.append)
    calls = 0

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return "ok"

    result, attempts = call_with_retry(
        flaky, policy=ProviderPolicy(requests_per_second=2, max_attempts=2),
        limiter=limiter, sleep=sleeps.append, random_value=lambda: 0,
    )
    assert (result, attempts) == ("ok", 2)
    assert 1.0 in sleeps


def test_research_cache_expires_after_three_trading_days() -> None:
    cache = ResearchCacheManifest(
        provider="akshare", symbol="600519", adjustment_mode="raw",
        fetched_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        latest_source_date=date(2026, 7, 10), coverage_start=date(2020, 1, 1),
        coverage_end=date(2026, 7, 10), payload_hash="a" * 64,
        schema_hash="b" * 64, quality_status="passed",
    )
    assert cache.state(as_of=date(2026, 7, 13)) == "fresh"
    assert cache.state(as_of=date(2026, 7, 15)) == "stale_usable"
    assert cache.state(as_of=date(2026, 7, 16)) == "expired"


def test_cn_primary_failure_uses_baostock_and_never_yfinance(monkeypatch, tmp_path) -> None:
    module = _load_free_fetcher()

    class Primary:
        name = "akshare"

        def fetch(self, *args, **kwargs):
            raise RuntimeError("akshare outage")

    class Backup:
        name = "baostock"

        def fetch(self, *args, **kwargs):
            return SimpleNamespace(payload='[{"日期":"2026-07-14","收盘":10}]'.encode(), row_count=1)

    class BackupContext:
        def __enter__(self):
            return Backup()

        def __exit__(self, *args):
            return None

    class Service:
        def persist(self, **kwargs):
            return SimpleNamespace(payload_hash="a" * 64)

    monkeypatch.setattr(module, "AkshareDailyResearchProvider", Primary)
    monkeypatch.setattr(module, "BaostockDailyResearchProvider", BackupContext)
    output = module._collect_cn_prices(
        Service(), ["600519"], full_history=False, lookback_days=3,
        cross_check_ratio=0, cursor_store=module.CursorStore(tmp_path / "cursor.json"),
        config={"primary_requests_per_second": 100, "backup_requests_per_second": 100, "max_attempts": 1, "retry_backoff_seconds": [0]},
    )
    assert output
    assert all(item["provider"] == "baostock" for item in output)
    assert all(item["provider_chain"] == ["akshare", "baostock"] for item in output)


def test_cn_generic_compatibility_path_is_fail_closed() -> None:
    module = _load_free_fetcher()
    result = module._collect_price(None, "cn", "600519", {"markets": {"cn": {"prices": "akshare"}}})
    assert result["status"] == "fetch_failed"
    assert result["provider_chain"] == ["akshare", "baostock"]
