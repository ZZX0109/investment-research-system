"""Shared contracts for the reproducible trusted-risk-gate evidence pack."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from statistics import mean, stdev

TRUST_FRAMEWORK_VERSION = "trusted-risk-gate-v1"
PRIMARY_TASK = "future_max_drawdown_20d"

PRICE_FEATURES = ["ret_5d", "ret_20d", "vol_5d", "vol_20d", "volume_z_20d", "halted_flag", "market_cn_flag", "market_us_flag", "market_hk_flag", "market_jp_flag"]
REFERENCE_FEATURES = ["benchmark_ret_20d", "relative_strength_20d", "sector_ret_20d", "sector_relative_strength_20d", "style_ret_20d", "style_relative_strength_20d"]
EVENT_FEATURES = ["news_count_7d", "filing_count_30d", "earnings_count_30d", "event_score_1d", "event_score_7d", "event_score_30d", "negative_event_score_7d", "official_event_score_30d", "earnings_surprise_score_30d", "guidance_cut_flag_30d", "regulatory_risk_score_30d", "mna_event_flag_30d", "filing_8k_count_30d"]


def sample_snapshot_hash(samples: Iterable[object]) -> str:
    """Hash only point-in-time identifiers; labels and future values are excluded."""
    rows = [
        {
            "symbol": sample.symbol,
            "as_of": sample.as_of_date.isoformat(),
            "market": getattr(sample.market, "value", sample.market),
            "feature_version": sample.feature_version,
            "data_version": sample.data_version,
            "feature_cutoff": sample.feature_cutoff.isoformat(),
        }
        for sample in sorted(samples, key=lambda item: (item.as_of_date, item.symbol))
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()


def confidence_interval(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"mean": None, "lower": None, "upper": None, "fold_count": 0}
    avg = mean(values)
    margin = 0.0 if len(values) == 1 else 1.96 * stdev(values) / math.sqrt(len(values))
    return {"mean": round(avg, 6), "lower": round(avg - margin, 6), "upper": round(avg + margin, 6), "fold_count": len(values)}


def gate_eligible(sample: object) -> bool:
    """Offline proxy for production gate inputs available in a training sample.

    This deliberately does not claim to execute the live Judge. It captures only
    frozen, point-in-time conditions that have direct training equivalents.
    """
    return bool(
        getattr(sample, "event_source_available", False)
        and getattr(sample, "feature_coverage", 0.0) >= 0.75
        and getattr(sample, "point_in_time_event_count", 0) >= 2
        and not getattr(sample, "data_issues", [])
    )
