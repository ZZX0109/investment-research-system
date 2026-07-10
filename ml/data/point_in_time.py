from __future__ import annotations

from datetime import date


def assert_point_in_time(as_of_date: str, observed_dates: list[str]) -> None:
    as_of = date.fromisoformat(as_of_date[:10])
    for value in observed_dates:
        observed = date.fromisoformat(value[:10])
        if observed > as_of:
            raise AssertionError(f"future data leakage: observed {observed} after asOfDate {as_of}")


def source_status(source_name: str) -> str:
    lowered = source_name.lower()
    if "synthetic" in lowered or "demo" in lowered or "fallback" in lowered:
        return "degraded"
    return "live"

