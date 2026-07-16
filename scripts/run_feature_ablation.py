#!/usr/bin/env python3
"""Run a reproducible, PIT-safe evidence matrix without publishing a model."""
from __future__ import annotations

import json
import math
import pickle
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_research.training.trust_framework import (  # noqa: E402
    EVENT_FEATURES, PRICE_FEATURES, PRIMARY_TASK, REFERENCE_FEATURES,
    TRUST_FRAMEWORK_VERSION, confidence_interval, gate_eligible, sample_snapshot_hash,
)


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value)) and abs(float(value)) <= 1_000
    except (TypeError, ValueError):
        return False


def _splits(samples: list) -> list[tuple[list, list]]:
    dates = sorted({sample.as_of_date for sample in samples})
    # Four expanding, date-aligned folds shared by every experiment variant.
    boundaries = [dates[int(len(dates) * fraction / 5)] for fraction in range(1, 5)]
    output = []
    for index in range(len(boundaries) - 1):
        train_end, valid_end = boundaries[index], boundaries[index + 1]
        train = [s for s in samples if s.as_of_date < train_end]
        valid = [s for s in samples if train_end <= s.as_of_date < valid_end]
        if train and valid:
            output.append((train, valid))
    return output


def _ece(labels: list[int], scores: list[float], buckets: int = 10) -> float:
    if not labels:
        return 0.0
    total = len(labels)
    return sum(
        abs(sum(labels[i::buckets]) / len(labels[i::buckets]) - sum(scores[i::buckets]) / len(scores[i::buckets])) * len(labels[i::buckets]) / total
        for i in range(buckets) if labels[i::buckets]
    )


def _metrics(samples: list, labels: list[int], scores: list[float], eligible: list[bool]) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    bucket = order[:max(1, len(order) // 5)]
    drawdowns = [float(samples[i].labels.future_max_drawdown_20d) for i in range(len(samples))]
    top_mean = sum(drawdowns[i] for i in bucket) / len(bucket)
    overall = sum(drawdowns) / len(drawdowns)
    model_alerts = [i for i, score in enumerate(scores) if score >= 0.5]
    gated_alerts = [i for i in model_alerts if eligible[i]]
    return {
        "auc_roc": round(roc_auc_score(labels, scores), 6),
        "pr_auc": round(average_precision_score(labels, scores), 6),
        "brier": round(brier_score_loss(labels, scores), 6),
        "ece": round(_ece(labels, scores), 6),
        "top_bucket_alert_precision": round(sum(labels[i] for i in bucket) / len(bucket), 6),
        "drawdown_lift": round(overall - top_mean, 6),
        "coverage_rate": round(len(gated_alerts) / len(labels), 6),
        "model_alert_rate": round(len(model_alerts) / len(labels), 6),
        "gate_rejection_rate": round(1 - len(gated_alerts) / max(1, len(model_alerts)), 6),
    }


def _run(samples: list, features: list[str], model_name: str) -> dict:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    folds, missing = [], 0
    for fold_id, (train, valid) in enumerate(_splits(samples), start=1):
        usable_train = [s for s in train if all(_finite(s.features.get(f)) for f in features)]
        usable_valid = [s for s in valid if all(_finite(s.features.get(f)) for f in features)]
        missing += len(train) + len(valid) - len(usable_train) - len(usable_valid)
        x_train = [[float(s.features[f]) for f in features] for s in usable_train]
        x_valid = [[float(s.features[f]) for f in features] for s in usable_valid]
        y_train = [int(s.labels.future_max_drawdown_20d <= -0.08) for s in usable_train]
        y_valid = [int(s.labels.future_max_drawdown_20d <= -0.08) for s in usable_valid]
        if len(set(y_train)) < 2 or len(set(y_valid)) < 2:
            continue
        model = (LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
                 if model_name == "linear-baseline" else RandomForestClassifier(n_estimators=250, min_samples_leaf=20, class_weight="balanced", random_state=42, n_jobs=-1))
        model.fit(x_train, y_train)
        scores = list(model.predict_proba(x_valid)[:, 1])
        fold = _metrics(usable_valid, y_valid, scores, [gate_eligible(s) for s in usable_valid])
        fold.update({"fold": fold_id, "train_count": len(usable_train), "validation_count": len(usable_valid)})
        folds.append(fold)
    summary = {name: confidence_interval([fold[name] for fold in folds]) for name in ("auc_roc", "pr_auc", "brier", "ece", "top_bucket_alert_precision", "drawdown_lift", "coverage_rate", "gate_rejection_rate")}
    return {"features": features, "model": model_name, "folds": folds, "summary": summary, "invalid_or_missing_feature_values": missing}


def main() -> int:
    results = json.loads((ROOT / "output" / "results.json").read_text(encoding="utf-8"))
    with (ROOT / "temp" / "all_samples.pkl").open("rb") as handle:
        samples = pickle.load(handle).get("samples", [])
    samples = sorted([s for s in samples if getattr(s.labels, PRIMARY_TASK) is not None], key=lambda s: (s.as_of_date, s.symbol))
    groups = {"no_event": PRICE_FEATURES, "with_event": PRICE_FEATURES + EVENT_FEATURES, "with_event_reference": PRICE_FEATURES + EVENT_FEATURES + REFERENCE_FEATURES}
    current_hash = sample_snapshot_hash(samples)
    if current_hash != results.get("sample_snapshot_hash"):
        raise RuntimeError("Ablation sample snapshot does not match the authoritative training run")
    report = {"schema_version": "trusted-risk-gate-experiments-v1", "framework_version": TRUST_FRAMEWORK_VERSION, "training_run_id": results.get("run_label"), "target_name": PRIMARY_TASK, "sample_snapshot_hash": current_hash, "feature_contract_version": results.get("feature_contract_version"), "data_version": results.get("data_source"), "sample_count": len(samples), "split_strategy": "shared_expanding_date_folds", "experiments": {}, "gate_comparison": {"description": "Offline PIT proxy; live Judge additionally evaluates freshness, provenance and deployment state."}}
    for group_name, features in groups.items():
        report["experiments"][group_name] = {model: _run(samples, features, model) for model in ("linear-baseline", "random-forest")}
    for market in ("us", "cn"):
        subset = [s for s in samples if getattr(s.market, "value", s.market) == market]
        report["experiments"][f"single_market_{market}"] = {"random-forest": _run(subset, groups["with_event"], "random-forest")}
    report["experiments"]["multi_market"] = {"random-forest": _run(samples, groups["with_event"], "random-forest")}
    event_auc = report["experiments"]["with_event"]["random-forest"]["summary"]["auc_roc"]["mean"]
    no_event_auc = report["experiments"]["no_event"]["random-forest"]["summary"]["auc_roc"]["mean"]
    report["summary"] = {"event_auc_delta_vs_no_event": None if event_auc is None or no_event_auc is None else round(event_auc - no_event_auc, 6), "publication_rule": "Do not promote a model from this ablation; promotion remains governed by the full walk-forward approval policy."}
    (ROOT / "audits" / "trusted_risk_gate_experiments.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Wrote audits/trusted_risk_gate_experiments.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
