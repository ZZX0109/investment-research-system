"""Coverage semantics for the free-data research feature contract.

The aggregate feature coverage on a PIT row intentionally includes optional
reference and event evidence.  Public CN sources frequently do not provide
those fields with a historical visibility guarantee, so using that aggregate
number as a hard price-data gate would make a usable price window look
unusable.  This module keeps the two facts separate: core market features are
gated for inference, while optional evidence remains visible as degraded
coverage and missing masks.
"""
from __future__ import annotations

from collections.abc import Mapping, Iterable


# These are the fields required for a price/market-state research estimate.
# Event, benchmark and financing fields are deliberately not silently promoted
# into this contract: their absence is still reported to the caller.
CORE_RESEARCH_FEATURES = (
    "ret_5d",
    "ret_20d",
    "vol_5d",
    "vol_20d",
    "volume_z_20d",
    "halted_flag",
    "limit_up_flag",
    "limit_down_flag",
    "turnover_percentile_20d",
    "relative_liquidity_20d",
    "market_cn_flag",
    "market_us_flag",
    "market_hk_flag",
    "market_jp_flag",
)


def feature_coverage_breakdown(
    features: Mapping[str, object], missing_features: Iterable[str] = ()
) -> tuple[float, float]:
    """Return ``(core_coverage, optional_coverage)`` for one row.

    A field listed in ``missing_features`` is missing even when a legacy
    standardizer left a placeholder value in ``features``.  Optional coverage
    is measured only over fields the row actually knows about; an empty
    optional set is reported as 1.0 because it is *not* a claim that optional
    sources were available.  The separate event/data status remains the source
    of that qualification.
    """
    present = set(features)
    missing = set(missing_features)
    core_missing = sum(
        name in missing or name not in present for name in CORE_RESEARCH_FEATURES
    )
    core = 1.0 - (core_missing / len(CORE_RESEARCH_FEATURES))

    optional_known = (present | missing) - set(CORE_RESEARCH_FEATURES)
    optional_missing = sum(name in missing or name not in present for name in optional_known)
    optional = 1.0 if not optional_known else 1.0 - (optional_missing / len(optional_known))
    return max(0.0, min(1.0, core)), max(0.0, min(1.0, optional))


def core_feature_coverage(features: Mapping[str, object], missing_features: Iterable[str] = ()) -> float:
    """Convenience wrapper used by inference and research reports."""
    return feature_coverage_breakdown(features, missing_features)[0]
