"""Plan minimal downstream rebuilds after a data revision."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DataRevisionChange:
    dataset: str
    symbol: str
    start_date: date
    end_date: date
    old_revision_id: str | None
    new_revision_id: str


@dataclass(frozen=True)
class IncrementalRebuildPlan:
    feature_ranges: dict[str, tuple[date, date]]
    label_ranges: dict[str, tuple[date, date]]
    affected_symbols: tuple[str, ...]
    invalidated_snapshot_ids: tuple[str, ...]
    invalidated_model_versions: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "feature_ranges": {key: [start.isoformat(), end.isoformat()] for key, (start, end) in self.feature_ranges.items()},
            "label_ranges": {key: [start.isoformat(), end.isoformat()] for key, (start, end) in self.label_ranges.items()},
            "affected_symbols": list(self.affected_symbols),
            "invalidated_snapshot_ids": list(self.invalidated_snapshot_ids),
            "invalidated_model_versions": list(self.invalidated_model_versions),
        }


def plan_incremental_rebuild(
    changes: list[DataRevisionChange],
    *,
    feature_lookback_sessions: int = 60,
    label_horizons: tuple[int, ...] = (60, 120, 240),
    trading_dates: tuple[date, ...] = (),
    snapshot_ids: tuple[str, ...] = (),
    model_versions: tuple[str, ...] = (),
) -> IncrementalRebuildPlan:
    """Expand changed source dates to the smallest feature/label ranges.

    A feature at date *t* can depend on prior observations, so a revised source
    row affects features from the revised date forward until the lookback
    window no longer contains it. A forward label at *t* can depend on
    observations after *t*, so a revised row affects labels before the revised
    date. The two ranges are kept separate so a revision does not force a
    full-universe rebuild.
    """
    if feature_lookback_sessions < 0 or any(horizon <= 0 for horizon in label_horizons):
        raise ValueError("lookback and label horizons must be non-negative/positive")
    calendar = tuple(sorted(set(trading_dates)))
    feature_ranges: dict[str, tuple[date, date]] = {}
    label_ranges: dict[str, tuple[date, date]] = {}
    for change in changes:
        if calendar and (change.start_date not in calendar or change.end_date not in calendar):
            raise ValueError("revision range must use dates present in the trading calendar")
        feature_start = change.start_date
        feature_end = _shift_sessions(change.end_date, feature_lookback_sessions, calendar)
        feature_ranges[change.symbol] = _merge(feature_ranges.get(change.symbol), feature_start, feature_end)
        longest = max(label_horizons, default=0)
        label_start = _shift_sessions(change.start_date, -longest, calendar)
        label_end = change.end_date
        label_ranges[change.symbol] = _merge(label_ranges.get(change.symbol), label_start, label_end)
    return IncrementalRebuildPlan(
        feature_ranges=feature_ranges,
        label_ranges=label_ranges,
        affected_symbols=tuple(sorted({change.symbol for change in changes})),
        invalidated_snapshot_ids=tuple(snapshot_ids),
        invalidated_model_versions=tuple(model_versions),
    )


def _merge(existing: tuple[date, date] | None, start: date, end: date) -> tuple[date, date]:
    if existing is None:
        return start, end
    return min(existing[0], start), max(existing[1], end)


def _shift_sessions(value: date, offset: int, calendar: tuple[date, ...]) -> date:
    """Shift by verified sessions when supplied; retain legacy fallback otherwise."""
    if not calendar:
        return value + timedelta(days=offset)
    if offset == 0:
        return value
    import bisect

    index = bisect.bisect_left(calendar, value)
    if index >= len(calendar) or calendar[index] != value:
        raise ValueError(f"date is not present in trading calendar: {value.isoformat()}")
    target = max(0, min(len(calendar) - 1, index + offset))
    return calendar[target]
