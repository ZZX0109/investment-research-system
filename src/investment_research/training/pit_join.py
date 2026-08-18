"""One point-in-time/as-of join implementation for training and replay."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class PITJoinResult:
    target_index: int
    value: Any | None
    revision_id: str | None
    missing_reason: str | None


class PITJoinService:
    """Select the latest revision visible at a target decision time.

    A reference is eligible only when both its effective date and available
    timestamp are no later than the target. Missing timestamps are rejected by
    default, preventing historical backfills from silently becoming PIT data.
    """

    def join(
        self,
        targets: Iterable[tuple[date, datetime]],
        references: Iterable[dict[str, Any]],
        *,
        value_field: str = "value",
        allow_unproven_available_at: bool = False,
    ) -> list[PITJoinResult]:
        target_list = list(targets)
        refs = list(references)
        results: list[PITJoinResult] = []
        for index, (target_date, decision_time) in enumerate(target_list):
            normalized_decision_time = _as_datetime(decision_time)
            if normalized_decision_time is None:
                results.append(PITJoinResult(index, None, None, "decision_time_invalid"))
                continue
            eligible: list[dict[str, Any]] = []
            for reference in refs:
                effective = _as_date(reference.get("effective_date") or reference.get("trade_date"))
                available = _as_datetime(reference.get("available_at"))
                published = _as_datetime(reference.get("published_at"))
                if effective is None or effective > target_date:
                    continue
                if available is None:
                    if not allow_unproven_available_at:
                        continue
                    available = published
                if available is None or available > normalized_decision_time:
                    continue
                eligible.append({**reference, "_effective": effective, "_available": available})
            if not eligible:
                reason = "available_at_unproven_or_not_visible"
                results.append(PITJoinResult(index, None, None, reason))
                continue
            chosen = max(
                eligible,
                key=lambda item: (
                    item["_effective"],
                    item["_available"],
                    _revision_sort_key(item),
                ),
            )
            results.append(
                PITJoinResult(
                    target_index=index,
                    value=chosen.get(value_field),
                    revision_id=str(chosen.get("revision_id") or chosen.get("revision") or "unknown"),
                    missing_reason=None,
                )
            )
        return results

    def latest_visible(
        self,
        records: Iterable[Any],
        decision_time: datetime,
        *,
        effective_field: str = "as_of_date",
        available_field: str = "as_of_time",
        revision_field: str = "revision_id",
    ) -> Any | None:
        """Return the latest domain record visible at ``decision_time``.

        This is the object-oriented counterpart of :meth:`join` for frozen
        samples used by inference and replay.
        """
        cutoff = _as_datetime(decision_time)
        if cutoff is None:
            return None
        eligible: list[tuple[tuple[date, datetime, tuple[int, str]], Any]] = []
        for record in records:
            effective_date = _as_date(_value(record, effective_field))
            available = _as_datetime(_value(record, available_field))
            if effective_date is None or available is None or available > cutoff:
                continue
            revision = _value(record, revision_field) or _value(record, "revision")
            key = (effective_date, available, _revision_sort_key({"revision_id": revision}))
            eligible.append((key, record))
        return max(eligible, key=lambda item: item[0])[1] if eligible else None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _revision_sort_key(reference: dict[str, Any]) -> tuple[int, str]:
    numeric = reference.get("revision")
    try:
        return int(numeric or 0), str(reference.get("revision_id") or "")
    except (TypeError, ValueError):
        return 0, str(reference.get("revision_id") or "")


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        # A naive timestamp has no defensible PIT meaning.  Do not silently
        # reinterpret it as UTC: that can move a publication across a market
        # session boundary and turn an invalid historical join into leakage.
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
        except ValueError:
            return None
    return None


def _value(record: Any, field: str) -> Any:
    if isinstance(record, dict):
        return record.get(field)
    return getattr(record, field, None)
