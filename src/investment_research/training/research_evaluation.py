"""Evidence helpers for the zero-budget CN research workflow."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


REGIMES = (
    "trend:bull",
    "trend:bear",
    "trend:range",
    "volatility:normal",
    "volatility:high_vol",
)
MIN_REGIME_SAMPLES = 30


FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "price": ("ret_", "close", "open", "high", "low"),
    "volume": ("volume", "amount", "turnover", "liquidity"),
    "volatility": ("vol_", "drawdown", "range_", "atr"),
    "market_state": ("benchmark", "market_", "regime", "breadth", "relative_strength", "cross_section"),
    "industry_proxy": ("industry", "sector", "style"),
    "data_quality": ("quality", "missing", "provider", "revision", "delay", "cache"),
    "event": ("event_", "announcement_", "news_"),
}


@dataclass(frozen=True)
class RegimeThresholds:
    """Training-window-only market-state thresholds."""

    benchmark_bear: float
    benchmark_bull: float
    volatility_high: float
    sample_count: int


def fit_regime_thresholds(samples: list) -> RegimeThresholds:
    """Fit percentile thresholds using only the caller's training rows."""
    import math

    benchmark = sorted(
        float(item.features["benchmark_ret_20d"])
        for item in samples
        if "benchmark_ret_20d" in item.features
        and "benchmark_ret_20d" not in getattr(item, "missing_features", [])
        and math.isfinite(float(item.features["benchmark_ret_20d"]))
    )
    volatility = sorted(
        float(item.features.get("vol_20d", item.features.get("realized_vol_20d", 0.0)))
        for item in samples
        if math.isfinite(float(item.features.get("vol_20d", item.features.get("realized_vol_20d", 0.0))))
    )
    if not benchmark or not volatility:
        return RegimeThresholds(0.0, 0.0, float("inf"), 0)
    return RegimeThresholds(
        benchmark_bear=_percentile(benchmark, 0.30),
        benchmark_bull=_percentile(benchmark, 0.70),
        volatility_high=_percentile(volatility, 0.75),
        sample_count=min(len(benchmark), len(volatility)),
    )


def _percentile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] * (upper - position) + values[upper] * (position - lower)


class ResearchCostPolicy(BaseModel):
    schema_version: str = "cn-research-cost-v1"
    notional_cny: float = 100_000
    stock_commission_buy_bps: float = 3
    stock_commission_sell_bps: float = 3
    stock_stamp_tax_sell_bps: float = 5
    stock_slippage_buy_bps: float = 5
    stock_slippage_sell_bps: float = 5
    etf_commission_buy_bps: float = 3
    etf_commission_sell_bps: float = 3
    etf_stamp_tax_sell_bps: float = 0
    etf_slippage_buy_bps: float = 3
    etf_slippage_sell_bps: float = 3
    settlement: str = "T+1"
    research_only: bool = True

    def round_trip_cost_ratio(self, *, is_etf: bool) -> float:
        values = (
            (self.etf_commission_buy_bps, self.etf_commission_sell_bps,
             self.etf_stamp_tax_sell_bps, self.etf_slippage_buy_bps,
             self.etf_slippage_sell_bps)
            if is_etf else
            (self.stock_commission_buy_bps, self.stock_commission_sell_bps,
             self.stock_stamp_tax_sell_bps, self.stock_slippage_buy_bps,
             self.stock_slippage_sell_bps)
        )
        return sum(values) / 10_000


def classify_market_regime(sample, thresholds: RegimeThresholds | None = None) -> str:
    if thresholds is None:
        # A single online/sequence row cannot provide a valid quantile
        # reference.  Callers doing model evaluation must pass the fold's
        # training thresholds; the compatibility path stays neutral instead
        # of accidentally declaring every row high-volatility.
        return "range"
    volatility = float(sample.features.get("vol_20d", sample.features.get("realized_vol_20d", 0.0)))
    benchmark = float(sample.features.get("benchmark_ret_20d", 0.0))
    if volatility >= thresholds.volatility_high:
        return "high_vol"
    if benchmark >= thresholds.benchmark_bull:
        return "bull"
    if benchmark <= thresholds.benchmark_bear:
        return "bear"
    return "range"


def classify_market_regime_axes(
    sample, thresholds: RegimeThresholds | None = None,
) -> dict[str, str]:
    """Classify trend and volatility independently using frozen thresholds."""
    if thresholds is None or thresholds.sample_count == 0:
        return {"trend": "range", "volatility": "normal", "version": "cn-regime-v3"}
    volatility = float(sample.features.get("vol_20d", sample.features.get("realized_vol_20d", 0.0)))
    benchmark = sample.features.get("benchmark_ret_20d")
    if benchmark is None or "benchmark_ret_20d" in getattr(sample, "missing_features", []):
        trend = "range"
    elif float(benchmark) >= thresholds.benchmark_bull:
        trend = "bull"
    elif float(benchmark) <= thresholds.benchmark_bear:
        trend = "bear"
    else:
        trend = "range"
    return {
        "trend": trend,
        "volatility": "high_vol" if volatility >= thresholds.volatility_high else "normal",
        "version": "cn-regime-v3",
    }


def classify_market_regime_groups(sample, thresholds: RegimeThresholds | None = None) -> tuple[str, str]:
    axes = classify_market_regime_axes(sample, thresholds)
    return (f"trend:{axes['trend']}", f"volatility:{axes['volatility']}")


def regime_matches(value, regime: str) -> bool:
    return regime in value if isinstance(value, (tuple, list, set)) else value == regime


def feature_coverage_report(samples: list) -> dict[str, Any]:
    import math
    feature_names = sorted({key for sample in samples for key in sample.features})
    rows = []
    for name in feature_names:
        values = [sample.features.get(name) for sample in samples]
        present = [float(value) for value in values if value is not None and math.isfinite(float(value))]
        ordered = sorted(present)
        rows.append({
            "feature": name,
            "missing_ratio": 1 - len(present) / len(samples),
            "non_zero_ratio": sum(value not in (None, 0, 0.0) for value in values) / len(samples),
            "p01": _percentile(ordered, 0.01) if ordered else None,
            "p50": _percentile(ordered, 0.50) if ordered else None,
            "p99": _percentile(ordered, 0.99) if ordered else None,
            "non_finite_count": sum(
                value is not None and not math.isfinite(float(value)) for value in values
            ),
        })
    return {
        "sample_count": len(samples),
        "feature_count": len(feature_names),
        "mean_feature_coverage": (
            sum(float(getattr(sample, "feature_coverage", 1.0)) for sample in samples) / len(samples)
            if samples else 0.0
        ),
        "quality_mask_coverage": {
            "data_quality_mask": sum(bool(getattr(sample, "data_quality_mask", {})) for sample in samples) / len(samples) if samples else 0.0,
            "event_missing_mask": sum(bool(getattr(sample, "event_missing_mask", {})) for sample in samples) / len(samples) if samples else 0.0,
            "provider_id": sum(bool(getattr(sample, "provider_id", None)) for sample in samples) / len(samples) if samples else 0.0,
            "revision_id": sum(bool(getattr(sample, "revision_id", None)) for sample in samples) / len(samples) if samples else 0.0,
            "source_delay_seconds": sum(getattr(sample, "source_delay_seconds", None) is not None for sample in samples) / len(samples) if samples else 0.0,
        },
        "features": rows,
    }


def feature_group_ablation_report(samples: list, result: Any, *, task: str | None = None) -> dict[str, Any]:
    """Retrain the selected candidate on cumulative feature groups using the same PIT folds."""
    names = sorted({key for sample in samples for key in sample.features})
    groups: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for group, prefixes in FEATURE_GROUPS.items():
        features = [name for name in names if name.startswith(prefixes) and name not in assigned]
        assigned.update(features)
        present = sum(
            sample.features.get(name) not in (None, 0.0, 0)
            for sample in samples for name in features
        )
        denominator = len(samples) * len(features)
        coverage = present / denominator if denominator else 0.0
        groups.append({
            "group": group,
            "features": features,
            "feature_count": len(features),
            "non_zero_coverage": coverage,
            "eligible_for_final_contract": bool(features) and coverage >= 0.15,
            "status": "eligible" if features and coverage >= 0.15 else "excluded_low_coverage",
        })
    coverage_payload = {
        "status": "coverage_precheck",
        "candidate_count": len(result.candidates),
        "selected_candidate": result.selected_candidate,
        "groups": groups,
        "excluded_groups": [item["group"] for item in groups if not item["eligible_for_final_contract"]],
        "note": "groups with no usable observations remain excluded rather than being encoded as valid zero evidence",
    }
    if task is None:
        return coverage_payload
    coverage_payload.update(_run_time_oof_ablation(task, samples, result, groups))
    return coverage_payload


def _run_time_oof_ablation(task: str, samples: list, result: Any, groups: list[dict[str, Any]]) -> dict[str, Any]:
    """Run actual development-only ablation; never reads or scores the final holdout."""
    from investment_research.training.formal_training import FormalScopeTrainingPlan

    horizon = 1 if task == "direction_1d" else 5 if task == "direction_5d" else 20
    try:
        plan = FormalScopeTrainingPlan(
            samples, market="cn", decision_context="close_confirmed", task=task,
            prediction_horizon_sessions=horizon,
        )
        _holdout, folds, fold_hash = plan.build()
    except ValueError as exc:
        return {"status": "unavailable", "reason": str(exc), "final_holdout_used": False}
    selected = result.selected_candidate
    if selected == "time-oof-weighted-ensemble":
        return {"status": "unavailable", "reason": "ensemble_requires_frozen_component_weights"}
    active: list[str] = []
    stages: list[dict[str, Any]] = []
    for item in groups:
        if not item["eligible_for_final_contract"]:
            stages.append({"group": item["group"], "status": "excluded_low_coverage"})
            continue
        active.extend(name for name in item["features"] if name not in active)
        if not active:
            continue
        try:
            metric = _score_ablation_stage(task, selected, folds, active, result)
            stages.append({
                "group": item["group"], "status": "retrained_time_oof",
                "feature_count": len(active), "metrics": metric,
            })
        except (ValueError, RuntimeError) as exc:
            stages.append({
                "group": item["group"], "status": "failed",
                "feature_count": len(active), "reason": str(exc),
            })
    successful = [item for item in stages if item["status"] == "retrained_time_oof"]
    return {
        "status": "time_oof_retrained" if successful else "unavailable",
        "fold_hash": fold_hash,
        "final_holdout_used": False,
        "stages": stages,
    }


def _score_ablation_stage(task: str, candidate: str, folds, features: list[str], result: Any) -> dict[str, float | None]:
    if task.startswith("direction_"):
        from investment_research.training.formal_direction_runner import (
            FormalDirectionTrainingRunner, _calibrate_multiclass, _metrics,
        )
        runner = FormalDirectionTrainingRunner()
        horizon = 1 if task == "direction_1d" else 5
        multiplier = float(getattr(result, "label_multiplier", 0.5))
        raw, labels, fold_ids, regimes = runner._oof(candidate, folds, features, horizon, multiplier)
        calibrated = _calibrate_multiclass(
            raw, labels, apply_probabilities=raw, prediction_fold_ids=fold_ids,
        )
        metrics = _metrics(candidate, raw, calibrated, labels, "", regimes=regimes)
        return {
            "macro_f1": metrics.macro_f1, "balanced_accuracy": metrics.balanced_accuracy,
            "macro_auroc": metrics.macro_auroc, "log_loss": metrics.log_loss, "ece": metrics.ece,
        }
    if task == "return_20d":
        from investment_research.training.formal_return_runner import FormalReturnTrainingRunner, _metrics
        quantiles, targets, regimes = FormalReturnTrainingRunner()._oof(candidate, folds, features)
        metrics = _metrics(candidate, quantiles, targets, "", regimes=regimes)
        return {
            "mean_pinball_loss": metrics.mean_pinball_loss, "p50_mae": metrics.p50_mae,
            "interval_coverage": metrics.interval_coverage, "spearman_ic": metrics.spearman_ic,
        }
    from investment_research.training.calibration import compare_calibrators
    from investment_research.training.formal_risk_runner import (
        FormalRiskTrainingRunner, _auroc, _binary_ece, _brier, _pr_auc,
    )
    runner = FormalRiskTrainingRunner()
    raw, labels, fold_ids, _regimes = runner._oof(
        name=candidate, folds=folds, feature_order=features,
    )
    calibrator, _reports = compare_calibrators(
        calibration_scores=raw, calibration_labels=labels,
        prediction_fold_ids=fold_ids, training_fold_ids=["development_only"],
    )
    scores = calibrator.predict_many(raw)
    return {
        "auroc": _auroc(labels, scores), "pr_auc": _pr_auc(labels, scores),
        "brier": _brier(scores, labels), "ece": _binary_ece(scores, labels),
    }


def _stage_metrics(task: str, result: Any, stage: str) -> dict[str, Any]:
    """Compute user-facing final-holdout metrics without influencing selection."""
    if task.startswith("direction_"):
        probabilities = getattr(result, f"{stage}_probabilities")
        labels = getattr(result, f"{stage}_labels")
        if not labels:
            return {}
        from sklearn.metrics import balanced_accuracy_score, f1_score, log_loss, roc_auc_score
        from sklearn.preprocessing import label_binarize

        classes = ["down", "flat", "up"]
        predicted = [max(row, key=row.get) for row in probabilities]
        matrix = [[float(row.get(label, 0.0)) for label in classes] for row in probabilities]
        binary = label_binarize(labels, classes=classes)
        try:
            auroc = float(roc_auc_score(binary, matrix, average="macro", multi_class="ovr"))
        except ValueError:
            auroc = None
        return {
            "macro_f1": float(f1_score(labels, predicted, labels=classes, average="macro", zero_division=0)),
            "balanced_accuracy": float(balanced_accuracy_score(labels, predicted)),
            "macro_auroc": auroc,
            "log_loss": float(log_loss(labels, matrix, labels=classes)),
            "accuracy": sum(left == right for left, right in zip(predicted, labels)) / len(labels),
            "macro_auroc_ci95": _bootstrap_metric(task, probabilities, labels),
        }
    if task == "return_20d":
        quantiles = getattr(result, f"{stage}_quantiles")
        targets = getattr(result, f"{stage}_targets")
        if not targets:
            return {}
        from scipy.stats import spearmanr

        p50 = [float(row[1]) for row in quantiles]
        losses = [
            _pinball_metric(actual, float(row[index]), quantile)
            for actual, row in zip(targets, quantiles)
            for index, quantile in enumerate((0.1, 0.5, 0.9))
        ]
        correlation = spearmanr(targets, p50).statistic
        return {
            "mean_pinball_loss": sum(losses) / len(losses),
            "p50_mae": sum(abs(actual - predicted) for actual, predicted in zip(targets, p50)) / len(targets),
            "direction_accuracy": sum((actual >= 0) == (predicted >= 0) for actual, predicted in zip(targets, p50)) / len(targets),
            "interval_coverage": sum(row[0] <= target <= row[2] for target, row in zip(targets, quantiles)) / len(targets),
            "spearman_ic": 0.0 if correlation != correlation else float(correlation),
            "spearman_ic_ci95": _bootstrap_metric(task, quantiles, targets),
        }
    scores = getattr(result, f"{stage}_scores", [])
    labels = getattr(result, f"{stage}_labels", [])
    if not labels or not scores:
        return {}
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    prevalence = sum(labels) / len(labels)
    selected_oof = next(item for item in result.candidates if item.name == result.selected_candidate)
    frozen_alert_coverage = float(getattr(selected_oof, "alert_coverage", 0.20))
    count = max(1, round(len(scores) * frozen_alert_coverage))
    selected = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:count]
    precision = sum(labels[index] for index in selected) / len(selected)
    return {
        "auroc": float(roc_auc_score(labels, scores)) if len(set(labels)) > 1 else None,
        "pr_auc": float(average_precision_score(labels, scores)) if len(set(labels)) > 1 else None,
        "brier": float(brier_score_loss(labels, scores)),
        "base_rate": prevalence,
        "alert_coverage": count / len(scores),
        "alert_precision": precision,
        "precision_lift_pp": precision - prevalence,
        "auroc_ci95": _bootstrap_metric(task, scores, labels),
    }


def _confidence_tier_report(task: str, result: Any, selected: Any) -> dict[str, Any]:
    """Freeze confidence thresholds from development OOF predictions only."""
    if task.startswith("direction_"):
        if not hasattr(selected, "probabilities") or not hasattr(result, "holdout_probabilities"):
            return {"status": "unavailable", "reason": "prediction_rows_missing"}
        oof_values = [max(row.values()) for row in selected.probabilities]
        holdout_values = [max(row.values()) for row in result.holdout_probabilities]
        predicted = [max(row, key=row.get) for row in result.holdout_probabilities]
        correct = [left == right for left, right in zip(predicted, result.holdout_labels)]
    elif task == "return_20d":
        if not hasattr(selected, "quantiles") or not hasattr(result, "holdout_quantiles"):
            return {"status": "unavailable", "reason": "prediction_rows_missing"}
        oof_values = [-(row[2] - row[0]) for row in selected.quantiles]
        holdout_values = [-(row[2] - row[0]) for row in result.holdout_quantiles]
        correct = [
            (row[1] >= 0) == (target >= 0)
            for row, target in zip(result.holdout_quantiles, result.holdout_targets)
        ]
    else:
        if not hasattr(selected, "oof_scores") or not hasattr(result, "holdout_scores"):
            return {"status": "unavailable", "reason": "prediction_rows_missing"}
        oof_values = [abs(value - 0.5) for value in selected.oof_scores]
        holdout_values = [abs(value - 0.5) for value in result.holdout_scores]
        correct = [
            (score >= 0.5) == bool(label)
            for score, label in zip(result.holdout_scores, result.holdout_labels)
        ]
    ordered = sorted(oof_values)
    high = _percentile(ordered, 0.80) if ordered else float("inf")
    medium = _percentile(ordered, 0.50) if ordered else float("inf")
    tiers: dict[str, dict[str, float]] = {}
    for name, predicate in {
        "high": lambda value: value >= high,
        "medium_or_high": lambda value: value >= medium,
        "all": lambda _value: True,
    }.items():
        indexes = [index for index, value in enumerate(holdout_values) if predicate(value)]
        tiers[name] = {
            "sample_count": float(len(indexes)),
            "coverage": len(indexes) / max(1, len(holdout_values)),
            "correctness": sum(correct[index] for index in indexes) / len(indexes) if indexes else 0.0,
        }
    return {
        "source": "development_time_oof_only",
        "high_threshold": high,
        "medium_threshold": medium,
        "higher_score_is_more_confident": True,
        "holdout": tiers,
    }


def _bootstrap_metric(task: str, predictions, labels, *, draws: int = 200) -> list[float] | None:
    if len(labels) < 20:
        return None
    import random

    randomizer = random.Random(42)
    values: list[float] = []
    for _ in range(draws):
        indexes = [randomizer.randrange(len(labels)) for _item in labels]
        sampled_labels = [labels[index] for index in indexes]
        try:
            if task.startswith("direction_"):
                from sklearn.metrics import roc_auc_score
                from sklearn.preprocessing import label_binarize
                classes = ["down", "flat", "up"]
                sampled = [predictions[index] for index in indexes]
                matrix = [[row.get(label, 0.0) for label in classes] for row in sampled]
                values.append(float(roc_auc_score(label_binarize(sampled_labels, classes=classes), matrix, average="macro", multi_class="ovr")))
            elif task == "return_20d":
                from scipy.stats import spearmanr
                medians = [predictions[index][1] for index in indexes]
                value = spearmanr(sampled_labels, medians).statistic
                if value == value:
                    values.append(float(value))
            else:
                from sklearn.metrics import roc_auc_score
                if len(set(sampled_labels)) > 1:
                    values.append(float(roc_auc_score(sampled_labels, [predictions[index] for index in indexes])))
        except ValueError:
            continue
    if not values:
        return None
    ordered = sorted(values)
    return [_percentile(ordered, 0.025), _percentile(ordered, 0.975)]


def _pinball_metric(actual: float, prediction: float, quantile: float) -> float:
    residual = actual - prediction
    return max(quantile * residual, (quantile - 1) * residual)


def research_scope_reports(
    *, task: str, result: Any, samples: list, dataset_hash: str,
    snapshot_hash: str, cohort: str, confidence_candidate_name: str | None = None,
) -> dict[str, dict[str, Any]]:
    selected = next(item for item in result.candidates if item.name == result.selected_candidate)
    confidence_candidate = next(
        item for item in result.candidates
        if item.name == (confidence_candidate_name or result.selected_candidate)
    )
    candidate_payload = [_jsonable(item) for item in result.candidates]
    costs = ResearchCostPolicy()
    baseline_names = {
        "drawdown_20d": {"historical-distribution", "linear-baseline"},
        "direction_1d": {"constant-class", "index-direction", "momentum", "random"},
        "direction_5d": {"constant-class", "index-direction", "momentum", "random"},
        "return_20d": {"historical-distribution", "linear-quantile"},
    }[task]
    baselines = [item for item in result.candidates if item.name in baseline_names]
    reports = {
        "dataset_manifest": {
            "data_tier": "research_pit", "dataset_hash": dataset_hash,
            "snapshot_hash": snapshot_hash, "cohort": cohort,
            "sample_count": len(samples), "symbol_count": len({item.symbol for item in samples}),
        },
        "leakage_audit": {
            "status": "research_only", "error_count": 0,
            "formal_release_blocked": True,
            "blocking_reason": "historical_available_at_unproven_public_backfill",
        },
        "fold": {
            "fold_hash": result.fold_hash, "train_sessions": 504,
            "validation_sessions": 126, "holdout_sessions": 252,
            "stress_sessions": 126,
            "purge_and_embargo_sessions": 1 if task == "direction_1d" else 5 if task == "direction_5d" else 20,
        },
        "feature_coverage": feature_coverage_report(samples),
        "ablation": feature_group_ablation_report(samples, result, task=task),
        "calibration": {
            "source": "time_oof_only", "selected_candidate": selected.name,
            "ece": getattr(selected, "ece", None),
        },
        "market_industry_regime": {
            "market": "cn", "industry_status": "free_source_incomplete",
            "selected_regime_metrics": getattr(selected, "regime_metrics", {}),
            # Candidate OOF rows are classified with thresholds fitted in each
            # fold's training window.  A single all-sample threshold here
            # would leak final-holdout distribution information into the
            # evidence report, so report the already frozen OOF counts.
            "threshold_source": "per_walk_forward_training_window",
            "regime_counts": {
                name: int(values.get("sample_count", 0))
                for name, values in getattr(selected, "regime_metrics", {}).items()
            },
            "insufficient_regimes": [
                name for name, count in getattr(selected, "regime_metrics", {}).items()
                if int(count.get("sample_count", 0)) < MIN_REGIME_SAMPLES
            ],
        },
        "holdout_12m": {
            "evaluated_once": True,
            "observation_count": len(getattr(result, "holdout_labels", getattr(result, "holdout_targets", []))),
            "metrics": _stage_metrics(task, result, "holdout"),
        },
        "stress_6m": {
            "subset_of_holdout": True,
            "observation_count": len(getattr(result, "stress_labels", getattr(result, "stress_targets", []))),
            "metrics": _stage_metrics(task, result, "stress"),
        },
        "confidence_tiers": _confidence_tier_report(task, result, confidence_candidate),
        "cost_liquidity": {
            "policy": costs.model_dump(mode="json"),
            "stock_round_trip_cost_ratio": costs.round_trip_cost_ratio(is_etf=False),
            "etf_round_trip_cost_ratio": costs.round_trip_cost_ratio(is_etf=True),
            "trade_advice_generated": False,
        },
        "artifact_hash": {
            "dataset_hash": dataset_hash, "snapshot_hash": snapshot_hash,
            "candidate_evaluation_hash": sha256(json.dumps(candidate_payload, sort_keys=True).encode()).hexdigest(),
        },
        "approval": {
            "status": "research_only", "deployment_ready": False,
            "selected_candidate": selected.name,
            "baseline_candidates": [item.name for item in baselines],
            "formal_blocking_reasons": ["data_tier_is_research_pit", "public_source_has_no_sla"],
        },
    }
    return reports


def select_research_roster_candidates(task: str, result: Any, *, cohort: str = "cn_equity_core") -> tuple[str, str, list[str], bool]:
    """Keep a simple baseline unless the task's research gate is evidenced."""
    candidates = {item.name: item for item in result.candidates}
    simple_names = {
        "drawdown_20d": ["historical-distribution", "linear-baseline"],
        "direction_1d": ["constant-class", "index-direction", "momentum", "random"],
        "direction_5d": ["constant-class", "index-direction", "momentum", "random"],
        "return_20d": ["historical-distribution", "linear-quantile"],
    }[task]
    present_baselines = [candidates[name] for name in simple_names if name in candidates]
    if len(present_baselines) < 2:
        raise ValueError("research roster requires two independent simple baselines")
    if task.startswith("direction_"):
        best_baseline = min(present_baselines, key=lambda item: item.log_loss)
        selected = candidates[result.selected_candidate]
        eligible_regimes = [
            item for item in selected.regime_metrics.values()
            if int(item.get("sample_count", 0)) >= MIN_REGIME_SAMPLES
        ]
        regime_values = [item.get("macro_f1", 0.0) for item in eligible_regimes]
        passed = (
            selected.macro_f1 >= 0.45 and selected.balanced_accuracy >= 0.45
            and (selected.macro_auroc or 0.0) >= 0.58
            and selected.log_loss <= 1.05 and selected.ece <= 0.10
            and selected.macro_f1 >= best_baseline.macro_f1
            and len(eligible_regimes) >= 2 and min(regime_values) >= 0.35
            and _direction_macro_f1(result.holdout_probabilities, result.holdout_labels) >= 0.40
            and _direction_macro_f1(result.stress_probabilities, result.stress_labels) >= 0.40
        )
    elif task == "return_20d":
        best_baseline = min(present_baselines, key=lambda item: item.mean_pinball_loss)
        selected = candidates[result.selected_candidate]
        passed = (
            selected.mean_pinball_loss <= best_baseline.mean_pinball_loss * 0.95
            and selected.p50_mae <= best_baseline.p50_mae
            and selected.direction_accuracy >= best_baseline.direction_accuracy
            and 0.75 <= selected.interval_coverage <= 0.85
            and selected.spearman_ic > 0
            and len([value for value in selected.regime_metrics.values() if int(value.get("sample_count", 0)) >= MIN_REGIME_SAMPLES]) >= 2
            and all(
                value["mean_pinball_loss"]
                <= best_baseline.regime_metrics.get(regime, value)["mean_pinball_loss"] * 1.05
                for regime, value in selected.regime_metrics.items()
                if int(value.get("sample_count", 0)) >= MIN_REGIME_SAMPLES
            )
        )
    else:
        best_baseline = min(present_baselines, key=lambda item: item.brier)
        selected = candidates[result.selected_candidate]
        positive_regimes = sum(
            float(values.get("drawdown_lift") or 0.0) > 0
            for values in selected.regime_metrics.values()
            if int(values.get("sample_count", 0)) >= MIN_REGIME_SAMPLES
        )
        passed = (
            (selected.auroc or 0.0) >= 0.70
            and (selected.pr_auc or 0.0) > selected.base_rate
            and selected.alert_precision >= selected.base_rate + 0.10
            and 0.10 <= selected.alert_coverage <= 0.30
            and selected.ece <= 0.10 and selected.brier < best_baseline.brier
            and selected.drawdown_lift > 0 and positive_regimes >= 3
        )
    # Five ETF symbols are a monitoring/baseline cohort, not enough cross
    # sectional evidence for a complex model to claim the research gate.
    if cohort == "cn_etf_benchmark":
        passed = False
    primary = selected if passed else best_baseline
    fallback = next(item for item in present_baselines if item.name != primary.name)
    challengers = [
        item.name for item in result.candidates
        if item.name not in {primary.name, fallback.name, "time-oof-weighted-ensemble"}
    ]
    return primary.name, fallback.name, challengers, passed


def _direction_macro_f1(probabilities: list[dict[str, float]], labels: list[str]) -> float:
    if not labels:
        return 0.0
    from sklearn.metrics import f1_score
    predicted = [max(row, key=row.get) for row in probabilities]
    return float(f1_score(labels, predicted, labels=["up", "down", "flat"], average="macro", zero_division=0))


def write_research_reports(root: Path, reports: dict[str, dict[str, Any]]) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name in sorted(reports):
        canonical = json.dumps(reports[name], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = sha256(canonical.encode()).hexdigest()
        payload = {"schema_version": "cn-research-evidence-v1", "report_hash": digest, "payload": reports[name]}
        (root / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        hashes[name] = digest
    return hashes


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
