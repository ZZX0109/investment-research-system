from investment_research.training.research_feature_coverage import (
    CORE_RESEARCH_FEATURES,
    feature_coverage_breakdown,
)


def test_optional_event_and_reference_gaps_do_not_hide_core_price_coverage():
    features = {name: 1.0 for name in CORE_RESEARCH_FEATURES}
    core, optional = feature_coverage_breakdown(
        features,
        ["news_count_7d", "benchmark_ret_20d", "event_score_7d"],
    )
    assert core == 1.0
    assert optional == 0.0


def test_missing_core_field_reduces_core_coverage_even_with_placeholder():
    features = {name: 1.0 for name in CORE_RESEARCH_FEATURES}
    features["vol_20d"] = 0.0
    core, _ = feature_coverage_breakdown(features, ["vol_20d"])
    assert core < 1.0
