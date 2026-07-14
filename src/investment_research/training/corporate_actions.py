"""Corporate action adjustment engine for split and dividend handling.

Handles the real processing logic for split_factor and dividend_cash fields
already present in CanonicalPriceBar, which were previously ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from investment_research.training.models import CanonicalPriceBar


@dataclass
class AdjustmentRecord:
    """Tracks a single corporate action event and its impact."""

    trade_date: str
    event_type: str  # "split" or "dividend"
    description: str
    split_ratio: float | None = None
    dividend_per_share: float | None = None


def adjust_price_bars_for_corporate_actions(
    bars: list[CanonicalPriceBar],
) -> tuple[list[CanonicalPriceBar], list[AdjustmentRecord]]:
    """Apply split and dividend adjustments to price bars in-place.

    Processes bars in chronological order and adjusts all earlier bars
    when a corporate action is encountered. This ensures the entire
    price series reflects the latest capital structure.

    Args:
        bars: Unsorted or sorted list of canonical price bars.

    Returns:
        (adjusted_bars, adjustment_records): Bars with adjusted prices
        and the list of corporate actions that were applied.
    """
    if not bars:
        return bars, []

    ordered = sorted(bars, key=lambda b: b.trade_date)
    records: list[AdjustmentRecord] = []
    cumulative_split_multiplier = 1.0
    cumulative_dividend_adjustment = 0.0

    for i in range(len(ordered) - 1, -1, -1):
        bar = ordered[i]

        # Apply accumulated adjustments to this bar (affects earlier dates)
        needs_adjust = (
            cumulative_split_multiplier != 1.0
            or cumulative_dividend_adjustment != 0.0
        )
        if needs_adjust:
            adjusted = _apply_cumulative_adjustments(
                bar,
                cumulative_split_multiplier,
                cumulative_dividend_adjustment,
            )
            ordered[i] = adjusted

        # Check if this bar triggers a new corporate action
        has_split = bar.split_factor is not None and bar.split_factor > 0.0 and bar.split_factor != 1.0
        has_dividend = bar.dividend_cash is not None and bar.dividend_cash > 0.0

        if has_split or has_dividend:
            if has_split and bar.split_factor is not None:
                cumulative_split_multiplier *= bar.split_factor
            if has_dividend and bar.dividend_cash is not None:
                dividend_ratio = bar.dividend_cash / bar.close if bar.close > 0 else 0.0
                cumulative_dividend_adjustment += dividend_ratio

            records.append(
                AdjustmentRecord(
                    trade_date=bar.trade_date.isoformat(),
                    event_type="split" if has_split else "dividend",
                    description=_describe_action(bar),
                    split_ratio=bar.split_factor,
                    dividend_per_share=bar.dividend_cash,
                )
            )

    return ordered, records


def calculate_adjustment_factors(
    bars: list[CanonicalPriceBar],
) -> list[float]:
    """Calculate cumulative backward adjustment factors for each bar.

    These factors can be multiplied with raw prices to obtain
    fully adjusted series. Factor = 1.0 means no adjustment needed.

    Args:
        bars: Chronologically sorted bars.

    Returns:
        List of adjustment factors per bar (same order as input).
    """
    ordered = sorted(bars, key=lambda b: b.trade_date)
    factors = [1.0] * len(ordered)

    cumulative = 1.0
    for i in range(len(ordered) - 1, -1, -1):
        bar = ordered[i]
        factors[i] = cumulative
        if bar.split_factor is not None and bar.split_factor != 1.0:
            cumulative *= bar.split_factor

    return factors


def detect_unadjusted_bars(bars: list[CanonicalPriceBar]) -> list[str]:
    """Detect bars that have corporate action data but inconsistent prices.

    Returns a list of warning messages for bars where split_factor or
    dividend_cash is present but prices appear not to have been adjusted.
    """
    ordered = sorted(bars, key=lambda b: b.trade_date)
    warnings: list[str] = []

    for i in range(len(ordered)):
        bar = ordered[i]
        if bar.split_factor is not None and bar.split_factor != 1.0:
            if i > 0:
                prev = ordered[i - 1]
                expected_ratio = bar.split_factor
                actual_ratio = bar.close / prev.close if prev.close > 0 else 1.0
                if abs(actual_ratio - expected_ratio) > 0.3 * expected_ratio:
                    warnings.append(
                        f"Possible unadjusted split on {bar.trade_date}: "
                        f"split_factor={bar.split_factor}, "
                        f"expected_ratio={expected_ratio:.4f}, "
                        f"actual_ratio={actual_ratio:.4f}"
                    )

    return warnings


def _apply_cumulative_adjustments(
    bar: CanonicalPriceBar,
    split_mult: float,
    dividend_ratio: float,
) -> CanonicalPriceBar:
    """Apply cumulative split and dividend adjustments to a single bar."""
    price_fields = {
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
    }
    if bar.adjusted_close is not None:
        price_fields["adjusted_close"] = bar.adjusted_close

    adjusted_fields: dict[str, float] = {}
    for field_name, value in price_fields.items():
        new_value = value * split_mult
        if dividend_ratio != 0.0:
            new_value *= 1.0 - dividend_ratio
        adjusted_fields[field_name] = new_value

    return CanonicalPriceBar(
        symbol=bar.symbol,
        trade_date=bar.trade_date,
        open=adjusted_fields["open"],
        high=adjusted_fields["high"],
        low=adjusted_fields["low"],
        close=adjusted_fields["close"],
        adjusted_close=adjusted_fields.get("adjusted_close"),
        volume=bar.volume,
        currency=bar.currency,
        fx_rate_to_usd=bar.fx_rate_to_usd,
        is_halted=bar.is_halted,
        is_suspended=bar.is_suspended,
        split_factor=bar.split_factor,
        dividend_cash=bar.dividend_cash,
        calendar_code=bar.calendar_code,
        published_at=bar.published_at,
    )


def _describe_action(bar: CanonicalPriceBar) -> str:
    parts: list[str] = []
    if bar.split_factor is not None and bar.split_factor != 1.0:
        parts.append(f"split {bar.split_factor}:1")
    if bar.dividend_cash is not None and bar.dividend_cash > 0.0:
        parts.append(f"dividend ${bar.dividend_cash:.4f}/share")
    return "; ".join(parts) if parts else "corporate action"
