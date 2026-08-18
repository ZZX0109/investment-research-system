from __future__ import annotations

from datetime import date

from investment_research.training.formal_preflight import PreflightStatus, run_formal_preflight
from investment_research.training.pipeline_config import PipelineMode, ProviderConfig, TrainingPipelineConfig


def test_preflight_materializes_missing_four_market_configuration_as_blocked(tmp_path) -> None:
    config = TrainingPipelineConfig(
        mode=PipelineMode.FORMAL,
        markets=["cn"],
        start_date=date(2020, 1, 1),
        end_date=date(2026, 1, 1),
        targets=["future_max_drawdown_20d"],
        embargo_days=20,
        providers={"cn": ProviderConfig(primary="licensed-cn")},
    )

    report = run_formal_preflight(config, training_run_id="formal-matrix", project_root=tmp_path)

    assert report.status == PreflightStatus.BLOCKED
    assert [item.market for item in report.markets] == ["cn", "us", "hk", "jp"]
    us = next(item for item in report.markets if item.market == "us")
    assert us.missing_requirements == ["formal_market_not_configured"]
