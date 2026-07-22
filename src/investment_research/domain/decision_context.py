from __future__ import annotations

from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


SHANGHAI = ZoneInfo("Asia/Shanghai")


class ExchangeSessionSpec(BaseModel):
    calendar_code: str
    timezone: str
    open_time: time
    close_time: time
    pre_open_time: time


EXCHANGE_SESSIONS: dict[str, ExchangeSessionSpec] = {
    "XSHG": ExchangeSessionSpec(
        calendar_code="XSHG",
        timezone="Asia/Shanghai",
        open_time=time(9, 30),
        close_time=time(15),
        pre_open_time=time(9, 10),
    ),
    "XSHE": ExchangeSessionSpec(
        calendar_code="XSHE",
        timezone="Asia/Shanghai",
        open_time=time(9, 30),
        close_time=time(15),
        pre_open_time=time(9, 10),
    ),
    "XBSE": ExchangeSessionSpec(
        calendar_code="XBSE",
        timezone="Asia/Shanghai",
        open_time=time(9, 30),
        close_time=time(15),
        pre_open_time=time(9, 10),
    ),
    "XNYS": ExchangeSessionSpec(
        calendar_code="XNYS",
        timezone="America/New_York",
        open_time=time(9, 30),
        close_time=time(16),
        pre_open_time=time(9, 10),
    ),
    "XNAS": ExchangeSessionSpec(
        calendar_code="XNAS",
        timezone="America/New_York",
        open_time=time(9, 30),
        close_time=time(16),
        pre_open_time=time(9, 10),
    ),
    "XHKG": ExchangeSessionSpec(
        calendar_code="XHKG",
        timezone="Asia/Hong_Kong",
        open_time=time(9, 30),
        close_time=time(16),
        pre_open_time=time(9, 10),
    ),
    "XTKS": ExchangeSessionSpec(
        calendar_code="XTKS",
        timezone="Asia/Tokyo",
        open_time=time(9),
        close_time=time(15, 30),
        pre_open_time=time(8, 50),
    ),
}


class DecisionContextType(str, Enum):
    CLOSE_CONFIRMED = "close_confirmed"
    PRE_OPEN = "pre_open"


class DecisionContext(BaseModel):
    """The explicit point-in-time contract for one research decision."""

    context_type: DecisionContextType
    trade_date: date
    decision_time: datetime
    prediction_start_date: date
    timezone: str = "Asia/Shanghai"
    confirmation_delay_minutes: int = Field(default=10, ge=0, le=180)

    @model_validator(mode="after")
    def validate_time(self) -> "DecisionContext":
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        local_zone = ZoneInfo(self.timezone)
        if self.decision_time.astimezone(local_zone).date() < self.trade_date:
            raise ValueError("decision_time cannot precede trade_date")
        return self

    def permits(self, available_at: datetime) -> bool:
        if available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        return available_at <= self.decision_time


def build_decision_context(
    trade_date: date,
    context_type: DecisionContextType | str = DecisionContextType.CLOSE_CONFIRMED,
    *,
    confirmation_delay_minutes: int = 10,
    trading_dates: list[date] | None = None,
) -> DecisionContext:
    kind = DecisionContextType(context_type)
    next_date = _next_trading_date(trade_date, trading_dates)
    if kind == DecisionContextType.CLOSE_CONFIRMED:
        decision_time = datetime.combine(trade_date, time(15, 0), SHANGHAI) + timedelta(
            minutes=confirmation_delay_minutes
        )
    else:
        decision_time = datetime.combine(next_date, time(9, 10), SHANGHAI)
    return DecisionContext(
        context_type=kind,
        trade_date=trade_date,
        decision_time=decision_time,
        prediction_start_date=next_date,
        confirmation_delay_minutes=confirmation_delay_minutes,
    )


def build_market_decision_context(
    trade_date: date,
    context_type: DecisionContextType | str,
    *,
    calendar_code: str,
    confirmation_delay_minutes: int = 10,
    trading_dates: list[date] | None = None,
    next_trading_date: date | None = None,
) -> DecisionContext:
    """Build a decision cutoff from an exchange-local session, including DST."""
    code = calendar_code.strip().upper()
    if code not in EXCHANGE_SESSIONS:
        raise ValueError(f"unsupported exchange calendar: {code}")
    spec = EXCHANGE_SESSIONS[code]
    zone = ZoneInfo(spec.timezone)
    kind = DecisionContextType(context_type)
    next_date = next_trading_date or _next_trading_date(trade_date, trading_dates)
    if kind == DecisionContextType.CLOSE_CONFIRMED:
        decision_time = datetime.combine(trade_date, spec.close_time, zone) + timedelta(
            minutes=confirmation_delay_minutes
        )
    else:
        decision_time = datetime.combine(next_date, spec.pre_open_time, zone)
    return DecisionContext(
        context_type=kind,
        trade_date=trade_date,
        decision_time=decision_time,
        prediction_start_date=next_date,
        timezone=spec.timezone,
        confirmation_delay_minutes=confirmation_delay_minutes,
    )


def _next_trading_date(current: date, trading_dates: list[date] | None) -> date:
    if trading_dates:
        future = sorted(item for item in set(trading_dates) if item > current)
        if future:
            return future[0]
    candidate = current + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate
