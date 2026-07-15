"""Data qualification is independent from source freshness or model quality."""
from __future__ import annotations

from enum import Enum


class DataTier(str, Enum):
    FORMAL_PIT = "formal_pit"
    RESEARCH_PIT = "research_pit"
    TEST_FIXTURE = "test_fixture"


RESEARCH_VISIBILITY_ASSUMPTION = "historical_available_at_unproven_public_backfill"
RESEARCH_TIER_REASONS = (
    RESEARCH_VISIBILITY_ASSUMPTION,
    "research_assumed_trade_date_availability",
    "historical_universe_incomplete",
)


def is_formal_tier(value: DataTier | str) -> bool:
    return value == DataTier.FORMAL_PIT or value == DataTier.FORMAL_PIT.value
