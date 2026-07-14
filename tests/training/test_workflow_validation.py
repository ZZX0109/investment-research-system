"""Tests for workflow validation modules."""

from datetime import datetime, timedelta, timezone

from investment_research.training.models import (
    RiskBucketObservation,
)
from investment_research.training.workflow_validation import (
    compute_risk_alert_lead_time,
    measure_explanation_stability,
    rank_observation_pool,
)


def _make_observation(
    symbol: str = "AAPL",
    score: float = 0.8,
    drawdown: float = 0.15,
    alerted_hours_ago: float | None = 10,
    event_hours_ago: float | None = 5,
) -> RiskBucketObservation:
    now = datetime.now(timezone.utc)
    return RiskBucketObservation(
        symbol=symbol,
        score=score,
        future_max_drawdown_20d=drawdown,
        alerted_at=now - timedelta(hours=alerted_hours_ago)
        if alerted_hours_ago is not None
        else None,
        risk_event_at=now - timedelta(hours=event_hours_ago)
        if event_hours_ago is not None
        else None,
    )

# ---------------------------------------------------------------------------
# Observation Pool Ranking
# ---------------------------------------------------------------------------

class TestRankObservationPool:
    def test_sort_by_score_descending(self):
        obs = [
            _make_observation(symbol="A", score=0.5),
            _make_observation(symbol="B", score=0.9),
            _make_observation(symbol="C", score=0.3),
        ]
        ranked = rank_observation_pool(obs)
        assert [r.symbol for r in ranked] == ["B", "A", "C"]

    def test_top_k_limit(self):
        obs = [_make_observation(symbol=s, score=0.1 * i) for i, s in enumerate("ABCDEF")]
        ranked = rank_observation_pool(obs, top_k=3)
        assert len(ranked) == 3
        assert ranked[0].symbol == "F"

    def test_min_score_filter(self):
        obs = [
            _make_observation(symbol="A", score=0.8),
            _make_observation(symbol="B", score=0.3),
            _make_observation(symbol="C", score=0.6),
        ]
        ranked = rank_observation_pool(obs, min_score=0.5)
        assert {r.symbol for r in ranked} == {"A", "C"}

    def test_max_alerted_days_ago_filter(self):
        obs = [
            _make_observation(symbol="A", score=0.8, alerted_hours_ago=1000),  # > 30 days
            _make_observation(symbol="B", score=0.7, alerted_hours_ago=10),
            _make_observation(symbol="C", score=0.9, alerted_hours_ago=None),   # kept
        ]
        ranked = rank_observation_pool(obs, max_alerted_days_ago=30)
        assert {r.symbol for r in ranked} == {"B", "C"}


# ---------------------------------------------------------------------------
# Lead Time
# ---------------------------------------------------------------------------

class TestComputeRiskAlertLeadTime:
    def test_positive_lead_time(self):
        now = datetime.now(timezone.utc)
        obs = RiskBucketObservation(
            symbol="AAPL",
            score=0.8,
            future_max_drawdown_20d=0.15,
            alerted_at=now - timedelta(days=10),
            risk_event_at=now - timedelta(days=5),
        )
        result = compute_risk_alert_lead_time([obs])
        assert result["n_matched"] == 1
        assert result["lead_times_days"][0] > 0
        assert result["missed_count"] == 0

    def test_negative_lead_time_missed(self):
        now = datetime.now(timezone.utc)
        obs = RiskBucketObservation(
            symbol="AAPL",
            score=0.8,
            future_max_drawdown_20d=0.15,
            alerted_at=now - timedelta(days=5),
            risk_event_at=now - timedelta(days=10),
        )
        result = compute_risk_alert_lead_time([obs])
        assert result["missed_count"] == 1

    def test_filters_by_event_threshold(self):
        now = datetime.now(timezone.utc)
        obs = RiskBucketObservation(
            symbol="AAPL",
            score=0.8,
            future_max_drawdown_20d=0.05,  # below threshold
            alerted_at=now - timedelta(days=5),
            risk_event_at=now - timedelta(days=1),
        )
        result = compute_risk_alert_lead_time([obs], event_threshold=0.1)
        assert result["n_matched"] == 0

    def test_empty_returns_zero(self):
        result = compute_risk_alert_lead_time([])
        assert result["n_matched"] == 0
        assert result["missed_ratio"] == 0.0


# ---------------------------------------------------------------------------
# Explanation Stability
# ---------------------------------------------------------------------------

class TestMeasureExplanationStability:
    def test_identical_folds_max_similarity(self):
        fold_top_features = {
            "fold_1": ["feat_a", "feat_b", "feat_c", "feat_d", "feat_e"],
            "fold_2": ["feat_a", "feat_b", "feat_c", "feat_d", "feat_e"],
        }
        result = measure_explanation_stability(fold_top_features)
        assert result["mean_similarity"] == 1.0

    def test_disjoint_folds_zero_similarity(self):
        fold_top_features = {
            "fold_1": ["a", "b", "c", "d", "e"],
            "fold_2": ["v", "w", "x", "y", "z"],
        }
        result = measure_explanation_stability(fold_top_features)
        assert result["mean_similarity"] == 0.0

    def test_partial_overlap(self):
        fold_top_features = {
            "fold_1": ["a", "b", "c", "d", "e"],
            "fold_2": ["c", "d", "e", "f", "g"],
        }
        result = measure_explanation_stability(fold_top_features)
        # intersection: {c, d, e} = 3; union: {a, b, c, d, e, f, g} = 7
        assert 0.35 < result["mean_similarity"] < 0.5

    def test_feature_frequencies(self):
        fold_top_features = {
            "fold_1": ["a", "b", "c"],
            "fold_2": ["a", "c", "d"],
            "fold_3": ["a", "e", "f"],
        }
        result = measure_explanation_stability(fold_top_features)
        assert result["feature_frequencies"]["a"] == 3  # present in all folds
        assert result["feature_frequencies"]["b"] == 1

    def test_empty_folds(self):
        result = measure_explanation_stability({})
        assert result["mean_similarity"] == 0.0
        assert result["feature_frequencies"] == {}
