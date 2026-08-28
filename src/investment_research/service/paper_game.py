"""Persistent entertainment-only paper trading on delayed public quotes."""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_research.integrations.xystock.quote_fetcher import is_cn_trading_session

CN = ZoneInfo("Asia/Shanghai")
INITIAL_CASH_CENTS = 10_000_000
MAX_QUOTE_AGE_SECONDS = 12 * 60
COMMISSION_RATE = Decimal("0.0003")
MIN_COMMISSION_CENTS = 500
SELL_TAX_RATE = Decimal("0.0005")
SLIPPAGE_RATE = Decimal("0.0005")
ETF_SYMBOLS = {"510050", "510300", "510500", "159915", "512100"}
GOLD_SYMBOL = "518880"

PERSONAS = [
    ("LION", "草原狮王", "🦁"), ("OWL", "财报猫头鹰", "🦉"),
    ("TURTLE", "定投海龟", "🐢"), ("FOX", "反转狐狸", "🦊"),
    ("BEE", "分散蜜蜂", "🐝"), ("CHEETAH", "动量猎豹", "🐆"),
    ("BEAVER", "现金流河狸", "🦫"), ("DOLPHIN", "消息海豚", "🐬"),
    ("CAT", "估值橘猫", "🐈"), ("PENGUIN", "共识企鹅", "🐧"),
    ("CAMEL", "周期骆驼", "🐫"), ("RACCOON", "机会浣熊", "🦝"),
]

SECTOR_OVERRIDES = {
    "科技": ["300750", "000725", "002415"],
    "消费": ["600519", "000858", "000333"],
    "医疗": ["600276", "300015"],
    "金融": ["600036", "000001", "600030"],
    "能源": ["601857", "600028", "601088"],
    "制造": ["600031", "002594", "601012"],
}

ETF_NAMES = {
    "510050": "上证50ETF", "510300": "沪深300ETF", "510500": "中证500ETF",
    "159915": "创业板ETF", "512100": "中证1000ETF", "518880": "黄金ETF",
}
_INDUSTRIES: dict[str, str] | None = None


def _iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _cn_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=CN) if value.tzinfo is None else value.astimezone(CN)


def _money(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


def _cents(value: float) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _fee(value_cents: int, side: str) -> int:
    commission = max(MIN_COMMISSION_CENTS, int((Decimal(value_cents) * COMMISSION_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    tax = int((Decimal(value_cents) * SELL_TAX_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if side == "sell" else 0
    return commission + tax


class PaperGameError(ValueError):
    pass


class PaperGameService:
    def __init__(self, uow, *, now: datetime | None = None) -> None:
        self.uow = uow
        self.conn = uow.connection
        self.now = _cn_now(now)

    def ensure_day(self) -> str:
        trade_date = self.now.date().isoformat()
        row = self.conn.execute("SELECT id FROM paper_game_days WHERE trade_date=?", (trade_date,)).fetchone()
        if row:
            return row[0]
        day_id = str(uuid.uuid4())
        bulletin = self._build_bulletin()
        self.conn.execute(
            "INSERT INTO paper_game_days (id,trade_date,status,bulletin_json,created_at) VALUES (?,?,?,?,?)",
            (day_id, trade_date, "active", json.dumps(bulletin, ensure_ascii=False), _iso(self.now)),
        )
        for symbol, display_name, sector, category in self._market_universe():
            category = "黄金" if symbol == GOLD_SYMBOL else "基金" if symbol in ETF_SYMBOLS else "股票"
            self.conn.execute(
                "INSERT INTO paper_game_assets (id,day_id,symbol,alias,category,sector,lot_size,t_plus_one) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), day_id, symbol, display_name, category, sector, 100, category == "股票"),
            )
        self.conn.commit()
        return day_id

    def run_automation(self) -> dict:
        """Advance queued orders and the two daily bot evaluation sessions."""
        accounts = self.conn.execute("SELECT id,visitor_token FROM paper_game_accounts").fetchall()
        processed = 0
        for account_id, visitor_token in accounts:
            self._settle_positions(account_id)
            before = self.conn.execute("SELECT COUNT(*) FROM paper_game_orders WHERE account_id=? AND status IN ('pending','open')", (account_id,)).fetchone()[0]
            self._process_pending(account_id)
            if before:
                self.account(visitor_token)
            processed += before
        self._ensure_bot_snapshots()
        return {"accounts": len(accounts), "queued_orders_checked": processed}

    def create_or_restore_account(self, visitor_token: str | None, persona_code: str | None = None, user_id: str | None = None) -> tuple[str, dict]:
        token = visitor_token or secrets.token_urlsafe(32)
        row = self.conn.execute("SELECT id FROM paper_game_accounts WHERE visitor_token=?", (token,)).fetchone()
        if not row:
            account_id = str(uuid.uuid4())
            nickname = f"模拟选手-{token[:6]}"
            self.conn.execute(
                "INSERT INTO paper_game_accounts (id,visitor_token,user_id,persona_code,nickname,initial_cash_cents,cash_cents,realized_pnl_cents,fees_cents,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, token, user_id, persona_code, nickname, INITIAL_CASH_CENTS, INITIAL_CASH_CENTS, 0, 0, 1, _iso(self.now), _iso(self.now)),
            )
            self.conn.commit()
        else:
            account_id = row[0]
            if persona_code or user_id:
                self.conn.execute("UPDATE paper_game_accounts SET persona_code=COALESCE(?,persona_code),user_id=COALESCE(?,user_id),updated_at=? WHERE id=?", (persona_code, user_id, _iso(self.now), account_id))
                self.conn.commit()
        return token, self.account(token)

    def onboarding(self, visitor_token: str) -> dict:
        account = self._account_row(visitor_token)
        status, setup_date, confirmed_at = account[10:13]
        snapshot_date = self._latest_close_date()
        symbols = [item[0] for item in self._equity_universe()]
        placeholders = ",".join("?" for _ in symbols)
        rows = [] if snapshot_date is None else self.conn.execute(
            f"SELECT symbol,display_name,close_cents,source,captured_at FROM paper_game_close_snapshots WHERE trade_date=? AND symbol IN ({placeholders}) ORDER BY display_name", (snapshot_date, *symbols)
        ).fetchall()
        return {
            "setup_status": status, "setup_trade_date": setup_date, "setup_confirmed_at": confirmed_at,
            "snapshot_date": snapshot_date, "ready": len(rows) >= len(self._equity_universe()),
            "reason": None if rows else "正在准备最近一个交易日的真实收盘数据",
            "assets": [{"symbol": r[0], "display_name": r[1], "close": _money(r[2]), "sector": self._sector(r[0]), "source": r[3], "captured_at": r[4], "lot_size": 100} for r in rows],
            "initial_cash": _money(INITIAL_CASH_CENTS),
        }

    def confirm_onboarding(self, visitor_token: str, positions: list[dict], idempotency_key: str) -> dict:
        account = self._account_row(visitor_token)
        if account[10] == "active":
            return self.account(visitor_token)
        onboarding = self.onboarding(visitor_token)
        if not onboarding["ready"] or not onboarding["snapshot_date"]:
            raise PaperGameError("昨日真实收盘数据尚未准备完成，暂不能建仓")
        requested: dict[str, int] = {}
        for item in positions:
            symbol, quantity = str(item.get("symbol", "")), int(item.get("quantity", 0))
            if symbol not in {asset[0] for asset in self._equity_universe()} or quantity <= 0 or quantity % 100:
                raise PaperGameError("初始持仓只能选择股票，且数量必须为100股的整数倍")
            requested[symbol] = requested.get(symbol, 0) + quantity
        if not requested:
            raise PaperGameError("请至少选择一只股票建立初始持仓")
        snapshot_rows = self.conn.execute(
            "SELECT symbol,display_name,close_cents FROM paper_game_close_snapshots WHERE trade_date=?", (onboarding["snapshot_date"],)
        ).fetchall()
        prices = {row[0]: (row[1], row[2]) for row in snapshot_rows}
        if any(symbol not in prices for symbol in requested):
            raise PaperGameError("部分股票缺少昨日真实收盘价，请刷新后重试")
        values = {symbol: prices[symbol][1] * quantity for symbol, quantity in requested.items()}
        fees = {symbol: _fee(value, "buy") for symbol, value in values.items()}
        total = sum(values.values()) + sum(fees.values())
        if total > INITIAL_CASH_CENTS:
            raise PaperGameError("初始持仓加费用超过10万元虚拟资金")
        day_id = self.ensure_day()
        now = _iso(self.now)
        if type(self.conn).__module__ == "sqlite3" and not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
        current = self._account_row(visitor_token)
        if current[10] == "active":
            self.conn.commit()
            return self.account(visitor_token)
        for symbol, quantity in requested.items():
            name, price = prices[symbol]
            order_id = str(uuid.uuid4())
            self.conn.execute("INSERT INTO paper_game_positions (account_id,symbol,quantity,available_quantity,average_cost_cents,last_buy_date,updated_at) VALUES (?,?,?,?,?,?,?)", (current[0], symbol, quantity, quantity, int(round((values[symbol] + fees[symbol]) / quantity)), onboarding["snapshot_date"], now))
            self.conn.execute("INSERT INTO paper_game_orders (id,account_id,day_id,symbol,side,quantity,status,idempotency_key,submitted_at,filled_at,fill_price_cents,fee_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (order_id, current[0], day_id, symbol, "buy", quantity, "filled", f"setup:{idempotency_key}:{symbol}", now, now, price, fees[symbol]))
            self.conn.execute("INSERT INTO paper_game_trades (id,order_id,account_id,symbol,side,quantity,price_cents,fee_cents,executed_at) VALUES (?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), order_id, current[0], symbol, "buy", quantity, price, fees[symbol], now))
        cash = INITIAL_CASH_CENTS - total
        self.conn.execute("UPDATE paper_game_accounts SET cash_cents=?,fees_cents=?,setup_status='active',setup_trade_date=?,setup_confirmed_at=?,version=version+1,updated_at=? WHERE id=?", (cash, sum(fees.values()), onboarding["snapshot_date"], now, now, current[0]))
        self._record_equity(current[0], cash, sum(values.values()), cash + sum(values.values()))
        self.conn.commit()
        return self.account(visitor_token)

    def today(self) -> dict:
        day_id = self.ensure_day()
        day = self.conn.execute("SELECT trade_date,status,bulletin_json FROM paper_game_days WHERE id=?", (day_id,)).fetchone()
        assets = self.conn.execute("SELECT symbol,alias,category,sector,lot_size,t_plus_one FROM paper_game_assets WHERE day_id=? ORDER BY category,sector,alias", (day_id,)).fetchall()
        quotes = self._quotes([row[0] for row in assets])
        return {
            "trade_date": day[0], "status": day[1], "market_open": is_cn_trading_session(self.now.replace(tzinfo=None)),
            "quote_policy": "约5分钟延迟行情；报价超过12分钟时禁止成交",
            "bulletins": json.loads(day[2]),
            "assets": [self._asset_view(row, quotes.get(row[0])) for row in assets],
            "disclaimer": "虚拟资金、娱乐竞赛，仅作学习体验，不构成投资建议。",
        }

    def account(self, visitor_token: str) -> dict:
        account = self._account_row(visitor_token)
        self._settle_positions(account[0])
        self._process_pending(account[0])
        account = self._account_row(visitor_token)
        positions = self.conn.execute("SELECT symbol,quantity,available_quantity,average_cost_cents,last_buy_date FROM paper_game_positions WHERE account_id=? AND quantity>0 ORDER BY symbol", (account[0],)).fetchall()
        quotes = self._quotes([row[0] for row in positions])
        position_views = []
        market_value = 0
        unrealized = 0
        for row in positions:
            quote = quotes.get(row[0])
            price_cents = _cents(quote["latest_price"]) if quote and quote.get("latest_price") else row[3]
            value = price_cents * row[1]
            market_value += value
            pnl = (price_cents - row[3]) * row[1]
            unrealized += pnl
            position_views.append({
                "symbol": row[0], "alias": self._alias(row[0]), "quantity": row[1], "available_quantity": row[2],
                "average_cost": _money(row[3]), "latest_price": _money(price_cents), "market_value": _money(value),
                "unrealized_pnl": _money(pnl), "last_buy_date": row[4],
            })
        total = account[6] + market_value
        self._record_equity(account[0], account[6], market_value, total)
        orders = self.conn.execute("SELECT id,symbol,side,quantity,status,rejection_reason,submitted_at,filled_at,fill_price_cents,fee_cents FROM paper_game_orders WHERE account_id=? ORDER BY submitted_at DESC LIMIT 100", (account[0],)).fetchall()
        trades = self.conn.execute("SELECT id,symbol,side,quantity,price_cents,fee_cents,executed_at FROM paper_game_trades WHERE account_id=? ORDER BY executed_at DESC LIMIT 100", (account[0],)).fetchall()
        return {
            "id": account[0], "persona_code": account[3], "nickname": account[4], "initial_cash": _money(account[5]), "setup_status": account[10], "setup_trade_date": account[11], "setup_confirmed_at": account[12],
            "cash": _money(account[6]), "market_value": _money(market_value), "total_equity": _money(total),
            "total_return_pct": round((total / account[5] - 1) * 100, 4), "realized_pnl": _money(account[7]),
            "unrealized_pnl": _money(unrealized), "fees": _money(account[8]), "version": account[9],
            "positions": position_views,
            "orders": [{"id": r[0], "symbol": r[1], "alias": self._alias(r[1]), "side": r[2], "quantity": r[3], "status": r[4], "rejection_reason": r[5], "submitted_at": r[6], "filled_at": r[7], "fill_price": _money(r[8]), "fee": _money(r[9])} for r in orders],
            "trades": [{"id": r[0], "symbol": r[1], "alias": self._alias(r[1]), "side": r[2], "quantity": r[3], "price": _money(r[4]), "fee": _money(r[5]), "executed_at": r[6]} for r in trades],
        }

    def place_order(self, visitor_token: str, *, symbol: str, side: str, quantity: int | None, amount: float | None, idempotency_key: str) -> dict:
        account = self._account_row(visitor_token)
        if account[10] != "active":
            raise PaperGameError("请先用昨日真实收盘价完成初始建仓")
        self._settle_positions(account[0])
        day_id = self.ensure_day()
        asset = self.conn.execute("SELECT lot_size FROM paper_game_assets WHERE day_id=? AND symbol=?", (day_id, symbol)).fetchone()
        if not asset:
            raise PaperGameError("该标的不在今日比赛池中")
        if side not in {"buy", "sell"}:
            raise PaperGameError("交易方向必须是 buy 或 sell")
        existing = self.conn.execute("SELECT id FROM paper_game_orders WHERE account_id=? AND idempotency_key=?", (account[0], idempotency_key)).fetchone()
        if existing:
            return self._order(existing[0])
        quote = self._quotes([symbol]).get(symbol)
        if quantity is None and amount is not None and quote and quote.get("latest_price"):
            quantity = math.floor(amount / quote["latest_price"] / asset[0]) * asset[0]
        if not quantity or quantity <= 0 or quantity % asset[0] != 0:
            raise PaperGameError(f"委托数量必须是{asset[0]}的正整数倍")
        order_id = str(uuid.uuid4())
        status = "open" if is_cn_trading_session(self.now.replace(tzinfo=None)) else "pending"
        self.conn.execute(
            "INSERT INTO paper_game_orders (id,account_id,day_id,symbol,side,quantity,status,idempotency_key,rejection_reason,submitted_at,filled_at,fill_price_cents,fee_cents) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, account[0], day_id, symbol, side, quantity, status, idempotency_key, None, _iso(self.now), None, None, None),
        )
        self.conn.commit()
        if status == "open":
            self._fill(order_id)
        return self._order(order_id)

    def cancel(self, visitor_token: str, order_id: str) -> dict:
        account = self._account_row(visitor_token)
        row = self.conn.execute("SELECT status FROM paper_game_orders WHERE id=? AND account_id=?", (order_id, account[0])).fetchone()
        if not row:
            raise PaperGameError("未找到该委托")
        if row[0] not in {"pending", "open"}:
            raise PaperGameError("只有未成交委托可以撤销")
        self.conn.execute("UPDATE paper_game_orders SET status='cancelled' WHERE id=?", (order_id,))
        self.conn.commit()
        return self._order(order_id)

    def leaderboard(self, visitor_token: str) -> dict:
        user = self.account(visitor_token)
        self._ensure_bot_snapshots()
        latest_session = self.conn.execute("SELECT session FROM paper_game_bot_snapshots WHERE trade_date=? ORDER BY captured_at DESC LIMIT 1", (self.now.date().isoformat(),)).fetchone()
        bot_values = {}
        if latest_session:
            bot_values = {row[0]: row for row in self.conn.execute("SELECT persona_code,return_pct,max_drawdown_pct,risk_adjusted_score,strategy_source FROM paper_game_bot_snapshots WHERE trade_date=? AND session=?", (self.now.date().isoformat(), latest_session[0])).fetchall()}
        seed = int(hashlib.sha256(self.now.date().isoformat().encode()).hexdigest()[:8], 16)
        rows = []
        for index, (code, name, emoji) in enumerate(PERSONAS):
            stored = bot_values.get(code)
            wave = stored[1] if stored else math.sin((seed % 997 + index * 17) / 37) * .2
            drawdown = stored[2] if stored else -abs(wave) * .7
            score = stored[3] if stored else wave - abs(drawdown) * .35
            source = stored[4] if stored else "开盘前人格规则基线（未使用模型买卖指令）"
            rows.append({"code": code, "name": name, "emoji": emoji, "return_pct": round(wave, 3), "max_drawdown_pct": round(drawdown, 3), "risk_adjusted_score": round(score, 3), "is_user": False, "strategy_source": source})
        rows.append({"code": "YOU", "name": user["nickname"], "emoji": "🙂", "return_pct": user["total_return_pct"], "max_drawdown_pct": self._max_drawdown(user["id"]), "risk_adjusted_score": round(user["total_return_pct"] - abs(self._max_drawdown(user["id"])) * .35, 3), "is_user": True, "strategy_source": "你的模拟交易"})
        rows.sort(key=lambda item: item["risk_adjusted_score"], reverse=True)
        for rank, item in enumerate(rows, 1): item["rank"] = rank
        return {"metric": "风险调整得分 = 收益率 - 0.35 × |最大回撤|", "entries": rows}

    def _ensure_bot_snapshots(self) -> None:
        minute = self.now.hour * 60 + self.now.minute
        sessions = []
        if minute >= 10 * 60: sessions.append("10:00")
        if minute >= 14 * 60 + 30: sessions.append("14:30")
        if not sessions: return
        day_id = self.ensure_day()
        symbols = [row[0] for row in self.conn.execute("SELECT symbol FROM paper_game_assets WHERE day_id=?", (day_id,)).fetchall()]
        changes = [item.get("change_pct") for item in self._quotes(symbols).values() if item.get("change_pct") is not None]
        market_move = sum(changes) / len(changes) if changes else 0.0
        trade_date = self.now.date().isoformat()
        for session in sessions:
            for index, (code, _name, _emoji) in enumerate(PERSONAS):
                exists = self.conn.execute("SELECT 1 FROM paper_game_bot_snapshots WHERE trade_date=? AND session=? AND persona_code=?", (trade_date, session, code)).fetchone()
                if exists: continue
                style = .45 + (index % 5) * .12
                contrarian = -1 if code in {"FOX", "CAT"} else 1
                diversification = .55 if code in {"BEE", "TURTLE", "BEAVER"} else .85
                value = market_move * style * contrarian * diversification
                value += math.sin((index + 1) * 1.71 + (0 if session == "10:00" else .8)) * .12
                drawdown = -abs(value) * (0.45 + (index % 4) * .09)
                score = value - abs(drawdown) * .35
                self.conn.execute("INSERT INTO paper_game_bot_snapshots (id,trade_date,session,persona_code,return_pct,max_drawdown_pct,risk_adjusted_score,strategy_source,captured_at) VALUES (?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), trade_date, session, code, value, drawdown, score, "人格规则策略；长期模型仅作可解释权重，未生成买卖指令", _iso(self.now)))
        self.conn.commit()

    def equity_curve(self, visitor_token: str) -> dict:
        account = self._account_row(visitor_token)
        rows = self.conn.execute("SELECT captured_at,cash_cents,market_value_cents,total_equity_cents FROM paper_game_equity WHERE account_id=? ORDER BY captured_at", (account[0],)).fetchall()
        return {"points": [{"captured_at": r[0], "cash": _money(r[1]), "market_value": _money(r[2]), "total_equity": _money(r[3])} for r in rows]}

    def _fill(self, order_id: str) -> None:
        order = self.conn.execute("SELECT id,account_id,symbol,side,quantity,status FROM paper_game_orders WHERE id=?", (order_id,)).fetchone()
        if not order or order[5] not in {"open", "pending"}: return
        quote = self._quotes([order[2]]).get(order[2])
        reason = self._quote_rejection(quote)
        if reason:
            self.conn.execute("UPDATE paper_game_orders SET status='rejected',rejection_reason=? WHERE id=?", (reason, order_id)); self.conn.commit(); return
        raw_cents = _cents(quote["latest_price"])
        price_cents = int((Decimal(raw_cents) * (Decimal("1") + SLIPPAGE_RATE if order[3] == "buy" else Decimal("1") - SLIPPAGE_RATE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        value = price_cents * order[4]
        fee = _fee(value, order[3])
        # Serialize balance/position checks and writes on SQLite. This prevents
        # two simultaneous browser requests from both spending the same cash.
        if type(self.conn).__module__ == "sqlite3" and not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
        account = self.conn.execute("SELECT cash_cents,version FROM paper_game_accounts WHERE id=?", (order[1],)).fetchone()
        position = self.conn.execute("SELECT quantity,available_quantity,average_cost_cents FROM paper_game_positions WHERE account_id=? AND symbol=?", (order[1], order[2])).fetchone()
        if order[3] == "buy" and account[0] < value + fee:
            return self._reject(order_id, "可用现金不足，无法完成该笔模拟买入")
        if order[3] == "sell" and (not position or position[1] < order[4]):
            return self._reject(order_id, "可卖数量不足；股票当日买入部分需下一交易日才能卖出")
        now = _iso(self.now)
        if order[3] == "buy":
            old_qty, old_available, old_cost = position if position else (0, 0, 0)
            new_qty = old_qty + order[4]
            avg = int(round((old_qty * old_cost + value + fee) / new_qty))
            self.conn.execute("INSERT OR REPLACE INTO paper_game_positions (account_id,symbol,quantity,available_quantity,average_cost_cents,last_buy_date,updated_at) VALUES (?,?,?,?,?,?,?)", (order[1], order[2], new_qty, old_available, avg, self.now.date().isoformat(), now))
            cash_delta, realized = -(value + fee), 0
        else:
            remaining = position[0] - order[4]
            realized = (price_cents - position[2]) * order[4] - fee
            self.conn.execute("UPDATE paper_game_positions SET quantity=?,available_quantity=?,updated_at=? WHERE account_id=? AND symbol=?", (remaining, position[1] - order[4], now, order[1], order[2]))
            cash_delta = value - fee
        self.conn.execute("UPDATE paper_game_accounts SET cash_cents=cash_cents+?,realized_pnl_cents=realized_pnl_cents+?,fees_cents=fees_cents+?,version=version+1,updated_at=? WHERE id=?", (cash_delta, realized, fee, now, order[1]))
        self.conn.execute("UPDATE paper_game_orders SET status='filled',filled_at=?,fill_price_cents=?,fee_cents=? WHERE id=?", (now, price_cents, fee, order_id))
        self.conn.execute("INSERT INTO paper_game_trades (id,order_id,account_id,symbol,side,quantity,price_cents,fee_cents,executed_at) VALUES (?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), order_id, order[1], order[2], order[3], order[4], price_cents, fee, now))
        self.conn.commit()

    def _reject(self, order_id: str, reason: str) -> None:
        self.conn.execute("UPDATE paper_game_orders SET status='rejected',rejection_reason=? WHERE id=?", (reason, order_id)); self.conn.commit()

    def _process_pending(self, account_id: str) -> None:
        if not is_cn_trading_session(self.now.replace(tzinfo=None)): return
        rows = self.conn.execute("SELECT id FROM paper_game_orders WHERE account_id=? AND status IN ('pending','open') ORDER BY submitted_at", (account_id,)).fetchall()
        for row in rows: self._fill(row[0])

    def _settle_positions(self, account_id: str) -> None:
        today = self.now.date().isoformat()
        self.conn.execute("UPDATE paper_game_positions SET available_quantity=quantity,updated_at=? WHERE account_id=? AND last_buy_date<?", (_iso(self.now), account_id, today)); self.conn.commit()

    def _quotes(self, symbols: list[str]) -> dict[str, dict]:
        if not symbols: return {}
        placeholders = ",".join("?" for _ in symbols)
        rows = self.conn.execute(f"SELECT q.symbol,q.name,q.latest_price,q.change_pct,q.volume,q.amount,q.captured_at FROM intraday_quote_spot q JOIN (SELECT symbol,MAX(captured_at) captured_at FROM intraday_quote_spot WHERE symbol IN ({placeholders}) GROUP BY symbol) latest ON latest.symbol=q.symbol AND latest.captured_at=q.captured_at", tuple(symbols)).fetchall()
        return {r[0]: {"symbol": r[0], "name": r[1], "latest_price": r[2], "change_pct": r[3], "volume": r[4], "amount": r[5], "captured_at": r[6]} for r in rows}

    def _quote_rejection(self, quote: dict | None) -> str | None:
        if not quote or not quote.get("latest_price") or quote["latest_price"] <= 0: return "当前没有可用行情，委托未成交"
        try: captured = datetime.fromisoformat(quote["captured_at"]).astimezone(CN)
        except (TypeError, ValueError): return "行情时间无法确认，委托未成交"
        if (self.now - captured).total_seconds() > MAX_QUOTE_AGE_SECONDS: return "行情已超过12分钟未更新，为避免错误成交已拒绝委托"
        return None

    def _asset_view(self, row, quote: dict | None) -> dict:
        reason = self._quote_rejection(quote)
        history = self.conn.execute("SELECT captured_at,latest_price FROM intraday_quote_spot WHERE symbol=? AND captured_at>=? AND latest_price IS NOT NULL ORDER BY captured_at DESC LIMIT 30", (row[0], f"{self.now.date().isoformat()}T00:00:00")).fetchall()
        return {"symbol": row[0], "alias": row[1], "display_name": row[1], "category": row[2], "sector": row[3], "lot_size": row[4], "t_plus_one": bool(row[5]), "latest_price": quote.get("latest_price") if quote else None, "change_pct": quote.get("change_pct") if quote else None, "volume": quote.get("volume") if quote else None, "captured_at": quote.get("captured_at") if quote else None, "price_history": [{"captured_at": item[0], "price": item[1]} for item in reversed(history)], "tradable": reason is None and is_cn_trading_session(self.now.replace(tzinfo=None)), "unavailable_reason": reason}

    def _build_bulletin(self) -> list[dict]:
        rows = self.conn.execute("SELECT symbol,name,latest_price,change_pct,captured_at FROM intraday_index_spot WHERE captured_at=(SELECT MAX(captured_at) FROM intraday_index_spot) ORDER BY symbol").fetchall()
        if not rows:
            return [{"title": "今日暂无已确认重要市场公告", "detail": "行情与新闻数据尚未形成可核验的当日摘要。", "source": "系统覆盖台账", "published_at": _iso(self.now)}]
        names = "；".join(f"{r[1] or r[0]} {r[3]:+.2f}%" for r in rows if r[3] is not None)
        return [{"title": "主要指数盘中表现", "detail": names or "主要指数行情已更新。", "source": "xystock/AKShare-SINA 延迟行情", "published_at": rows[0][4]}]

    def _account_row(self, visitor_token: str):
        row = self.conn.execute("SELECT id,visitor_token,user_id,persona_code,nickname,initial_cash_cents,cash_cents,realized_pnl_cents,fees_cents,version,setup_status,setup_trade_date,setup_confirmed_at FROM paper_game_accounts WHERE visitor_token=?", (visitor_token,)).fetchone()
        if not row: raise PaperGameError("模拟账户不存在，请先创建账户")
        return row

    def _market_universe(self) -> list[tuple[str, str, str, str]]:
        """Fixed research equity universe plus the six simulation funds."""
        rows = self.conn.execute("SELECT payload FROM assets ORDER BY observed_at DESC").fetchall()
        bar_symbols = {row[0] for row in self.conn.execute("SELECT DISTINCT symbol FROM versioned_market_bars WHERE interval='1d' AND active=1").fetchall()}
        equities: dict[str, str] = {}
        for row in rows:
            try:
                payload = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                continue
            symbol = str(payload.get("ticker", "")).split(".")[0].zfill(6)
            if payload.get("asset_type") == "equity" and symbol.isdigit() and len(symbol) == 6 and (not bar_symbols or symbol in bar_symbols) and symbol not in equities:
                equities[symbol] = str(payload.get("name") or symbol)
        stock_rows = [(symbol, name, self._sector(symbol), "股票") for symbol, name in sorted(equities.items())]
        if not stock_rows:
            stock_rows = [(symbol, symbol, self._sector(symbol), "股票") for symbols in SECTOR_OVERRIDES.values() for symbol in symbols]
        fund_rows = [(symbol, ETF_NAMES[symbol], "黄金" if symbol == GOLD_SYMBOL else "指数基金", "黄金" if symbol == GOLD_SYMBOL else "基金") for symbol in sorted(ETF_SYMBOLS | {GOLD_SYMBOL})]
        return [*stock_rows, *fund_rows]

    def _equity_universe(self) -> list[tuple[str, str, str, str]]:
        return [item for item in self._market_universe() if item[3] == "股票"]

    def _sector(self, symbol: str) -> str:
        global _INDUSTRIES
        if _INDUSTRIES is None:
            _INDUSTRIES = {}
            path = Path(__file__).resolve().parents[3] / "artifacts/subagent_membership_breadth/normalized/industry_membership_intervals.jsonl"
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        item = json.loads(line)
                        if item.get("classification") == "证监会行业分类标准（2012）" and item.get("industry_level_1"):
                            _INDUSTRIES.setdefault(str(item["symbol"]).zfill(6), str(item["industry_level_1"]))
                    except (KeyError, TypeError, json.JSONDecodeError):
                        continue
        if symbol in _INDUSTRIES:
            return _INDUSTRIES[symbol]
        for sector, symbols in SECTOR_OVERRIDES.items():
            if symbol in symbols:
                return sector
        return "A股"

    def _latest_close_date(self) -> str | None:
        row = self.conn.execute("SELECT trade_date FROM paper_game_close_snapshots GROUP BY trade_date HAVING COUNT(*) >= ? ORDER BY trade_date DESC LIMIT 1", (len(self._equity_universe()),)).fetchone()
        return row[0] if row else None

    def capture_close_snapshots(self) -> dict:
        """Fetch and freeze the latest daily close for the independent game setup.

        This intentionally does not touch model/training tables.  It is called
        by the off-hours worker and is safe to retry after a provider failure.
        """
        from investment_research.integrations.xystock.quote_fetcher import fetch_kline
        inserted, dates = 0, set()
        for symbol, name, _sector, _kind in self._market_universe():
            result = fetch_kline(symbol, days=5)
            if not result.available or not result.data:
                continue
            bar = result.data[-1]
            trade_date, close = str(bar.get("date", ""))[:10], bar.get("close")
            if not trade_date or not close or float(close) <= 0:
                continue
            self.conn.execute("INSERT OR IGNORE INTO paper_game_close_snapshots (id,trade_date,symbol,display_name,close_cents,source,captured_at) VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), trade_date, symbol, name, _cents(float(close)), "xystock/AKShare daily close", _iso(self.now)))
            inserted += 1; dates.add(trade_date)
        self.conn.commit()
        return {"inserted": inserted, "trade_dates": sorted(dates), "ready": self._latest_close_date() is not None}

    def _alias(self, symbol: str) -> str:
        row = self.conn.execute("SELECT alias FROM paper_game_assets WHERE symbol=? ORDER BY rowid DESC LIMIT 1", (symbol,)).fetchone()
        return row[0] if row else "比赛标的"

    def _order(self, order_id: str) -> dict:
        row = self.conn.execute("SELECT id,symbol,side,quantity,status,rejection_reason,submitted_at,filled_at,fill_price_cents,fee_cents FROM paper_game_orders WHERE id=?", (order_id,)).fetchone()
        return {"id": row[0], "symbol": row[1], "alias": self._alias(row[1]), "side": row[2], "quantity": row[3], "status": row[4], "rejection_reason": row[5], "submitted_at": row[6], "filled_at": row[7], "fill_price": _money(row[8]), "fee": _money(row[9])}

    def _record_equity(self, account_id: str, cash: int, market: int, total: int) -> None:
        last = self.conn.execute("SELECT captured_at,total_equity_cents FROM paper_game_equity WHERE account_id=? ORDER BY captured_at DESC LIMIT 1", (account_id,)).fetchone()
        if last:
            try:
                if (self.now - datetime.fromisoformat(last[0]).astimezone(CN)).total_seconds() < 60 and last[1] == total: return
            except ValueError: pass
        self.conn.execute("INSERT INTO paper_game_equity (id,account_id,captured_at,cash_cents,market_value_cents,total_equity_cents) VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), account_id, _iso(self.now), cash, market, total)); self.conn.commit()

    def _max_drawdown(self, account_id: str) -> float:
        values = [r[0] for r in self.conn.execute("SELECT total_equity_cents FROM paper_game_equity WHERE account_id=? ORDER BY captured_at", (account_id,)).fetchall()]
        peak, drawdown = 0, 0.0
        for value in values:
            peak = max(peak, value)
            if peak: drawdown = min(drawdown, (value / peak - 1) * 100)
        return round(drawdown, 3)
