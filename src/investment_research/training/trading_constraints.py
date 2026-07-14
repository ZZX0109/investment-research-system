from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from investment_research.domain.pit import TradingCostSchedule


class ConstrainedReturn(BaseModel):
    gross_return: float
    net_return: float | None = None
    strategy_metric_publishable: bool
    applied_cost_version: str | None = None
    reasons: list[str] = Field(default_factory=list)


def apply_trading_constraints(
    gross_return: float,
    *,
    market: str,
    entry_date: date,
    holding_sessions: int,
    average_daily_amount: float | None,
    schedule: TradingCostSchedule | None,
) -> ConstrainedReturn:
    if schedule is None or not schedule.verified:
        return ConstrainedReturn(
            gross_return=gross_return,
            strategy_metric_publishable=False,
            reasons=["trading_cost_schedule_unverified"],
        )
    if (
        schedule.market != market
        or entry_date < schedule.effective_from
        or (schedule.effective_to and entry_date > schedule.effective_to)
    ):
        return ConstrainedReturn(
            gross_return=gross_return,
            strategy_metric_publishable=False,
            reasons=["trading_cost_schedule_not_effective"],
        )
    if schedule.settlement_rule.upper() == "T+1" and holding_sessions < 1:
        return ConstrainedReturn(
            gross_return=gross_return,
            strategy_metric_publishable=False,
            reasons=["t_plus_one_violation"],
        )
    if (
        average_daily_amount is None
        or average_daily_amount < schedule.minimum_liquidity_amount
    ):
        return ConstrainedReturn(
            gross_return=gross_return,
            strategy_metric_publishable=False,
            reasons=["liquidity_constraint_failed"],
        )
    return ConstrainedReturn(
        gross_return=gross_return,
        net_return=gross_return - schedule.round_trip_cost,
        strategy_metric_publishable=True,
        applied_cost_version=schedule.version,
    )
