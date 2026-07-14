from datetime import date, datetime, timezone
from types import SimpleNamespace

from investment_research.training.trust_framework import confidence_interval, gate_eligible, sample_snapshot_hash


def sample(*, symbol: str = "AAA", issues: list[str] | None = None):
    return SimpleNamespace(
        symbol=symbol,
        as_of_date=date(2025, 1, 1),
        market=SimpleNamespace(value="us"),
        feature_version="v1",
        data_version="real-v1",
        feature_cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_source_available=True,
        feature_coverage=0.9,
        point_in_time_event_count=2,
        data_issues=issues or [],
    )


def test_snapshot_hash_is_stable_and_excludes_labels() -> None:
    first = sample()
    second = sample()
    first.labels = {"future": -0.2}
    second.labels = {"future": 0.5}

    assert sample_snapshot_hash([first]) == sample_snapshot_hash([second])


def test_gate_eligible_requires_frozen_quality_inputs() -> None:
    assert gate_eligible(sample()) is True
    assert gate_eligible(sample(issues=["future_event"])) is False


def test_confidence_interval_exposes_fold_distribution() -> None:
    interval = confidence_interval([0.7, 0.8, 0.9])
    assert interval["fold_count"] == 3
    assert interval["lower"] < interval["mean"] < interval["upper"]
