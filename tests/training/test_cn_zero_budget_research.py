from datetime import date, datetime, timezone
import json
from types import SimpleNamespace
import importlib.util
from pathlib import Path
import time

from investment_research.training.cn_free_providers import (
    compare_public_daily_payloads,
    deterministic_cross_check,
    _validate_daily_frame,
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


def test_provider_history_coverage_difference_is_degraded_not_conflict() -> None:
    primary = json.dumps([
        {"日期": "2024-01-02", "收盘": 10.0, "成交量": 1000},
        {"日期": "2024-01-03", "收盘": 10.0, "成交量": 1000},
    ]).encode()
    backup = json.dumps([
        {"日期": "2024-01-03", "收盘": 10.0, "成交量": 1000},
    ]).encode()
    result = compare_public_daily_payloads(primary, backup)
    assert result.status == "partial"
    assert not result.severe
    assert result.missing_dates == 1


def test_cross_check_selection_is_deterministic() -> None:
    first = deterministic_cross_check("600519", date(2026, 7, 14), ratio=0.1)
    assert first == deterministic_cross_check("600519", date(2026, 7, 14), ratio=0.1)
    assert deterministic_cross_check("600519", date(2026, 7, 14), ratio=1)


def test_provider_rejects_negative_adjusted_ohlc_before_persisting() -> None:
    pandas = __import__("pytest").importorskip("pandas")
    frame = pandas.DataFrame([{"开盘": -3.0, "最高": -3.0, "最低": -3.0, "收盘": -3.0}])
    with __import__("pytest").raises(RuntimeError, match="failed OHLC validation"):
        _validate_daily_frame(frame, symbol="000001", adjustment_mode="qfq")


def test_provider_accepts_positive_chinese_ohlc() -> None:
    pandas = __import__("pytest").importorskip("pandas")
    frame = pandas.DataFrame([{"开盘": 10.0, "最高": 10.5, "最低": 9.8, "收盘": 10.2}])
    _validate_daily_frame(frame, symbol="000001", adjustment_mode="raw")


def test_cninfo_title_classification_preserves_partial_event_evidence() -> None:
    module = _load_free_fetcher()
    row = module._classify_cninfo_notice({"公告标题": "关于股份回购方案的公告"}, source_date=date(2026, 7, 14))
    assert row["event_category"] == "repurchase"
    assert row["first_published_at"] == "2026-07-14"




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


def test_cn_equity_cohort_keeps_all_eligible_symbols_without_a_cap() -> None:
    bars = []
    for symbol, amount in (("600001", 1000), ("000001", 2000)):
        bars.extend(_bar(symbol, (index % 28) + 1, amount) for index in range(260))

    equity = build_cn_equity_core(
        bars,
        as_of=date(2024, 1, 31),
        lookback_sessions=20,
        minimum_history_sessions=20,
        minimum_coverage_ratio=0.05,
        minimum_median_amount=0,
        minimum_required_members=1,
    )

    assert [item.symbol for item in equity.members] == ["000001", "600001"]
    assert equity.selection_limit is None
    assert all(
        not reason.startswith("liquidity_rank_below_top_")
        for reason in equity.excluded.values()
    )


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


def test_retry_interrupts_hung_provider_request() -> None:
    started = time.monotonic()
    with __import__("pytest").raises(RuntimeError, match="TimeoutError"):
        call_with_retry(
            lambda: time.sleep(0.2),
            policy=ProviderPolicy(requests_per_second=100, max_attempts=1),
            limiter=SerialRateLimiter(100),
            timeout_seconds=0.02,
        )
    assert time.monotonic() - started < 0.15


def test_retry_hard_timeout_kills_an_unresponsive_request() -> None:
    started = time.monotonic()
    with __import__("pytest").raises(RuntimeError, match="TimeoutError"):
        call_with_retry(
            lambda: time.sleep(0.2),
            policy=ProviderPolicy(requests_per_second=100, max_attempts=1),
            limiter=SerialRateLimiter(100),
            timeout_seconds=0.02,
            hard_timeout=True,
        )
    assert time.monotonic() - started < 0.15


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
        def __init__(self, **_kwargs):
            pass

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
            config={"primary_requests_per_second": 100, "backup_requests_per_second": 100, "max_attempts": 1, "retry_backoff_seconds": [0], "hard_timeout": False},
    )
    assert output
    assert all(item["provider"] == "baostock" for item in output)
    assert all(item["provider_chain"] == ["akshare", "baostock"] for item in output)
    # The fallback's real source date is persisted for the next incremental
    # run; it must not be replaced by today's requested calendar date.
    cursor = module.CursorStore(tmp_path / "cursor.json").get("baostock", "600519", "raw")
    assert cursor is not None
    assert cursor.last_successful_trade_date == date(2026, 7, 14)


def test_incremental_cursor_reuses_latest_successful_fallback_provider(monkeypatch, tmp_path) -> None:
    module = _load_free_fetcher()
    starts = []

    class Primary:
        name = "akshare"

        def fetch(self, symbol, *, start, end, adjustment_mode):
            starts.append((adjustment_mode, start))
            return SimpleNamespace(payload=b'[{"date":"2026-07-16","close":10}]', row_count=1)

    class BackupUnavailable:
        def __enter__(self):
            raise RuntimeError("offline")

        def __exit__(self, *_args):
            return None

    class Service:
        def persist(self, **_kwargs):
            return SimpleNamespace(payload_hash="b" * 64)

    cursors = module.CursorStore(tmp_path / "cursor.json")
    for mode in ("raw", "qfq"):
        cursors.put(CollectionCursor(
            provider="baostock", symbol="600519", adjustment_mode=mode,
            last_successful_trade_date=date(2026, 7, 16),
            updated_at=datetime(2026, 7, 17, tzinfo=timezone.utc), payload_hash="a" * 64,
        ))
    monkeypatch.setattr(module, "AkshareDailyResearchProvider", Primary)
    monkeypatch.setattr(module, "BaostockDailyResearchProvider", BackupUnavailable)
    module._collect_cn_prices(
        Service(), ["600519"], full_history=False, lookback_days=730,
        cross_check_ratio=0, cursor_store=cursors,
            config={"primary_requests_per_second": 100, "backup_requests_per_second": 100, "max_attempts": 1, "retry_backoff_seconds": [0], "hard_timeout": False},
    )
    # Five business-day overlap from the Baostock cursor, rather than the
    # generic 30-day lookback caused by an absent AKShare cursor.
    assert starts == [("raw", date(2026, 7, 9)), ("qfq", date(2026, 7, 9))]


def test_payload_latest_trade_date_uses_actual_bar_not_requested_weekend() -> None:
    module = _load_free_fetcher()
    assert module._payload_latest_trade_date(
        b'[{"date":"2026-08-14","close":10}]', fallback=date(2026, 8, 16),
    ) == date(2026, 8, 14)


def test_cn_universe_discovery_does_not_silently_keep_demo_symbols(monkeypatch) -> None:
    module = _load_free_fetcher()

    class Primary:
        def enumerate_symbols(self):
            raise RuntimeError("public listing endpoint unavailable")

    class Backup:
        def enumerate_symbols(self, *, as_of):
            return ["600000", "000001"]

    class BackupContext:
        def __enter__(self):
            return Backup()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(module, "AkshareDailyResearchProvider", Primary)
    monkeypatch.setattr(module, "BaostockDailyResearchProvider", BackupContext)

    symbols = module._symbols_by_market(None, None, discover_cn=True)["cn"]

    assert {"600000", "000001"}.issubset(symbols)
    assert set(module.ETF_RESEARCH_SYMBOLS).issubset(symbols)
    assert "300750" not in symbols


def test_capped_cn_discovery_uses_liquid_buffer_before_fixed_etfs(monkeypatch) -> None:
    module = _load_free_fetcher()

    class Backup:
        def enumerate_liquid_candidates(self):
            return ["600000", "000001", "300001"]

    class BackupContext:
        def __enter__(self):
            return Backup()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(module, "BaostockDailyResearchProvider", BackupContext)

    symbols = module._symbols_by_market(None, 2, discover_cn=True)["cn"]

    assert symbols[:5] == list(module.ETF_RESEARCH_SYMBOLS)
    assert symbols[5:] == ["000001", "300001"]


def test_symbols_file_accepts_current_universe_record_list(tmp_path: Path) -> None:
    module = _load_free_fetcher()
    path = tmp_path / "security_master_current.json"
    path.write_text(json.dumps([
        {"code": "1", "code_name": "A"},
        {"code": "sh.600000", "code_name": "B"},
        {"code": "510300", "code_name": "ETF"},
    ]), encoding="utf-8")

    symbols = module._symbols_by_market(path, None, discover_cn=False)["cn"]

    assert symbols == ["000001", "600000", "510300"]


def test_coverage_shards_merge_without_promoting_research_tier(tmp_path: Path) -> None:
    from scripts.merge_free_research_coverage import merge

    symbols = tmp_path / "symbols.json"
    symbols.write_text(json.dumps([{"code": "000001"}, {"code": "600000"}]), encoding="utf-8")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    base = {
        "schema_version": "free-research-coverage-v1",
        "data_tier": "research_pit",
        "generated_at": "2026-08-24T00:00:00+00:00",
        "records": [],
    }
    first.write_text(json.dumps({**base, "records": [{
        "market": "cn", "dataset": "daily_bars_raw", "provider": "baostock",
        "status": "backfilled", "symbol": "000001", "rows_or_bytes": 1,
    }]}), encoding="utf-8")
    second.write_text(json.dumps({**base, "records": [{
        "market": "cn", "dataset": "daily_bars_raw", "provider": "baostock",
        "status": "backfilled", "symbol": "600000", "rows_or_bytes": 1,
    }]}), encoding="utf-8")

    output = tmp_path / "merged.json"
    merged = merge([first, second], symbols_file=symbols, output=output)

    cn = next(item for item in merged["market_coverage"] if item["market"] == "cn")
    assert cn["coverage_ratio"] == 1.0
    assert merged["data_tier"] == "research_pit"
    assert merged["formal_deployment_allowed"] is False


def test_parallel_baostock_helpers_normalize_universe_and_latest_date(tmp_path: Path) -> None:
    from scripts.fetch_cn_baostock_parallel import _latest_trade_date, _load_symbols

    path = tmp_path / "universe.json"
    path.write_text(json.dumps([{"code": "sh.1"}, {"code": "000002"}]), encoding="utf-8")

    assert _load_symbols(path) == ["000001", "000002"]
    assert _latest_trade_date(
        json.dumps([{"日期": "2026-08-20"}, {"日期": "2026-08-21"}]).encode(),
        date(2026, 1, 1),
    ) == date(2026, 8, 21)


def test_parallel_baostock_worker_uses_akshare_fallback(monkeypatch) -> None:
    import investment_research.training.cn_free_providers as providers
    from scripts import fetch_cn_baostock_parallel as module

    class BrokenBaostock:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            raise RuntimeError("baostock login unavailable")

        def __exit__(self, *_args):
            return None

    class Akshare:
        def fetch(self, symbol, *, start, end, adjustment_mode):
            payload = json.dumps([{
                "日期": end.isoformat(), "代码": symbol, "开盘": 10,
                "最高": 10.5, "最低": 9.5, "收盘": 10,
            }]).encode()
            return SimpleNamespace(payload=payload, row_count=1)

    monkeypatch.setattr(providers, "BaostockDailyResearchProvider", BrokenBaostock)
    monkeypatch.setattr(providers, "AkshareDailyResearchProvider", Akshare)
    records = module._worker_fetch(["000001"], date(2026, 8, 20), date(2026, 8, 21), 1)

    assert len(records) == 2
    assert all(item["status"] == "backfilled" for item in records)
    assert all(item["provider"] == "akshare" for item in records)
    assert all(item["provider_chain"] == ["baostock", "akshare"] for item in records)


def test_baostock_batch_adapter_reuses_session_and_reconnects_after_error(monkeypatch) -> None:
    module = _load_free_fetcher()
    opened: list[object] = []
    closed: list[object] = []

    class Provider:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            opened.append(self)
            return self

        def __exit__(self, *_args):
            closed.append(self)

        def fetch(self, symbol, **_kwargs):
            if symbol == "bad":
                raise RuntimeError("socket protocol failure")
            return symbol

    monkeypatch.setattr(module, "BaostockDailyResearchProvider", Provider)
    adapter = module._PerRequestBaostock()
    assert adapter.fetch("one") == "one"
    assert adapter.fetch("two") == "two"
    assert len(opened) == 1
    with __import__("pytest").raises(RuntimeError, match="socket protocol failure"):
        adapter.fetch("bad")
    assert len(closed) == 1
    assert adapter.fetch("three") == "three"
    assert len(opened) == 2
    adapter.close()
    assert len(closed) == 2


def test_full_history_ignores_existing_incremental_cursor(monkeypatch, tmp_path) -> None:
    module = _load_free_fetcher()
    starts = []

    class Primary:
        name = "akshare"

        def fetch(self, symbol, *, start, end, adjustment_mode):
            starts.append((adjustment_mode, start))
            return SimpleNamespace(payload=b'[{"date":"2026-07-14","close":10}]', row_count=1)

    class BackupUnavailable:
        def __enter__(self):
            raise RuntimeError("offline")

        def __exit__(self, *args):
            return None

    class Service:
        def persist(self, **kwargs):
            return SimpleNamespace(payload_hash="b" * 64)

    cursors = module.CursorStore(tmp_path / "cursor.json")
    for mode in ("raw", "qfq"):
        cursors.put(CollectionCursor(
            provider="akshare", symbol="600519", adjustment_mode=mode,
            last_successful_trade_date=date(2026, 7, 13),
            updated_at=datetime(2026, 7, 14, tzinfo=timezone.utc), payload_hash="a" * 64,
        ))
    monkeypatch.setattr(module, "AkshareDailyResearchProvider", Primary)
    monkeypatch.setattr(module, "BaostockDailyResearchProvider", BackupUnavailable)
    module._collect_cn_prices(
        Service(), ["600519"], full_history=True, lookback_days=3,
        cross_check_ratio=0, cursor_store=cursors,
            config={"primary_requests_per_second": 100, "backup_requests_per_second": 100, "max_attempts": 1, "retry_backoff_seconds": [0], "hard_timeout": False},
    )
    assert starts == [("raw", None), ("qfq", None)]


def test_cn_generic_compatibility_path_is_fail_closed() -> None:
    module = _load_free_fetcher()
    result = module._collect_price(None, "cn", "600519", {"markets": {"cn": {"prices": "akshare"}}})
    assert result["status"] == "fetch_failed"
    assert result["provider_chain"] == ["akshare", "baostock"]
