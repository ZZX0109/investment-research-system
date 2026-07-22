from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from investment_research.training.models import InstrumentType, LabelSet, Market, TrainingSample
from investment_research.training.research_evaluation import (
    ResearchCostPolicy,
    classify_market_regime,
    fit_regime_thresholds,
    research_scope_reports,
    write_research_reports,
)


@dataclass
class Candidate:
    name: str
    ece: float
    regime_metrics: dict


@dataclass
class Result:
    fold_hash: str
    selected_candidate: str
    candidates: list[Candidate]
    holdout_labels: list[int]
    stress_labels: list[int]


def test_research_reports_are_hashed_and_never_deployable(tmp_path: Path) -> None:
    when = datetime(2026, 7, 14, tzinfo=timezone.utc)
    sample = TrainingSample(
        symbol="600519", market=Market.CN, instrument_type=InstrumentType.EQUITY,
        as_of_date=date(2026, 7, 14), as_of_time=when, feature_cutoff=when,
        feature_version="v2", data_version="snapshot", features={"vol_20d": 0.2},
        labels=LabelSet(symbol="600519", as_of_date=date(2026, 7, 14)),
    )
    reports = research_scope_reports(
        task="drawdown_20d",
        result=Result("f" * 64, "historical-distribution", [Candidate("historical-distribution", 0.1, {})], [0], [0]),
        samples=[sample], dataset_hash="d" * 64, snapshot_hash="s" * 64,
        cohort="cn_equity_core",
    )
    hashes = write_research_reports(tmp_path, reports)
    assert reports["approval"]["deployment_ready"] is False
    assert reports["approval"]["status"] == "research_only"
    assert set(hashes) == set(reports)
    assert all((tmp_path / f"{name}.json").is_file() for name in reports)


def test_cost_policy_matches_conservative_stock_and_etf_assumptions() -> None:
    policy = ResearchCostPolicy()
    assert policy.round_trip_cost_ratio(is_etf=False) == 0.0021
    assert policy.round_trip_cost_ratio(is_etf=True) == 0.0012


def test_regime_thresholds_are_fitted_from_training_rows_not_fixed_constants() -> None:
    when = datetime(2026, 7, 14, tzinfo=timezone.utc)
    samples = []
    for index, (benchmark, volatility) in enumerate(((-0.10, 0.10), (-0.04, 0.11), (0.00, 0.11), (0.05, 0.12), (0.10, 0.11), (0.15, 0.11), (0.20, 0.13), (0.30, 0.60))):
        samples.append(TrainingSample(
            symbol=f"600{index:03d}", market=Market.CN, instrument_type=InstrumentType.EQUITY,
            as_of_date=date(2026, 7, 14), as_of_time=when, feature_cutoff=when,
            feature_version="cn-research-feature-v3", data_version="snapshot",
            features={"benchmark_ret_20d": benchmark, "vol_20d": volatility},
            labels=LabelSet(symbol=f"600{index:03d}", as_of_date=date(2026, 7, 14)),
        ))
    thresholds = fit_regime_thresholds(samples)
    assert thresholds.benchmark_bear < thresholds.benchmark_bull
    assert thresholds.volatility_high >= 0.12
    assert classify_market_regime(samples[0], thresholds) == "bear"
    assert classify_market_regime(samples[-1], thresholds) == "high_vol"
    assert {classify_market_regime(sample, thresholds) for sample in samples} == {
        "bull", "bear", "range", "high_vol"
    }
