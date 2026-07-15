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

FREE_RESEARCH_PROVIDERS = frozenset({
    "akshare", "akshare_cninfo_notices", "baostock", "yfinance",
    "sec", "sec_edgar", "hkex", "hkexnews", "fred", "fred_public_csv",
    "edinet", "tdnet",
})


def is_formal_tier(value: DataTier | str) -> bool:
    return value == DataTier.FORMAL_PIT or value == DataTier.FORMAL_PIT.value


def formal_data_blocking_reasons(
    *, data_tier: DataTier | str, provider: str, request_id: str,
) -> list[str]:
    reasons: list[str] = []
    if not is_formal_tier(data_tier):
        reasons.append("data_tier_is_not_formal_pit")
    if provider.lower() in FREE_RESEARCH_PROVIDERS:
        reasons.append("free_research_provider_forbidden_in_formal_path")
    if request_id.lower().startswith("free-"):
        reasons.append("free_request_prefix_forbidden_in_formal_path")
    return reasons
