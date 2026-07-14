from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from investment_research.training.catalog import UNIVERSE_PRESETS
from investment_research.training.models import PreparedPriceBar, TrainingSample, WalkForwardFold

REGIME_RULE_VERSION = "per-market-v2"


@dataclass(frozen=True)
class FinalHoldoutSplit:
    development: list[TrainingSample]
    holdout_12m: list[TrainingSample]
    stress_6m: list[TrainingSample]
    holdout_start: date
    stress_start: date


def build_final_holdout_split(
    samples: list[TrainingSample],
    *,
    holdout_sessions: int = 252,
    stress_sessions: int = 126,
) -> FinalHoldoutSplit:
    """Reserve global time boundaries across all symbols; never tune on holdout."""
    dates = sorted({sample.as_of_date for sample in samples})
    if len(dates) <= holdout_sessions:
        raise ValueError("insufficient dates for a 12-month final holdout")
    if stress_sessions > holdout_sessions:
        raise ValueError("stress slice must be inside final holdout")
    holdout_start = dates[-holdout_sessions]
    stress_start = dates[-stress_sessions]
    development = [
        sample
        for sample in samples
        if sample.as_of_date < holdout_start
        and (sample.labels.label_end is None or sample.labels.label_end < holdout_start)
    ]
    holdout = [sample for sample in samples if sample.as_of_date >= holdout_start]
    stress = [sample for sample in holdout if sample.as_of_date >= stress_start]
    return FinalHoldoutSplit(development, holdout, stress, holdout_start, stress_start)


def samples_for_fold(
    samples: list[TrainingSample], fold: WalkForwardFold
) -> tuple[list[TrainingSample], list[TrainingSample]]:
    """Apply the fold and explicitly purge labels crossing validation_start."""
    train = [
        sample
        for sample in samples
        if fold.train_start <= sample.as_of_date <= fold.train_end
        and (sample.labels.label_end is None or sample.labels.label_end < fold.validation_start)
    ]
    validation = [
        sample
        for sample in samples
        if fold.validation_start <= sample.as_of_date <= fold.validation_end
    ]
    return train, validation


def build_walk_forward_folds(
    dates: list[date],
    *,
    train_window_days: int,
    validation_window_days: int,
    step_days: int | None = None,
    regime_reference: list[PreparedPriceBar] | None = None,
    prediction_horizon_days: int = 0,
    embargo_days: int | None = None,
) -> list[WalkForwardFold]:
    if train_window_days <= 0 or validation_window_days <= 0:
        raise ValueError("train_window_days and validation_window_days must be positive")

    ordered_dates = sorted(set(dates))
    embargo = prediction_horizon_days if embargo_days is None else embargo_days
    gap = max(prediction_horizon_days, embargo)
    if len(ordered_dates) < train_window_days + gap + validation_window_days:
        return []

    step = step_days or validation_window_days
    folds: list[WalkForwardFold] = []
    start = 0
    fold_index = 1
    while start + train_window_days + gap + validation_window_days <= len(ordered_dates):
        train_dates = ordered_dates[start : start + train_window_days]
        validation_start = start + train_window_days + gap
        validation_dates = ordered_dates[validation_start : validation_start + validation_window_days]
        regime = infer_market_regime(validation_dates, regime_reference=regime_reference)
        folds.append(
            WalkForwardFold(
                fold_id=f"wf-{fold_index:03d}",
                train_start=train_dates[0],
                train_end=train_dates[-1],
                validation_start=validation_dates[0],
                validation_end=validation_dates[-1],
                regime=regime,
                label_horizon_days=prediction_horizon_days,
                purge_days=prediction_horizon_days,
                embargo_days=embargo,
            )
        )
        start += step
        fold_index += 1
    return folds


def infer_market_regime(
    validation_dates: list[date],
    *,
    regime_reference: list[PreparedPriceBar] | None = None,
) -> str:
    if not regime_reference or len(validation_dates) < 2:
        return "unknown"

    market_groups = _reference_bars_by_market(regime_reference)
    if len(market_groups) > 1:
        market_regimes = {
            market: _infer_regime_from_reference(validation_dates, bars)
            for market, bars in sorted(market_groups.items())
        }
        return _combine_market_regimes(market_regimes)

    return _infer_regime_from_reference(validation_dates, regime_reference)


def _infer_regime_from_reference(
    validation_dates: list[date],
    regime_reference: list[PreparedPriceBar],
) -> str:
    reference_closes = _daily_reference_closes(regime_reference)
    available = [reference_closes[item] for item in validation_dates if item in reference_closes]
    if len(available) < 2:
        return "unknown"

    start_close = available[0]
    end_close = available[-1]
    total_return = (end_close / start_close) - 1.0
    worst_drawdown = _max_drawdown(available)
    volatility = _simple_volatility(available)
    historical_volatility_threshold = _historical_volatility_threshold(
        reference_closes,
        validation_end=validation_dates[-1],
        window_size=min(20, len(available)),
    )

    if _is_high_volatility(volatility, historical_volatility_threshold):
        return "high_vol"

    if total_return >= 0.1 and worst_drawdown > -0.08:
        return "bull"
    if total_return <= -0.1 or worst_drawdown <= -0.12:
        return "bear"
    return "range"


def _reference_bars_by_market(regime_reference: list[PreparedPriceBar]) -> dict[str, list[PreparedPriceBar]]:
    grouped: dict[str, list[PreparedPriceBar]] = {}
    for bar in regime_reference:
        preset = UNIVERSE_PRESETS.get(bar.symbol.upper())
        market = preset.market.value if preset is not None else "unknown"
        grouped.setdefault(market, []).append(bar)
    return {market: bars for market, bars in grouped.items() if market != "unknown" and bars}


def _combine_market_regimes(market_regimes: dict[str, str]) -> str:
    known = [regime for regime in market_regimes.values() if regime != "unknown"]
    if not known:
        return "unknown"
    counts = Counter(known)
    if counts["high_vol"] > 0:
        return "high_vol"
    if counts["bear"] > 0 and counts["bear"] >= counts["bull"]:
        return "bear"
    if counts["bull"] >= max(1, len(known) // 2):
        return "bull"
    return "range"


def _max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    worst = 0.0
    for close in closes[1:]:
        peak = max(peak, close)
        worst = min(worst, (close / peak) - 1.0)
    return worst


def _simple_volatility(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    returns = [(current / previous) - 1.0 for previous, current in zip(closes, closes[1:])]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return variance ** 0.5


def _daily_reference_closes(regime_reference: list[PreparedPriceBar]) -> dict[date, float]:
    bars_by_symbol: dict[str, list[PreparedPriceBar]] = {}
    for bar in regime_reference:
        if bar.close_normalized <= 0:
            continue
        bars_by_symbol.setdefault(bar.symbol, []).append(bar)

    returns_by_date: dict[date, list[float]] = {}
    for bars in bars_by_symbol.values():
        ordered = sorted(bars, key=lambda item: item.trade_date)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.close_normalized <= 0:
                continue
            daily_return = (current.close_normalized / previous.close_normalized) - 1.0
            returns_by_date.setdefault(current.trade_date, []).append(max(-0.2, min(0.2, daily_return)))

    if returns_by_date:
        index_level = 100.0
        reference_index: dict[date, float] = {}
        for trade_date in sorted(returns_by_date):
            daily_returns = returns_by_date[trade_date]
            mean_return = sum(daily_returns) / len(daily_returns)
            index_level *= 1.0 + mean_return
            reference_index[trade_date] = index_level
        return reference_index

    closes_by_date: dict[date, list[float]] = {}
    for bars in bars_by_symbol.values():
        for bar in bars:
            closes_by_date.setdefault(bar.trade_date, []).append(bar.close_normalized)
    return {
        trade_date: sum(closes) / len(closes)
        for trade_date, closes in closes_by_date.items()
        if closes
    }


def _historical_volatility_threshold(
    reference_closes: dict[date, float],
    *,
    validation_end: date,
    window_size: int,
) -> float:
    if window_size < 2:
        return 0.0
    ordered = [
        close
        for trade_date, close in sorted(reference_closes.items())
        if trade_date <= validation_end
    ]
    if len(ordered) < window_size:
        return 0.0
    volatilities: list[float] = []
    for index in range(window_size, len(ordered) + 1):
        volatilities.append(_simple_volatility(ordered[index - window_size : index]))
    if not volatilities:
        return 0.0
    return _percentile(volatilities, 0.9)


def _is_high_volatility(volatility: float, historical_threshold: float) -> bool:
    if volatility >= 0.02:
        return True
    return historical_threshold > 0 and volatility >= historical_threshold


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)
