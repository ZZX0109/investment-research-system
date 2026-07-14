from __future__ import annotations

from datetime import date, datetime

from investment_research.training.models import (
    CalendarHandlingPolicy,
    CanonicalPriceBar,
    DataQualityIssue,
    DataQualityRuleSet,
    HaltHandlingPolicy,
    IssueSeverity,
    PointInTimeEvent,
    PreparedPriceBar,
)


def prepare_price_bars(
    bars: list[CanonicalPriceBar],
    *,
    rules: DataQualityRuleSet,
) -> tuple[list[PreparedPriceBar], list[DataQualityIssue]]:
    issues: list[DataQualityIssue] = []
    prepared: list[PreparedPriceBar] = []
    seen_dates: set[date] = set()
    previous_date: date | None = None

    for bar in sorted(bars, key=lambda item: item.trade_date):
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="non_positive_ohlc",
                    severity=IssueSeverity.ERROR,
                    message="OHLC prices must all be positive.",
                )
            )
            continue
        if bar.trade_date in seen_dates:
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="duplicate_trade_date",
                    severity=IssueSeverity.ERROR,
                    message="Duplicate trade date detected in price history.",
                )
            )
            continue
        seen_dates.add(bar.trade_date)

        if previous_date and bar.trade_date <= previous_date:
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="non_monotonic_trade_date",
                    severity=IssueSeverity.ERROR,
                    message="Trade dates must be strictly increasing after sorting.",
                )
            )
            continue
        previous_date = bar.trade_date

        if bar.is_halted or bar.is_suspended:
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="halted_or_suspended",
                    severity=IssueSeverity.WARN,
                    message="Trading halt or suspension present in training window.",
                )
            )
            if rules.halt_policy == HaltHandlingPolicy.EXCLUDE:
                continue

        if (
            rules.currency_policy.value == "convert_to_usd"
            and bar.currency != rules.target_currency
            and bar.fx_rate_to_usd is None
        ):
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="missing_fx_rate",
                    severity=IssueSeverity.ERROR,
                    message="FX rate is required when converting non-target currency bars.",
                )
            )
            continue

        if (
            rules.adjustment_policy.value == "adjusted_close"
            and bar.adjusted_close is None
        ):
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="missing_adjusted_close",
                    severity=IssueSeverity.ERROR,
                    message="Adjusted close is required under adjusted-close policy.",
                )
            )
            continue

        normalized_close = (
            bar.adjusted_close
            if rules.adjustment_policy.value == "adjusted_close"
            else bar.close
        )
        assert normalized_close is not None
        if (
            rules.currency_policy.value == "convert_to_usd"
            and bar.currency != rules.target_currency
        ):
            normalized_close *= bar.fx_rate_to_usd or 1.0

        volume = bar.volume
        if volume is None:
            if rules.missing_value_policy.value == "error":
                issues.append(
                    DataQualityIssue(
                        symbol=bar.symbol,
                        trade_date=bar.trade_date,
                        code="missing_volume",
                        severity=IssueSeverity.ERROR,
                        message="Volume is missing and the current policy disallows imputation.",
                    )
                )
                continue
            if rules.missing_value_policy.value == "drop":
                continue
            volume = prepared[-1].volume if prepared else 0.0

        prepared.append(
            PreparedPriceBar(
                symbol=bar.symbol,
                trade_date=bar.trade_date,
                close_native=bar.close,
                close_normalized=normalized_close,
                open_native=bar.open,
                high_native=bar.high,
                low_native=bar.low,
                open_normalized=bar.open * (normalized_close / bar.close),
                high_normalized=bar.high * (normalized_close / bar.close),
                low_normalized=bar.low * (normalized_close / bar.close),
                volume=volume,
                amount=bar.amount,
                turnover_rate=bar.turnover_rate,
                margin_financing_balance=bar.margin_financing_balance,
                market_breadth_5d=bar.market_breadth_5d,
                currency=bar.currency,
                target_currency=rules.target_currency,
                is_halted=bar.is_halted,
                is_suspended=bar.is_suspended,
                published_at=bar.published_at,
                source_time=bar.source_time,
                received_at=bar.received_at,
                persisted_at=bar.persisted_at,
                available_at=bar.available_at or bar.published_at,
                calendar_code=bar.calendar_code,
                revision=bar.revision,
                adjustment_factor=bar.adjustment_factor,
                is_limit_up=bar.is_limit_up,
                is_limit_down=bar.is_limit_down,
                is_one_price_limit=bar.is_one_price_limit,
                is_tradeable=bar.is_tradeable,
                provider=bar.provider,
                as_of=bar.as_of or bar.published_at,
                payload_ref=bar.payload_ref,
                source_url=bar.source_url,
                raw_hash=bar.raw_hash,
                normalized_hash=bar.normalized_hash,
                data_version=bar.data_version,
            )
        )

    _validate_calendar_gaps(prepared, rules, issues)
    return prepared, issues


def select_point_in_time_events(
    events: list[PointInTimeEvent], *, as_of: datetime
) -> list[PointInTimeEvent]:
    return sorted(
        [event for event in events if event.published_at <= as_of],
        key=lambda item: (item.published_at, item.event_time),
    )


def detect_future_leakage(
    *,
    bars: list[PreparedPriceBar],
    events: list[PointInTimeEvent],
    as_of: datetime,
) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for bar in bars:
        if (bar.available_at or bar.published_at) > as_of:
            issues.append(
                DataQualityIssue(
                    symbol=bar.symbol,
                    trade_date=bar.trade_date,
                    code="future_price_bar",
                    severity=IssueSeverity.ERROR,
                    message="Price bar published after feature cutoff would leak future information.",
                )
            )
    for event in events:
        if (event.available_at or event.published_at) > as_of:
            issues.append(
                DataQualityIssue(
                    symbol=event.symbol,
                    code="future_event",
                    severity=IssueSeverity.ERROR,
                    message="Event published after feature cutoff would leak future information.",
                )
            )
    return issues


def _validate_calendar_gaps(
    bars: list[PreparedPriceBar],
    rules: DataQualityRuleSet,
    issues: list[DataQualityIssue],
) -> None:
    if rules.calendar_policy != CalendarHandlingPolicy.STRICT or len(bars) < 2:
        return

    for previous, current in zip(bars, bars[1:]):
        gap = (current.trade_date - previous.trade_date).days
        if gap > 5:
            issues.append(
                DataQualityIssue(
                    symbol=current.symbol,
                    trade_date=current.trade_date,
                    code="calendar_gap",
                    severity=IssueSeverity.WARN,
                    message="Observed a gap larger than one trading week. Confirm suspensions or calendar settings.",
                )
            )
