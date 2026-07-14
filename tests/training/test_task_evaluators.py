"""Tests for task-specific evaluators."""

from datetime import datetime, timedelta, timezone

import pytest

from investment_research.training.models import RiskBucketObservation
from investment_research.training.task_evaluators import (
    evaluate_drawdown_severity,
    evaluate_regime_aware,
    evaluate_time_to_event,
)


def _make_obs(
    score: float,
    drawdown: float,
    alerted_at: datetime | None = None,
    risk_event_at: datetime | None = None,
) -> RiskBucketObservation:
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return RiskBucketObservation(
        symbol="TEST",
        as_of_date=now.date(),
        score=score,
        future_max_drawdown_20d=drawdown,
        alerted_at=alerted_at,
        risk_event_at=risk_event_at,
    )


class TestEvaluateDrawdownSeverity:
    def test_raises_on_empty(self):
        with pytest.raises(ValueError):
            evaluate_drawdown_severity([])

    def test_returns_valid_metrics(self):
        observations = [
            _make_obs(0.9, -0.15),
            _make_obs(0.8, -0.12),
            _make_obs(0.5, -0.06),
            _make_obs(0.3, -0.04),
            _make_obs(0.1, -0.02),
        ]
        result = evaluate_drawdown_severity(observations)
        assert result.top_decile_mean_drawdown <= result.bottom_decile_mean_drawdown
        assert result.severity_lift <= 0

    def test_early_warning_ratio(self):
        observations = [
            _make_obs(0.9, -0.20),
            _make_obs(0.6, -0.05),
            _make_obs(0.4, -0.03),
            _make_obs(0.3, -0.02),
            _make_obs(0.2, -0.01),
        ]
        result = evaluate_drawdown_severity(observations, top_fraction=0.2)
        assert result.early_warning_ratio == 1.0  # only severe event in top decile

    def test_false_positive_rate(self):
        observations = [
            _make_obs(0.9, -0.02),  # false positive (not severe)
            _make_obs(0.1, -0.20),  # severe but not in top
        ]
        result = evaluate_drawdown_severity(observations, top_fraction=0.5)
        assert result.false_positive_rate == 1.0  # the only top item is a false positive


class TestEvaluateRegimeAware:
    def test_raises_on_mismatched_lengths(self):
        with pytest.raises(ValueError):
            evaluate_regime_aware([_make_obs(0.5, -0.05)], ["bull", "bear"])

    def test_separates_regimes(self):
        observations = [
            _make_obs(0.9, -0.15),
            _make_obs(0.8, -0.10),
            _make_obs(0.3, -0.04),
        ]
        regimes = ["bear", "bear", "bull"]
        result = evaluate_regime_aware(observations, regimes)
        assert result.regime_consistency >= 0.0


class TestEvaluateTimeToEvent:
    def test_no_events_returns_none(self):
        observations = [
            _make_obs(0.8, -0.04, alerted_at=datetime(2026, 1, 10, tzinfo=timezone.utc)),
        ]
        result = evaluate_time_to_event(observations)
        assert result.median_lead_days is None

    def test_computes_lead_time(self):
        observations = [
            _make_obs(
                0.9,
                -0.15,
                alerted_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
                risk_event_at=datetime(2026, 1, 12, tzinfo=timezone.utc),
            ),
        ]
        result = evaluate_time_to_event(observations)
        assert result.median_lead_days == 7.0
        assert result.early_capture_rate == 1.0

    def test_early_vs_late_capture(self):
        observations = [
            _make_obs(
                0.9,
                -0.10,
                alerted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                risk_event_at=datetime(2026, 1, 10, tzinfo=timezone.utc),  # 8 days lead
            ),
            _make_obs(
                0.7,
                -0.12,
                alerted_at=datetime(2026, 1, 8, tzinfo=timezone.utc),
                risk_event_at=datetime(2026, 1, 9, tzinfo=timezone.utc),  # 1 day lead
            ),
        ]
        result = evaluate_time_to_event(observations)
        assert result.early_capture_rate == 0.5
        assert result.late_capture_rate == 0.5
