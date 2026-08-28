from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.paper_game import PaperGameService

CN = ZoneInfo("Asia/Shanghai")


def _now(day: int = 20, hour: int = 10) -> datetime:
    return datetime(2026, 8, day, hour, 0, tzinfo=CN)


def _quote(uow: SQLiteUnitOfWork, symbol: str, price: float, captured_at: datetime) -> None:
    uow.connection.execute(
        "INSERT INTO intraday_quote_spot (id,symbol,market,name,latest_price,change_pct,volume,amount,source,captured_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), symbol, "sh", "真实名称", price, 1.25, 1000, 10000, "test", captured_at.astimezone(timezone.utc).isoformat()),
    )
    uow.connection.commit()


def _activate(uow: SQLiteUnitOfWork, token: str) -> None:
    uow.connection.execute("UPDATE paper_game_accounts SET setup_status='active' WHERE visitor_token=?", (token,))
    uow.connection.commit()


def test_account_buy_idempotency_fee_and_t_plus_one(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "paper.db")
    now = _now()
    _quote(uow, "600519", 100.0, now)
    service = PaperGameService(uow, now=now)
    token, account = service.create_or_restore_account(None, "OWL")
    _activate(uow, token)
    assert account["cash"] == 100_000

    first = service.place_order(token, symbol="600519", side="buy", quantity=100, amount=None, idempotency_key="same-request-0001")
    second = service.place_order(token, symbol="600519", side="buy", quantity=100, amount=None, idempotency_key="same-request-0001")
    assert first["id"] == second["id"]
    assert first["status"] == "filled"
    bought = service.account(token)
    assert bought["positions"][0]["quantity"] == 100
    assert bought["positions"][0]["available_quantity"] == 0
    assert bought["fees"] >= 5

    sell = service.place_order(token, symbol="600519", side="sell", quantity=100, amount=None, idempotency_key="same-day-sell-01")
    assert sell["status"] == "rejected"
    assert "下一交易日" in sell["rejection_reason"]

    next_day = _now(day=21)
    _quote(uow, "600519", 102.0, next_day)
    next_service = PaperGameService(uow, now=next_day)
    sold = next_service.place_order(token, symbol="600519", side="sell", quantity=100, amount=None, idempotency_key="next-day-sell-1")
    assert sold["status"] == "filled"
    final = next_service.account(token)
    assert final["positions"] == []
    assert final["realized_pnl"] > 0
    uow.close()


def test_stale_quote_is_rejected_and_off_hours_order_can_cancel(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "paper.db")
    now = _now()
    _quote(uow, "600519", 100.0, now - timedelta(minutes=20))
    service = PaperGameService(uow, now=now)
    token, _ = service.create_or_restore_account(None)
    _activate(uow, token)
    stale = service.place_order(token, symbol="600519", side="buy", quantity=100, amount=None, idempotency_key="stale-order-0001")
    assert stale["status"] == "rejected"
    assert "12分钟" in stale["rejection_reason"]

    closed = _now(hour=16)
    closed_service = PaperGameService(uow, now=closed)
    pending = closed_service.place_order(token, symbol="600519", side="buy", quantity=100, amount=None, idempotency_key="closed-order-001")
    assert pending["status"] == "pending"
    assert closed_service.cancel(token, pending["id"])["status"] == "cancelled"
    uow.close()


def test_daily_pool_has_real_named_stocks_funds_and_gold_and_is_frozen(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "paper.db")
    service = PaperGameService(uow, now=_now())
    first = service.today()
    second = service.today()
    assert [item["symbol"] for item in first["assets"]] == [item["symbol"] for item in second["assets"]]
    assert {item["category"] for item in first["assets"]} == {"股票", "基金", "黄金"}
    assert all(item["display_name"] == item["alias"] for item in first["assets"])
    uow.close()


def test_onboarding_uses_frozen_close_and_unlocks_todays_orders(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "paper.db")
    now = _now()
    uow.connection.execute("INSERT INTO assets (id,status,schema_version,entity_version,data_mode,source_type,observed_at,payload) VALUES (?,?,?,?,?,?,?,?)", ("asset-1", "active", "1", 1, "real", "real", now.isoformat(), '{"ticker":"600519","name":"贵州茅台","asset_type":"equity"}'))
    uow.connection.execute("INSERT INTO paper_game_close_snapshots (id,trade_date,symbol,display_name,close_cents,source,captured_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), "2026-08-19", "600519", "贵州茅台", 10000, "test", now.isoformat()))
    uow.connection.commit()
    service = PaperGameService(uow, now=now)
    token, account = service.create_or_restore_account(None)
    assert account["setup_status"] == "setup_required"
    setup = service.onboarding(token)
    assert setup["ready"] and setup["assets"][0]["display_name"] == "贵州茅台"
    activated = service.confirm_onboarding(token, [{"symbol": "600519", "quantity": 100}], "setup-test-0001")
    assert activated["setup_status"] == "active"
    assert activated["positions"][0]["available_quantity"] == 100
    _quote(uow, "600519", 101.0, now)
    sold = service.place_order(token, symbol="600519", side="sell", quantity=100, amount=None, idempotency_key="sell-after-setup-1")
    assert sold["status"] == "filled"
    uow.close()


def test_worker_automation_fills_queued_order_and_runs_two_bot_sessions(tmp_path: Path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "paper.db")
    closed = _now(hour=16)
    _quote(uow, "600519", 100.0, closed)
    service = PaperGameService(uow, now=closed)
    token, _ = service.create_or_restore_account(None)
    _activate(uow, token)
    pending = service.place_order(token, symbol="600519", side="buy", quantity=100, amount=None, idempotency_key="automated-open-1")
    assert pending["status"] == "pending"

    next_day = _now(day=21, hour=14).replace(minute=35)
    _quote(uow, "600519", 101.0, next_day)
    automation = PaperGameService(uow, now=next_day).run_automation()
    assert automation["queued_orders_checked"] == 1
    assert PaperGameService(uow, now=next_day).account(token)["orders"][0]["status"] == "filled"
    sessions = uow.connection.execute("SELECT session,COUNT(*) FROM paper_game_bot_snapshots GROUP BY session ORDER BY session").fetchall()
    assert [(row[0], row[1]) for row in sessions] == [("10:00", 12), ("14:30", 12)]
    uow.close()
