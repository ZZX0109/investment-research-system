from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def temporal_split(as_of_date: str) -> str:
    day = date.fromisoformat(as_of_date[:10])
    if day <= date(2022, 12, 31):
        return "train"
    if day <= date(2023, 12, 31):
        return "validation"
    if day <= date(2025, 12, 31):
        return "test"
    return "shadow"


def apply_embargo(dates: Iterable[str], embargo_days: int = 90) -> dict[str, str]:
    sorted_dates = sorted(date.fromisoformat(item[:10]) for item in dates)
    blocked: dict[str, str] = {}
    for split_date in (date(2022, 12, 31), date(2023, 12, 31), date(2025, 12, 31)):
        start = split_date - timedelta(days=embargo_days)
        end = split_date + timedelta(days=embargo_days)
        for day in sorted_dates:
            if start <= day <= end:
                blocked[day.isoformat()] = "embargo"
    return blocked

