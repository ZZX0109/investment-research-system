from investment_research.training.catalog import (
    TARGET_COVERAGE_GROUP_COUNTS,
    TARGET_MARKET_TOTALS,
    TARGET_MARKET_TYPE_COUNTS,
    UNIVERSE_PRESETS,
    iter_market_presets,
    market_distribution,
    market_symbols,
    validate_universe_distribution,
)
from investment_research.training.models import CoverageGroup, InstrumentType, Market


def test_universe_distribution_is_128_and_balanced() -> None:
    assert len(UNIVERSE_PRESETS) == 128
    assert not validate_universe_distribution()

    distribution = market_distribution()
    for market, expected in TARGET_MARKET_TYPE_COUNTS.items():
        assert len(market_symbols(market)) == TARGET_MARKET_TOTALS[market]
        assert distribution[market.value]["equity"] == expected[InstrumentType.EQUITY]
        assert distribution[market.value]["etf"] == expected[InstrumentType.ETF]
        assert distribution[market.value]["index"] == expected[InstrumentType.INDEX]

    us_groups = [preset.coverage_group for preset in iter_market_presets(Market.US)]
    assert us_groups.count(CoverageGroup.CHINA_ADR) == TARGET_COVERAGE_GROUP_COUNTS[Market.US][CoverageGroup.CHINA_ADR]


def test_every_preset_has_required_training_metadata() -> None:
    for preset in UNIVERSE_PRESETS.values():
        assert preset.market is not None
        assert preset.instrument_type is not None
        assert preset.industry_key
        assert preset.benchmark_symbol
        assert preset.sector_reference_symbol
        assert preset.style_reference_symbol
        assert preset.primary_provider is not None
