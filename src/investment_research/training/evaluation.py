from __future__ import annotations

from datetime import timedelta

from investment_research.training.models import ClassificationEvaluation, RiskBucketObservation


class RiskBucketEvaluation(ClassificationEvaluation):
    top_bucket_size: int
    top_bucket_mean_drawdown: float
    overall_mean_drawdown: float
    drawdown_lift: float
    alert_precision: float | None = None
    average_lead_days: float | None = None


def evaluate_risk_bucket_usefulness(
    observations: list[RiskBucketObservation],
    *,
    top_fraction: float = 0.2,
    event_drawdown_threshold: float = -0.08,
    higher_is_risk: bool = False,
) -> RiskBucketEvaluation:
    if not observations:
        raise ValueError("observations must not be empty")
    if not 0 < top_fraction <= 1:
        raise ValueError("top_fraction must be within (0, 1]")

    ordered = sorted(observations, key=lambda item: item.score, reverse=True)
    top_bucket_size = max(1, int(len(ordered) * top_fraction))
    top_bucket = ordered[:top_bucket_size]

    overall_mean_drawdown = sum(item.future_max_drawdown_20d for item in ordered) / len(ordered)
    top_mean_drawdown = sum(item.future_max_drawdown_20d for item in top_bucket) / len(top_bucket)

    precision_hits = [
        item
        for item in top_bucket
        if (
            item.future_max_drawdown_20d >= event_drawdown_threshold
            if higher_is_risk
            else item.future_max_drawdown_20d <= event_drawdown_threshold
        )
    ]
    alert_precision = len(precision_hits) / len(top_bucket) if top_bucket else None

    lead_days: list[float] = []
    for item in top_bucket:
        if item.alerted_at is None or item.risk_event_at is None:
            continue
        lead_days.append((item.risk_event_at - item.alerted_at) / timedelta(days=1))

    labels = [
        1 if (
            item.future_max_drawdown_20d >= event_drawdown_threshold
            if higher_is_risk
            else item.future_max_drawdown_20d <= event_drawdown_threshold
        ) else 0
        for item in observations
    ]
    scores = [item.score for item in observations]
    auc_roc = compute_auc_roc(labels, scores)
    pr_auc = compute_pr_auc(labels, scores)
    brier = compute_brier_score(labels, scores)
    ece = compute_expected_calibration_error(labels, scores, bucket_count=10)

    return RiskBucketEvaluation(
        top_bucket_size=top_bucket_size,
        top_bucket_mean_drawdown=top_mean_drawdown,
        overall_mean_drawdown=overall_mean_drawdown,
        drawdown_lift=(
            top_mean_drawdown - overall_mean_drawdown
            if higher_is_risk
            else overall_mean_drawdown - top_mean_drawdown
        ),
        alert_precision=alert_precision,
        average_lead_days=None if not lead_days else sum(lead_days) / len(lead_days),
        auc_roc=auc_roc,
        pr_auc=pr_auc,
        brier_score=brier,
        expected_calibration_error=ece,
        top_bucket_lift=(
            top_mean_drawdown - overall_mean_drawdown
            if higher_is_risk
            else overall_mean_drawdown - top_mean_drawdown
        ),
        top_bucket_precision=alert_precision,
    )


def compute_auc_roc(labels: list[int], scores: list[float]) -> float | None:
    if len(labels) != len(scores) or not labels:
        return None
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    ordered = sorted(zip(scores, labels), key=lambda item: item[0])
    rank_sum = 0.0
    for rank, (_, label) in enumerate(ordered, start=1):
        if label == 1:
            rank_sum += rank
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def compute_pr_auc(labels: list[int], scores: list[float]) -> float | None:
    if len(labels) != len(scores) or not labels:
        return None
    positives = sum(labels)
    if positives == 0:
        return None
    ordered = sorted(zip(scores, labels), key=lambda item: item[0], reverse=True)
    tp = 0
    fp = 0
    previous_recall = 0.0
    area = 0.0
    for _, label in ordered:
        if label == 1:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / positives
        area += precision * max(0.0, recall - previous_recall)
        previous_recall = recall
    return area


def compute_brier_score(labels: list[int], scores: list[float]) -> float | None:
    if len(labels) != len(scores) or not labels:
        return None
    return sum((label - score) ** 2 for label, score in zip(labels, scores)) / len(labels)


def compute_expected_calibration_error(labels: list[int], scores: list[float], *, bucket_count: int = 10) -> float | None:
    if len(labels) != len(scores) or not labels:
        return None
    bucket_count = max(2, bucket_count)
    buckets: list[list[tuple[int, float]]] = [[] for _ in range(bucket_count)]
    for label, score in zip(labels, scores):
        index = min(bucket_count - 1, int(score * bucket_count))
        buckets[index].append((label, score))
    total = len(labels)
    error = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        avg_label = sum(label for label, _ in bucket) / len(bucket)
        avg_score = sum(score for _, score in bucket) / len(bucket)
        error += abs(avg_label - avg_score) * (len(bucket) / total)
    return error
