from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from heapq import heappop, heappush
from math import sqrt
from typing import Protocol


FEATURE_CONTRACT_VERSION = "investment-risk-features-v1"
FEATURE_CONTRACT_V2_VERSION = "investment-risk-features-v2"
INVESTMENT_RISK_FEATURE_ORDER = [
    "benchmark_ret_20d",
    "earnings_count_30d",
    "earnings_surprise_score_30d",
    "event_score_1d",
    "event_score_30d",
    "event_score_7d",
    "filing_8k_count_30d",
    "filing_count_30d",
    "guidance_cut_flag_30d",
    "halted_flag",
    "market_cn_flag",
    "market_hk_flag",
    "market_jp_flag",
    "market_us_flag",
    "mna_event_flag_30d",
    "negative_event_score_7d",
    "news_count_7d",
    "official_event_score_30d",
    "regulatory_risk_score_30d",
    "relative_strength_20d",
    "ret_20d",
    "ret_5d",
    "sector_relative_strength_20d",
    "sector_ret_20d",
    "style_relative_strength_20d",
    "style_ret_20d",
    "vol_20d",
    "vol_5d",
    "volume_z_20d",
]

# V2 is trained and approved independently; the deployed V1 order is intentionally
# unchanged until a V2 manifest passes the promotion gate.
INVESTMENT_RISK_FEATURE_V2_ADDITIONS = [
    "turnover_percentile_20d",
    "relative_liquidity_20d",
    "market_breadth_5d",
    "industry_strength_20d",
    "limit_up_flag",
    "limit_down_flag",
    "margin_financing_change_5d",
    "announcement_regulatory_count_30d",
    "announcement_shareholder_action_count_30d",
]
INVESTMENT_RISK_FEATURE_V2_ORDER = [*INVESTMENT_RISK_FEATURE_ORDER, *INVESTMENT_RISK_FEATURE_V2_ADDITIONS]


def asof_aligned_values(
    targets: list[tuple[date, datetime]],
    references: list[tuple[date, datetime, float]],
    *,
    max_gap_days: int = 7,
) -> list[float]:
    """Return the latest reference value public at each target cutoff."""
    return [
        value
        for value in asof_aligned_optional_values(
            targets, references, max_gap_days=max_gap_days
        )
        if value is not None
    ]


def asof_aligned_optional_values(
    targets: list[tuple[date, datetime]],
    references: list[tuple[date, datetime, float]],
    *,
    max_gap_days: int = 7,
) -> list[float | None]:
    """Align every target to a prior published value, preserving missing positions."""
    ordered = sorted(references, key=lambda item: (item[1], item[0]))
    pending: list[tuple[date, datetime, int, float]] = []
    cursor = 0
    aligned: list[float | None] = []
    latest: tuple[date, datetime, float] | None = None
    for target_date, target_cutoff in sorted(
        targets, key=lambda item: (item[1], item[0])
    ):
        while cursor < len(ordered) and ordered[cursor][1] <= target_cutoff:
            reference_date, published_at, value = ordered[cursor]
            heappush(pending, (reference_date, published_at, cursor, value))
            cursor += 1
        while pending and pending[0][0] <= target_date:
            reference_date, published_at, _, value = heappop(pending)
            candidate = (reference_date, published_at, value)
            if latest is None or candidate[:2] > latest[:2]:
                latest = candidate
        if latest is None:
            aligned.append(None)
            continue
        if (target_date - latest[0]).days <= max_gap_days:
            aligned.append(latest[2])
        else:
            aligned.append(None)
    return aligned


class StructuredEventLike(Protocol):
    published_at: datetime
    event_type: object
    event_direction: object
    event_intensity: object
    source_tier: object
    surprise_bucket: object
    guidance_bucket: object
    filing_subtype: str | None


@dataclass(frozen=True)
class StructuredEventRecord:
    published_at: datetime
    event_type: str
    event_direction: str = "unknown"
    event_intensity: str = "normal"
    source_tier: str = "aggregator"
    surprise_bucket: str = "unknown"
    guidance_bucket: str = "unknown"
    filing_subtype: str | None = None


def enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def window_return(closes: list[float]) -> float:
    if len(closes) < 2 or closes[0] == 0:
        return 0.0
    return (closes[-1] / closes[0]) - 1.0


def realized_volatility(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    returns = [
        (current / previous) - 1.0
        for previous, current in zip(closes, closes[1:])
        if previous != 0
    ]
    if not returns:
        return 0.0
    average = sum(returns) / len(returns)
    variance = sum((value - average) ** 2 for value in returns) / len(returns)
    return sqrt(variance)


def zscore(value: float, history: list[float]) -> float:
    if len(history) < 2:
        return 0.0
    average = sum(history) / len(history)
    variance = sum((item - average) ** 2 for item in history) / len(history)
    std = sqrt(variance)
    if std == 0:
        return 0.0
    return (value - average) / std


def count_recent_events(
    events: list[StructuredEventLike], as_of_date: date
) -> dict[str, int]:
    counts = {
        "news_count_7d": 0,
        "filing_count_30d": 0,
        "earnings_count_30d": 0,
    }
    for event in events:
        age_days = (as_of_date - event.published_at.date()).days
        if age_days < 0:
            continue
        event_type = enum_value(event.event_type)
        if event_type == "news" and age_days <= 7:
            counts["news_count_7d"] += 1
        if event_type in {"filing", "announcement"} and age_days <= 30:
            counts["filing_count_30d"] += 1
        if event_type == "earnings" and age_days <= 30:
            counts["earnings_count_30d"] += 1
    return counts


def build_structured_event_features(
    events: list[StructuredEventLike],
    as_of_date: date,
) -> dict[str, float]:
    features = {
        "event_score_1d": 0.0,
        "event_score_7d": 0.0,
        "event_score_30d": 0.0,
        "negative_event_score_7d": 0.0,
        "official_event_score_30d": 0.0,
        "earnings_surprise_score_30d": 0.0,
        "guidance_cut_flag_30d": 0.0,
        "regulatory_risk_score_30d": 0.0,
        "mna_event_flag_30d": 0.0,
        "filing_8k_count_30d": 0.0,
    }
    for event in events:
        age_days = (as_of_date - event.published_at.date()).days
        if age_days < 0 or age_days > 30:
            continue
        base_score = event_base_score(event)
        event_type = enum_value(event.event_type)
        if age_days <= 1:
            features["event_score_1d"] += decayed_score(
                base_score, age_days, half_life_days=1.0
            )
        if age_days <= 7:
            features["event_score_7d"] += decayed_score(
                base_score, age_days, half_life_days=3.0
            )
            if enum_value(event.event_direction) == "negative":
                features["negative_event_score_7d"] += decayed_score(
                    abs(base_score), age_days, half_life_days=3.0
                )
        features["event_score_30d"] += decayed_score(
            base_score, age_days, half_life_days=7.0
        )
        if enum_value(event.source_tier) in {"official", "exchange", "regulatory"}:
            features["official_event_score_30d"] += decayed_score(
                abs(base_score), age_days, half_life_days=10.0
            )
        if enum_value(event.surprise_bucket) != "unknown":
            features["earnings_surprise_score_30d"] += earnings_surprise_score(event)
        if enum_value(event.guidance_bucket) == "cut":
            features["guidance_cut_flag_30d"] = 1.0
        if event_type in {"regulation", "litigation", "policy"}:
            features["regulatory_risk_score_30d"] += decayed_score(
                abs(base_score), age_days, half_life_days=10.0
            )
        if event_type == "m&a":
            features["mna_event_flag_30d"] = 1.0
        if event_type == "filing" and (event.filing_subtype or "").upper() == "8-K":
            features["filing_8k_count_30d"] += 1.0
    return features


def event_base_score(event: StructuredEventLike) -> float:
    intensity_weight = {"major": 1.5, "normal": 1.0, "low": 0.5}.get(
        enum_value(event.event_intensity), 1.0
    )
    tier_weight = {
        "official": 1.2,
        "exchange": 1.15,
        "regulatory": 1.2,
        "mainstream_news": 1.0,
        "aggregator": 0.8,
    }.get(enum_value(event.source_tier), 0.8)
    direction_weight = {
        "positive": 1.0,
        "neutral": 0.35,
        "negative": -1.0,
        "unknown": 0.2,
    }.get(enum_value(event.event_direction), 0.2)
    return intensity_weight * tier_weight * direction_weight


def earnings_surprise_score(event: StructuredEventLike) -> float:
    return {
        "big_beat": 2.0,
        "beat": 1.0,
        "inline": 0.2,
        "miss": -1.0,
        "big_miss": -2.0,
        "unknown": 0.0,
    }.get(enum_value(event.surprise_bucket), 0.0)


def decayed_score(value: float, age_days: int, *, half_life_days: float) -> float:
    if half_life_days <= 0:
        return value
    return value * (0.5 ** (age_days / half_life_days))
