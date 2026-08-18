from pathlib import Path

import pytest

from investment_research.training.long_term_config import (
    LongTermTrainingConfig,
    load_long_term_training_config,
)


def test_long_term_config_is_long_horizon_and_ranked() -> None:
    config = load_long_term_training_config(Path("config/long_term_training.yaml"))
    assert config.profile == "long_term_investment_quality"
    assert max(config.horizons_days) == 960
    assert "excess_return_120d" in config.targets
    assert set(config.primary_targets) == {
        "excess_return_120d", "excess_return_240d",
        "future_max_drawdown_120d", "future_max_drawdown_240d",
    }
    assert set(config.auxiliary_targets) == {
        "future_quality_persistence_4q", "future_quality_persistence_8q",
    }
    assert config.short_horizon_role == "auxiliary_market_observation"
    assert "rank_ic" in config.evaluation_metrics
    assert {
        "pinball_loss", "mae", "interval_coverage", "capacity",
        "year_stability", "industry_stability", "regime_stability",
        "data_completeness_stability",
    }.issubset(config.evaluation_metrics)
    assert config.require_snapshot_gate is True
    assert "cn_fundamentals_research" in config.required_snapshot_datasets
    assert len(config.canonical_hash()) == 64


def test_short_horizon_targets_are_rejected() -> None:
    with pytest.raises(ValueError, match="short-horizon"):
        LongTermTrainingConfig(targets=["return_20d"])


def test_short_horizon_excess_return_is_rejected_from_long_term_contract() -> None:
    with pytest.raises(ValueError, match="short-horizon"):
        LongTermTrainingConfig(targets=["excess_return_5d"], horizons_days=[5], purge_days=5)


def test_purge_window_covers_longest_label() -> None:
    with pytest.raises(ValueError, match="purge_days"):
        LongTermTrainingConfig(purge_days=20)


def test_primary_long_term_targets_cannot_be_dropped() -> None:
    with pytest.raises(ValueError, match="primary_targets"):
        LongTermTrainingConfig(
            targets=["excess_return_120d"],
            primary_targets=["excess_return_120d"],
            auxiliary_targets=["excess_return_120d"],
            horizons_days=[120],
            purge_days=120,
            min_history_days=120,
        )
