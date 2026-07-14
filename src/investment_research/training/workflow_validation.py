"""Workflow validation modules for training governance.

This module provides three core workflow validation components:
1. Observation pool ranking – sort and filter the pool of risk observations.
2. Risk alert lead time – compute how early alerts are raised relative to events.
3. Explanation stability – measure consistency of feature contributions across folds.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from investment_research.training.models import (
    FeatureContribution,
    FoldMetric,
    PredictionExplanation,
    RiskBucketObservation,
    WalkForwardFoldResult,
)


def rank_observation_pool(
    observations: list[RiskBucketObservation],
    *,
    top_k: int | None = 50,
    min_score: float = 0.0,
    max_alerted_days_ago: int | None = 30,
) -> list[RiskBucketObservation]:
    """Rank the observation pool by score and apply filters.

    Args:
        observations: Raw observations from a model.
        top_k: Return at most this many observations (None for all).
        min_score: Minimum risk score threshold.
        max_alerted_days_ago: If provided, only keep observations alerted within
            this many days from now (UTC). Observations without alerted_at are kept.

    Returns:
        Sorted list of observations (highest score first) after filtering.
    """
    now = datetime.now().astimezone()

    filtered = []
    for obs in observations:
        if obs.score < min_score:
            continue
        if max_alerted_days_ago is not None and obs.alerted_at is not None:
            days_ago = (now - obs.alerted_at).days
            if days_ago > max_alerted_days_ago:
                continue
        filtered.append(obs)

    filtered.sort(key=lambda o: o.score, reverse=True)
    if top_k is not None:
        filtered = filtered[:top_k]
    return filtered


def compute_risk_alert_lead_time(
    observations: list[RiskBucketObservation],
    *,
    event_threshold: float = 0.1,
) -> dict[str, Any]:
    """Compute lead‑time statistics for alerts that preceded risk events.

    For each observation where both alerted_at and risk_event_at are present,
    compute the time difference (lead time) in days. If the event occurred before
    the alert (negative lead time), treat it as a missed alert.

    Args:
        observations: Observations with both alerted_at and risk_event_at.
        event_threshold: Minimum future_max_drawdown_20d value to consider as a
            true risk event.

    Returns:
        Dict with:
            - 'n_events': total observations with risk_event_at
            - 'n_alerts': total observations with alerted_at
            - 'n_matched': observations with both timestamps
            - 'lead_times_days': list of lead times (positive if alert before event)
            - 'mean_lead_days': average lead time (only for positive leads)
            - 'median_lead_days': median lead time (only for positive leads)
            - 'missed_count': count of events where alert came after event
            - 'missed_ratio': missed_count / n_matched
    """
    matched = [
        obs
        for obs in observations
        if obs.alerted_at is not None
        and obs.risk_event_at is not None
        and obs.future_max_drawdown_20d >= event_threshold
    ]

    lead_times = []
    missed = 0
    for obs in matched:
        delta = (obs.risk_event_at - obs.alerted_at).total_seconds() / 86400.0
        lead_times.append(delta)
        if delta < 0:
            missed += 1

    positive_leads = [lt for lt in lead_times if lt > 0]
    return {
        "n_events": sum(1 for o in observations if o.risk_event_at is not None),
        "n_alerts": sum(1 for o in observations if o.alerted_at is not None),
        "n_matched": len(matched),
        "lead_times_days": lead_times,
        "mean_lead_days": sum(positive_leads) / len(positive_leads) if positive_leads else 0.0,
        "median_lead_days": sorted(positive_leads)[len(positive_leads) // 2] if positive_leads else 0.0,
        "missed_count": missed,
        "missed_ratio": missed / len(matched) if matched else 0.0,
    }


def measure_explanation_stability(
    fold_top_features: dict[str, list[str]],
) -> dict[str, Any]:
    """Measure consistency of feature contributions across walk‑forward folds.

    Compute the Jaccard similarity of top‑N feature sets between consecutive
    folds and the overall frequency of each feature appearing in any fold.

    Args:
        fold_top_features: Mapping of fold_id to list of top‑N feature names,
            where features are ordered by importance (most important first).

    Returns:
        Dict with:
            - 'fold_top_features': list of (fold_id, [feature_names]) for each fold
            - 'pairwise_similarity': list of Jaccard similarities between consecutive folds
            - 'mean_similarity': average pairwise similarity
            - 'feature_frequencies': dict {feature_name: count across all folds}
    """
    fold_list = list(fold_top_features.items())
    results_fold_features: list[tuple[str, list[str]]] = list(fold_list)

    # Pairwise Jaccard similarity
    similarities: list[float] = []
    for i in range(len(results_fold_features) - 1):
        set_a = set(results_fold_features[i][1])
        set_b = set(results_fold_features[i + 1][1])
        if not set_a and not set_b:
            sim = 1.0
        elif not set_a or not set_b:
            sim = 0.0
        else:
            sim = len(set_a & set_b) / len(set_a | set_b)
        similarities.append(sim)

    # Feature frequencies
    feat_freq: dict[str, int] = defaultdict(int)
    for _fold_id, feats in results_fold_features:
        for feat in feats:
            feat_freq[feat] += 1

    return {
        "fold_top_features": results_fold_features,
        "pairwise_similarity": similarities,
        "mean_similarity": sum(similarities) / len(similarities) if similarities else 0.0,
        "feature_frequencies": dict(feat_freq),
    }
