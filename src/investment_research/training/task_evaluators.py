"""Task-specific evaluators for risk prediction tasks.

Provides specialized evaluation metrics beyond generic classification,
tailored to drawdown severity, regime-aware performance, and time-to-event
analysis.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from investment_research.training.models import (
    ClassificationEvaluation,
    RiskBucketObservation,
)


class DrawdownSeverityEvaluation(ClassificationEvaluation):
    """Evaluation focused on drawdown severity ranking and early warning."""

    severity_correlation: float | None
    """Pearson correlation between predicted score and actual drawdown severity."""

    top_decile_mean_drawdown: float
    """Mean drawdown in the top 10% highest-risk predictions."""

    bottom_decile_mean_drawdown: float
    """Mean drawdown in the bottom 10% lowest-risk predictions."""

    severity_lift: float
    """Difference between top and bottom decile mean drawdowns."""

    early_warning_ratio: float | None
    """Proportion of severe events (drawdown <= -0.10) captured in top 20%."""

    false_positive_rate: float
    """Proportion of top predictions that were false alarms (drawdown > -0.05)."""


class RegimeAwareEvaluation(ClassificationEvaluation):
    """Evaluation split by market regime (bull, bear, volatile)."""

    bull_market_auc: float | None
    bear_market_auc: float | None
    volatile_market_auc: float | None

    regime_consistency: float
    """Ratio of worst to best regime AUC (higher = more consistent)."""

    regime_detection_gap: float | None
    """Difference between best and worst regime AUC."""


class TimeToEventEvaluation(ClassificationEvaluation):
    """Evaluation for time-to-event (lead time) prediction."""

    median_lead_days: float | None
    mean_lead_days: float | None
    lead_time_std: float | None

    early_capture_rate: float | None
    """Proportion of events captured at least 5 days in advance."""

    late_capture_rate: float | None
    """Proportion of events captured within 2 days of event."""

    false_alert_lead_time: float | None
    """Average lead time of false positive alerts."""


def evaluate_drawdown_severity(
    observations: list[RiskBucketObservation],
    *,
    top_fraction: float = 0.1,
    bottom_fraction: float = 0.1,
    severe_threshold: float = -0.10,
    false_alarm_threshold: float = -0.05,
) -> DrawdownSeverityEvaluation:
    """Evaluate ranking quality by drawdown severity."""
    if not observations:
        raise ValueError("observations must not be empty")

    ordered = sorted(observations, key=lambda item: item.score, reverse=True)
    n = len(ordered)

    # Top and bottom deciles
    top_n = max(1, int(n * top_fraction))
    bottom_n = max(1, int(n * bottom_fraction))
    top = ordered[:top_n]
    bottom = ordered[-bottom_n:]

    top_mean = sum(item.future_max_drawdown_20d for item in top) / len(top)
    bottom_mean = sum(item.future_max_drawdown_20d for item in bottom) / len(bottom)

    # Severity correlation
    scores = [item.score for item in ordered]
    drawdowns = [item.future_max_drawdown_20d for item in ordered]
    if len(scores) >= 2:
        import numpy as np
        severity_corr = float(np.corrcoef(scores, drawdowns)[0, 1])
    else:
        severity_corr = None

    # Early warning ratio
    severe_events = [item for item in ordered if item.future_max_drawdown_20d <= severe_threshold]
    severe_in_top = [item for item in top if item.future_max_drawdown_20d <= severe_threshold]
    early_warning_ratio = len(severe_in_top) / len(severe_events) if severe_events else None

    # False positive rate
    false_positives = sum(
        1 for item in top
        if item.future_max_drawdown_20d > false_alarm_threshold
    )
    false_positive_rate = false_positives / len(top) if top else 0.0

    # Generic classification metrics
    labels = [1 if item.future_max_drawdown_20d <= -0.08 else 0 for item in ordered]
    auc_roc = compute_auc_roc(labels, scores)
    pr_auc = compute_pr_auc(labels, scores)
    brier = compute_brier_score(labels, scores)
    ece = compute_expected_calibration_error(labels, scores)

    return DrawdownSeverityEvaluation(
        severity_correlation=severity_corr,
        top_decile_mean_drawdown=top_mean,
        bottom_decile_mean_drawdown=bottom_mean,
        severity_lift=top_mean - bottom_mean,
        early_warning_ratio=early_warning_ratio,
        false_positive_rate=false_positive_rate,
        auc_roc=auc_roc,
        pr_auc=pr_auc,
        brier_score=brier,
        expected_calibration_error=ece,
        top_bucket_lift=top_mean - sum(drawdowns) / n,
        top_bucket_precision=len(severe_in_top) / len(top) if top else None,
    )


def evaluate_regime_aware(
    observations: list[RiskBucketObservation],
    regime_labels: list[Literal["bull", "bear", "volatile"]],
) -> RegimeAwareEvaluation:
    """Evaluate performance across market regimes."""
    if len(observations) != len(regime_labels):
        raise ValueError("observations and regime_labels must have same length")

    regime_groups: dict[str, list[RiskBucketObservation]] = {
        "bull": [],
        "bear": [],
        "volatile": [],
    }
    for obs, regime in zip(observations, regime_labels):
        if regime in regime_groups:
            regime_groups[regime].append(obs)

    aucs = {}
    for regime, group in regime_groups.items():
        if len(group) < 10:
            aucs[regime] = None
            continue
        labels = [1 if obs.future_max_drawdown_20d <= -0.08 else 0 for obs in group]
        scores = [obs.score for obs in group]
        aucs[regime] = compute_auc_roc(labels, scores)

    # Overall metrics
    all_labels = [1 if obs.future_max_drawdown_20d <= -0.08 else 0 for obs in observations]
    all_scores = [obs.score for obs in observations]
    auc_roc = compute_auc_roc(all_labels, all_scores)
    pr_auc = compute_pr_auc(all_labels, all_scores)
    brier = compute_brier_score(all_labels, all_scores)
    ece = compute_expected_calibration_error(all_labels, all_scores)

    # Regime consistency
    valid_aucs = [auc for auc in aucs.values() if auc is not None]
    if valid_aucs:
        worst = min(valid_aucs)
        best = max(valid_aucs)
        regime_consistency = worst / best if best != 0 else 0.0
        regime_gap = best - worst
    else:
        regime_consistency = 0.0
        regime_gap = None

    return RegimeAwareEvaluation(
        bull_market_auc=aucs.get("bull"),
        bear_market_auc=aucs.get("bear"),
        volatile_market_auc=aucs.get("volatile"),
        regime_consistency=regime_consistency,
        regime_detection_gap=regime_gap,
        auc_roc=auc_roc,
        pr_auc=pr_auc,
        brier_score=brier,
        expected_calibration_error=ece,
        top_bucket_lift=None,
        top_bucket_precision=None,
    )


def evaluate_time_to_event(
    observations: list[RiskBucketObservation],
    *,
    event_threshold: float = -0.08,
    early_cutoff_days: int = 5,
    late_cutoff_days: int = 2,
) -> TimeToEventEvaluation:
    """Evaluate lead time prediction quality."""
    events = [
        obs for obs in observations
        if obs.future_max_drawdown_20d <= event_threshold
        and obs.alerted_at is not None
        and obs.risk_event_at is not None
    ]
    if not events:
        return TimeToEventEvaluation(
            median_lead_days=None,
            mean_lead_days=None,
            lead_time_std=None,
            early_capture_rate=None,
            late_capture_rate=None,
            false_alert_lead_time=None,
            auc_roc=None,
            pr_auc=None,
            brier_score=None,
            expected_calibration_error=None,
            top_bucket_lift=None,
            top_bucket_precision=None,
        )

    lead_times = [
        (obs.risk_event_at - obs.alerted_at) / timedelta(days=1)
        for obs in events
    ]
    import numpy as np
    median_lead = float(np.median(lead_times))
    mean_lead = float(np.mean(lead_times))
    std_lead = float(np.std(lead_times))

    early_capture = sum(1 for lt in lead_times if lt >= early_cutoff_days) / len(lead_times)
    late_capture = sum(1 for lt in lead_times if lt <= late_cutoff_days) / len(lead_times)

    # False alert lead time
    false_alerts = [
        obs for obs in observations
        if obs.future_max_drawdown_20d > -0.05
        and obs.alerted_at is not None
        and obs.risk_event_at is not None
    ]
    false_lead = None
    if false_alerts:
        false_lead_times = [
            (obs.risk_event_at - obs.alerted_at) / timedelta(days=1)
            for obs in false_alerts
        ]
        false_lead = float(np.mean(false_lead_times))

    # Generic metrics
    all_labels = [1 if obs.future_max_drawdown_20d <= event_threshold else 0 for obs in observations]
    all_scores = [obs.score for obs in observations]
    auc_roc = compute_auc_roc(all_labels, all_scores)
    pr_auc = compute_pr_auc(all_labels, all_scores)
    brier = compute_brier_score(all_labels, all_scores)
    ece = compute_expected_calibration_error(all_labels, all_scores)

    return TimeToEventEvaluation(
        median_lead_days=median_lead,
        mean_lead_days=mean_lead,
        lead_time_std=std_lead,
        early_capture_rate=early_capture,
        late_capture_rate=late_capture,
        false_alert_lead_time=false_lead,
        auc_roc=auc_roc,
        pr_auc=pr_auc,
        brier_score=brier,
        expected_calibration_error=ece,
        top_bucket_lift=None,
        top_bucket_precision=None,
    )


# Reuse existing evaluation utilities
from investment_research.training.evaluation import (
    compute_auc_roc,
    compute_brier_score,
    compute_expected_calibration_error,
    compute_pr_auc,
)
