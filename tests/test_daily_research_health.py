from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_daily_research_health.py"
    spec = importlib.util.spec_from_file_location("daily_research_health_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _worker_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_research_worker.py"
    spec = importlib.util.spec_from_file_location("research_worker_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coverage() -> dict:
    return {
        "generated_at": "2026-08-20T08:00:00+00:00",
        "market_coverage": [{
            "market": "cn", "coverage_ratio": 1.0, "event_coverage_status": "events_present",
            "records": [
                {"dataset": "daily_bars_raw", "symbol": "600519"},
                {"dataset": "daily_bars_qfq", "symbol": "600519"},
            ],
        }],
    }


def test_daily_health_is_healthy_when_both_price_modes_are_current() -> None:
    module = _module()
    cursors = {
        "akshare:600519:raw": {"provider": "akshare", "symbol": "600519", "adjustment_mode": "raw", "last_successful_trade_date": "2026-08-20"},
        "akshare:600519:qfq": {"provider": "akshare", "symbol": "600519", "adjustment_mode": "qfq", "last_successful_trade_date": "2026-08-20"},
    }
    result = module.build_health(
        _coverage(), cursors, as_of=date(2026, 8, 20), maximum_age_trading_days=1,
        worker_heartbeat={"pid": 123, "observed_at": datetime.now(timezone.utc).isoformat()},
    )
    assert result["status"] == "healthy"
    assert result["fresh_price_cursor_count"] == 2


def test_daily_health_flags_non_trading_cursor_and_missing_mode() -> None:
    module = _module()
    cursors = {
        "baostock:600519:raw": {"provider": "baostock", "symbol": "600519", "adjustment_mode": "raw", "last_successful_trade_date": "2026-08-16"},
    }
    result = module.build_health(
        _coverage(), cursors, as_of=date(2026, 8, 20), maximum_age_trading_days=1,
        worker_heartbeat={"pid": 123, "observed_at": datetime.now(timezone.utc).isoformat()},
    )
    assert result["status"] == "degraded"
    assert "cursor_non_trading_date" in result["reasons"]
    assert result["missing_price_cursors"] == ["600519:qfq"]


def test_daily_health_flags_missing_worker_heartbeat() -> None:
    module = _module()
    cursors = {
        "akshare:600519:raw": {"provider": "akshare", "symbol": "600519", "adjustment_mode": "raw", "last_successful_trade_date": "2026-08-20"},
        "akshare:600519:qfq": {"provider": "akshare", "symbol": "600519", "adjustment_mode": "qfq", "last_successful_trade_date": "2026-08-20"},
    }
    result = module.build_health(_coverage(), cursors, as_of=date(2026, 8, 20), maximum_age_trading_days=1)
    assert result["status"] == "degraded"
    assert "worker_heartbeat_missing" in result["reasons"]


def test_daily_health_keeps_rolling_event_coverage_as_a_warning() -> None:
    module = _module()
    coverage = _coverage()
    coverage["market_coverage"][0]["event_coverage_status"] = "partial"
    cursors = {
        "akshare:600519:raw": {"provider": "akshare", "symbol": "600519", "adjustment_mode": "raw", "last_successful_trade_date": "2026-08-20"},
        "akshare:600519:qfq": {"provider": "akshare", "symbol": "600519", "adjustment_mode": "qfq", "last_successful_trade_date": "2026-08-20"},
    }
    result = module.build_health(
        coverage, cursors, as_of=date(2026, 8, 20), maximum_age_trading_days=1,
        worker_heartbeat={"pid": 123, "observed_at": datetime.now(timezone.utc).isoformat()},
    )
    assert result["status"] == "healthy"
    assert result["warnings"] == ["event_coverage:partial"]


def test_worker_writes_atomic_heartbeat(tmp_path) -> None:
    worker = _worker_module()
    target = tmp_path / "worker.json"
    worker._write_heartbeat(target, started_at=datetime(2026, 8, 20, tzinfo=timezone.utc))
    payload = __import__("json").loads(target.read_text())
    assert payload["role"] == "research_scheduler"
    assert isinstance(payload["pid"], int)
