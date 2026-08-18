from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt

from investment_research.training.models import (
    EventType,
    LabelSet,
    PointInTimeEvent,
    PreparedPriceBar,
)


@dataclass(frozen=True)
class LabelGenerationContext:
    price_lookup: dict[date, PreparedPriceBar]
    ordered_dates: list[date]
    ordered_bars: list[PreparedPriceBar]
    index_by_date: dict[date, int]
    benchmark_lookup: dict[date, PreparedPriceBar]
    industry_lookup: dict[date, PreparedPriceBar]
    events: list[PointInTimeEvent]


@dataclass(frozen=True)
class TradeableLabelPolicy:
    version: str = "tradeable-label-v1"
    max_entry_delay_sessions: int = 5
    volatility_lookback: int = 20
    volatility_multiplier: float = 0.5
    minimum_cost_boundary: float = 0.002
    stock_round_trip_cost: float = 0.0021
    etf_round_trip_cost: float = 0.0012


def generate_tradeable_labels(
    *,
    symbol: str,
    as_of_date: date,
    price_bars: list[PreparedPriceBar],
    policy: TradeableLabelPolicy | None = None,
    context: LabelGenerationContext | None = None,
    instrument_is_etf: bool = False,
) -> LabelSet:
    """Generate execution-aware labels without pretending suspended/limit bars trade."""
    policy = policy or TradeableLabelPolicy()
    if context is None:
        ordered = sorted(price_bars, key=lambda item: item.trade_date)
        index = next(
            (i for i, item in enumerate(ordered) if item.trade_date == as_of_date), None
        )
    else:
        ordered = context.ordered_bars
        index = context.index_by_date.get(as_of_date)
    if index is None:
        raise ValueError("as_of_date must exist in prepared price bars")
    labels = LabelSet(symbol=symbol, as_of_date=as_of_date)
    candidates = ordered[index + 1 : index + 2 + policy.max_entry_delay_sessions]
    entry_offset = next(
        (
            i
            for i, bar in enumerate(candidates)
            if bar.is_tradeable
            and not bar.is_halted
            and not bar.is_suspended
            and not (bar.is_one_price_limit and bar.is_limit_up)
            and _bar_open(bar) > 0
        ),
        None,
    )
    if entry_offset is None:
        labels.label_available = False
        labels.label_unavailable_reason = "no_tradeable_entry_within_5_sessions"
        return labels
    entry_index = index + 1 + entry_offset
    entry = ordered[entry_index]
    entry_price = _bar_open(entry)
    labels.entry_trade_date = entry.trade_date
    labels.entry_delay_sessions = entry_offset
    labels.label_start = entry.trade_date

    past = ordered[max(0, index - policy.volatility_lookback + 1) : index + 1]
    trailing_vol = (
        _realized_volatility_from_closes([bar.close_normalized for bar in past]) or 0.0
    )
    for horizon in (1, 5, 20):
        window = ordered[entry_index : entry_index + horizon]
        if len(window) < horizon:
            if horizon == 20:
                labels.label_available = False
                labels.label_unavailable_reason = "insufficient_20_session_horizon"
            continue
        terminal_return = (window[-1].close_normalized / entry_price) - 1.0
        setattr(labels, f"future_return_{horizon}d", terminal_return)
        if horizon == 20:
            labels.future_return_20d_from_open = terminal_return
        # v2 research labels use volatility-standardised boundaries and an
        # execution-cost floor.  The legacy policy remains reproducible when
        # callers retain its original version string.
        cost_floor = policy.minimum_cost_boundary
        if policy.version in {
            "cn-direction-volatility-label-v2",
            "cn-direction-volatility-label-v3",
        }:
            round_trip = policy.etf_round_trip_cost if instrument_is_etf else policy.stock_round_trip_cost
            cost_floor = max(cost_floor, 2.0 * round_trip)
        threshold = max(
            cost_floor,
            trailing_vol * sqrt(horizon) * policy.volatility_multiplier,
        )
        standardized = terminal_return / max(trailing_vol * sqrt(horizon), 1e-12)
        setattr(labels, f"volatility_standardized_return_{horizon}d", standardized)
        setattr(labels, f"direction_threshold_{horizon}d", threshold)
        direction = (
            "up"
            if terminal_return > threshold
            else "down"
            if terminal_return < -threshold
            else "flat"
        )
        setattr(labels, f"direction_{horizon}d", direction)

    # Generate the execution-aware 5-session excess-return label independently
    # of the 20-session horizon.  Previously this block lived inside the
    # ``len(window_20) == 20`` branch, so otherwise valid 5d observations near
    # the sample tail inherited the 20d availability constraint.
    window_5 = ordered[entry_index : entry_index + 5]
    if len(window_5) == 5 and context is not None and labels.future_return_5d is not None:
        benchmark_entry = context.benchmark_lookup.get(window_5[0].trade_date)
        benchmark_terminal = context.benchmark_lookup.get(window_5[-1].trade_date)
        if benchmark_entry is not None and benchmark_terminal is not None:
            benchmark_entry_price = _bar_open(benchmark_entry)
            if benchmark_entry_price > 0:
                benchmark_return = benchmark_terminal.close_normalized / benchmark_entry_price - 1.0
                labels.excess_return_5d = labels.future_return_5d - benchmark_return

    window_20 = ordered[entry_index : entry_index + 20]
    if len(window_20) == 20:
        labels.label_end = window_20[-1].trade_date
        peak = entry_price
        worst = 0.0
        favorable = 0.0
        adverse = 0.0
        for bar in window_20:
            high = _bar_high(bar)
            low = _bar_low(bar)
            peak = max(peak, high)
            worst = min(worst, (low / peak) - 1.0)
            adverse = min(adverse, (low / entry_price) - 1.0)
            favorable = max(favorable, (high / entry_price) - 1.0)
        labels.future_max_drawdown_20d = worst
        labels.drawdown_exceeds_8pct_20d = worst <= -0.08
        labels.drawdown_exceeds_12pct_20d = worst <= -0.12
        labels.drawdown_exceeds_15pct_20d = worst <= -0.15
        labels.maximum_adverse_excursion_20d = adverse
        labels.maximum_favorable_excursion_20d = favorable
        labels.encountered_suspension_20d = any(
            bar.is_halted or bar.is_suspended for bar in window_20
        )
        labels.touched_limit_up_20d = any(bar.is_limit_up for bar in window_20)
        labels.touched_limit_down_20d = any(bar.is_limit_down for bar in window_20)
        if context is not None:
            benchmark_entry = context.benchmark_lookup.get(entry.trade_date)
            benchmark_terminal = context.benchmark_lookup.get(window_20[-1].trade_date)
            if benchmark_entry is not None and benchmark_terminal is not None:
                benchmark_entry_price = _bar_open(benchmark_entry)
                if benchmark_entry_price > 0:
                    benchmark_return = benchmark_terminal.close_normalized / benchmark_entry_price - 1.0
                    labels.excess_return_20d = labels.future_return_20d_from_open - benchmark_return
    long_term_available = True
    long_term_reasons: list[str] = []
    for horizon in (60, 120, 240):
        window = ordered[entry_index : entry_index + horizon]
        if len(window) == horizon:
            peak = entry_price
            worst = 0.0
            for bar in window:
                peak = max(peak, _bar_high(bar))
                worst = min(worst, (_bar_low(bar) / peak) - 1.0)
            setattr(labels, f"future_max_drawdown_{horizon}d", worst)
            benchmark_entry = context.benchmark_lookup.get(window[0].trade_date) if context is not None else None
            benchmark_terminal = context.benchmark_lookup.get(window[-1].trade_date) if context is not None else None
            if benchmark_entry is not None and benchmark_terminal is not None:
                benchmark_entry_price = _bar_open(benchmark_entry)
                if benchmark_entry_price > 0:
                    benchmark_return = benchmark_terminal.close_normalized / benchmark_entry_price - 1.0
                    terminal_return = window[-1].close_normalized / entry_price - 1.0
                    setattr(labels, f"excess_return_{horizon}d", terminal_return - benchmark_return)
                else:
                    long_term_available = False
                    long_term_reasons.append(f"benchmark_entry_price_invalid_{horizon}d")
            else:
                long_term_available = False
                long_term_reasons.append(f"benchmark_missing_{horizon}d")
        else:
            long_term_available = False
            long_term_reasons.append(f"insufficient_{horizon}_session_horizon")
    labels.long_term_label_available = long_term_available
    labels.long_term_label_unavailable_reason = None if long_term_available else ";".join(long_term_reasons)
    return labels


def _bar_open(bar: PreparedPriceBar) -> float:
    return bar.open_normalized or bar.open_native or bar.close_normalized


def _bar_high(bar: PreparedPriceBar) -> float:
    return bar.high_normalized or bar.high_native or bar.close_normalized


def _bar_low(bar: PreparedPriceBar) -> float:
    return bar.low_normalized or bar.low_native or bar.close_normalized


def build_label_generation_context(
    *,
    price_bars: list[PreparedPriceBar],
    benchmark_bars: list[PreparedPriceBar] | None = None,
    industry_reference_bars: list[PreparedPriceBar] | None = None,
    events: list[PointInTimeEvent] | None = None,
) -> LabelGenerationContext:
    price_lookup = {bar.trade_date: bar for bar in price_bars}
    ordered_dates = sorted(price_lookup)
    return LabelGenerationContext(
        price_lookup=price_lookup,
        ordered_dates=ordered_dates,
        ordered_bars=[price_lookup[item] for item in ordered_dates],
        index_by_date={
            trade_date: index for index, trade_date in enumerate(ordered_dates)
        },
        benchmark_lookup={bar.trade_date: bar for bar in benchmark_bars or []},
        industry_lookup={bar.trade_date: bar for bar in industry_reference_bars or []},
        events=sorted(events or [], key=lambda item: item.published_at),
    )


def generate_multitask_labels(
    *,
    symbol: str,
    as_of_date: date,
    price_bars: list[PreparedPriceBar],
    benchmark_bars: list[PreparedPriceBar] | None = None,
    industry_reference_bars: list[PreparedPriceBar] | None = None,
    events: list[PointInTimeEvent] | None = None,
    context: LabelGenerationContext | None = None,
) -> LabelSet:
    resolved = context or build_label_generation_context(
        price_bars=price_bars,
        benchmark_bars=benchmark_bars,
        industry_reference_bars=industry_reference_bars,
        events=events,
    )
    benchmark_lookup = resolved.benchmark_lookup
    industry_lookup = resolved.industry_lookup
    event_list = resolved.events
    price_lookup = resolved.price_lookup
    ordered_dates = resolved.ordered_dates
    if as_of_date not in price_lookup:
        raise ValueError("as_of_date must exist in prepared price bars")

    start_index = resolved.index_by_date[as_of_date]
    future_dates = ordered_dates[start_index + 1 : start_index + 121]
    future_closes = [price_lookup[item].close_normalized for item in future_dates]
    base_close = price_lookup[as_of_date].close_normalized

    labels = LabelSet(symbol=symbol, as_of_date=as_of_date)
    labels.future_return_1d = _simple_return(base_close, future_closes[:1])
    labels.future_return_5d = _simple_return(base_close, future_closes[:5])
    if future_closes[:5]:
        returns_5d = [(value / base_close) - 1.0 for value in future_closes[:5]]
        labels.maximum_adverse_excursion_5d = min(returns_5d)
        labels.maximum_favorable_excursion_5d = max(returns_5d)
    for horizon in (5, 20, 60, 120):
        horizon_dates = future_dates[:horizon]
        closes = [price_lookup[item].close_normalized for item in horizon_dates]
        setattr(
            labels, f"future_max_drawdown_{horizon}d", _max_drawdown(base_close, closes)
        )
        setattr(
            labels,
            f"future_volatility_{horizon}d",
            _realized_volatility(base_close, closes),
        )
        setattr(
            labels,
            f"excess_return_{horizon}d",
            _excess_return(
                base_close=base_close,
                closes=closes,
                benchmark_lookup=benchmark_lookup,
                benchmark_base_date=as_of_date,
                horizon_dates=horizon_dates,
            ),
        )
        setattr(
            labels,
            f"industry_excess_return_{horizon}d",
            _excess_return(
                base_close=base_close,
                closes=closes,
                benchmark_lookup=industry_lookup,
                benchmark_base_date=as_of_date,
                horizon_dates=horizon_dates,
            ),
        )

    horizon_20_dates = future_dates[:20]
    horizon_20_closes = [
        price_lookup[item].close_normalized for item in horizon_20_dates
    ]
    horizon_10_dates = future_dates[:10]
    horizon_10_closes = [
        price_lookup[item].close_normalized for item in horizon_10_dates
    ]
    past_60_dates = ordered_dates[max(0, start_index - 59) : start_index + 1]
    past_60_closes = [price_lookup[item].close_normalized for item in past_60_dates]

    labels.future_return_20d = _simple_return(base_close, horizon_20_closes)
    future_volatility_20d = labels.future_volatility_20d
    if labels.future_return_20d is not None and future_volatility_20d is not None:
        labels.risk_adjusted_return_20d = labels.future_return_20d / max(
            future_volatility_20d, 1e-6
        )
    current_trailing_vol_60d = _realized_volatility_from_closes(past_60_closes)
    future_volatility_10d = _realized_volatility(base_close, horizon_10_closes)
    if current_trailing_vol_60d is not None and future_volatility_10d is not None:
        labels.volatility_spike_10d = future_volatility_10d - current_trailing_vol_60d
    labels.event_drawdown_5d = _event_window_drawdown(
        as_of_date=as_of_date,
        bars=price_lookup,
        events=event_list,
        event_types={
            EventType.EARNINGS,
            EventType.FILING,
            EventType.ANNOUNCEMENT,
            EventType.POLICY,
            EventType.LITIGATION,
            EventType.MNA,
            EventType.REGULATION,
        },
        window_days=5,
    )

    labels.post_earnings_abnormal_move_5d = _event_window_move(
        as_of_date=as_of_date,
        bars=price_lookup,
        events=event_list,
        event_types={EventType.EARNINGS, EventType.FILING, EventType.ANNOUNCEMENT},
        window_days=5,
    )
    labels.news_event_shock_3d = _event_window_move(
        as_of_date=as_of_date,
        bars=price_lookup,
        events=event_list,
        event_types={EventType.NEWS},
        window_days=3,
    )
    return labels


def _max_drawdown(base_close: float, closes: list[float]) -> float | None:
    if not closes:
        return None
    peak = base_close
    worst = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = (close / peak) - 1.0
        worst = min(worst, drawdown)
    return worst


def _realized_volatility(base_close: float, closes: list[float]) -> float | None:
    if len(closes) < 2 or base_close <= 0:
        return None
    returns: list[float] = []
    previous = base_close
    for close in closes:
        returns.append((close / previous) - 1.0)
        previous = close
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / len(returns)
    return sqrt(variance)


def _realized_volatility_from_closes(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    return _realized_volatility(closes[0], closes[1:])


def _simple_return(base_close: float, closes: list[float]) -> float | None:
    if not closes or base_close <= 0:
        return None
    return (closes[-1] / base_close) - 1.0


def _excess_return(
    *,
    base_close: float,
    closes: list[float],
    benchmark_lookup: dict[date, PreparedPriceBar],
    benchmark_base_date: date,
    horizon_dates: list[date],
) -> float | None:
    if not closes or benchmark_base_date not in benchmark_lookup or not horizon_dates:
        return None
    last_date = horizon_dates[-1]
    if last_date not in benchmark_lookup:
        return None
    asset_return = (closes[-1] / base_close) - 1.0
    benchmark_base = benchmark_lookup[benchmark_base_date].close_normalized
    benchmark_return = (
        benchmark_lookup[last_date].close_normalized / benchmark_base
    ) - 1.0
    return asset_return - benchmark_return


def _event_window_move(
    *,
    as_of_date: date,
    bars: dict[date, PreparedPriceBar],
    events: list[PointInTimeEvent],
    event_types: set[EventType],
    window_days: int,
) -> float | None:
    eligible = [
        event
        for event in events
        if event.event_type in event_types
        and event.published_at.date() > as_of_date
        and event.published_at.date() in bars
    ]
    if not eligible:
        return None
    first_event = sorted(eligible, key=lambda item: item.published_at)[0]
    start_date = first_event.published_at.date()
    base = bars[start_date].close_normalized
    max_abs_move: float | None = None
    for offset in range(1, window_days + 1):
        next_date = start_date + timedelta(days=offset)
        if next_date not in bars:
            continue
        move = abs((bars[next_date].close_normalized / base) - 1.0)
        max_abs_move = move if max_abs_move is None else max(max_abs_move, move)
    return max_abs_move


def _event_window_drawdown(
    *,
    as_of_date: date,
    bars: dict[date, PreparedPriceBar],
    events: list[PointInTimeEvent],
    event_types: set[EventType],
    window_days: int,
) -> float | None:
    eligible = [
        event
        for event in events
        if event.event_type in event_types
        and event.published_at.date() > as_of_date
        and event.published_at.date() in bars
    ]
    if not eligible:
        return None
    first_event = sorted(eligible, key=lambda item: item.published_at)[0]
    start_date = first_event.published_at.date()
    base = bars[start_date].close_normalized
    closes: list[float] = []
    for offset in range(1, window_days + 1):
        next_date = start_date + timedelta(days=offset)
        if next_date in bars:
            closes.append(bars[next_date].close_normalized)
    return _max_drawdown(base, closes) if closes else None
