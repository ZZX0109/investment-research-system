"""Long-horizon cross-sectional baseline pipeline.

The pipeline is deliberately small and auditable: it builds observations from
the canonical ``TrainingSample`` contract, uses purged walk-forward folds,
keeps the final holdout untouched, and reports portfolio-oriented ranking
metrics. It is a baseline stage, not an approval or deployment mechanism.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from math import sqrt
import os
from pathlib import Path
from typing import Any, Iterable

from investment_research.training.long_term_config import LongTermTrainingConfig
from investment_research.training.models import TrainingSample
from investment_research.training.validation import build_period_walk_forward_folds


@dataclass(frozen=True)
class LongTermObservation:
    symbol: str
    decision_date: date
    industry_key: str | None
    features: dict[str, float]
    target: float
    regime: str = "unknown"
    feature_coverage: float = 1.0
    data_quality_status: str = "passed"


def build_long_term_observations(
    samples: Iterable[TrainingSample],
    *,
    target: str,
    minimum_feature_coverage: float = 0.98,
    snapshot_frequency: str = "quarterly",
) -> list[LongTermObservation]:
    """Filter only mature, finite, cross-sectional observations.

    Unknown targets and immature labels fail closed. Missing feature values are
    not silently converted to zero; callers must impute using a training-fold
    policy before fitting.
    """
    sample_list = list(samples)
    if target in {"future_quality_persistence_4q", "future_quality_persistence_8q"}:
        sample_list = attach_future_quality_labels(sample_list)
    candidates: dict[tuple[str, date], LongTermObservation] = {}
    long_term_target = target in {
        "future_quality_persistence_4q", "future_quality_persistence_8q",
        "excess_return_60d", "excess_return_120d", "excess_return_240d",
        "future_max_drawdown_120d", "future_max_drawdown_240d",
    }
    for sample in sample_list:
        if long_term_target and not sample.labels.long_term_label_available:
            continue
        if not long_term_target and not sample.labels.label_available:
            continue
        if sample.feature_coverage < minimum_feature_coverage:
            continue
        value = getattr(sample.labels, target, None)
        if value is None:
            continue
        features = {
            str(name): float(value)
            for name, value in sample.features.items()
            if value is not None and _finite(float(value))
        }
        if not features:
            continue
        period_key = (sample.symbol, _period_key(sample.as_of_date, snapshot_frequency))
        observation = LongTermObservation(
            symbol=sample.symbol,
            decision_date=sample.as_of_date,
            industry_key=sample.industry_key,
            features=features,
            target=float(value),
            regime=_infer_feature_regime(features),
            feature_coverage=float(sample.feature_coverage),
            data_quality_status=str(sample.data_quality_status),
        )
        # Keep the last available trading day in each calendar period. This
        # handles quarter/month ends falling on weekends or market holidays.
        previous = candidates.get(period_key)
        if previous is None or observation.decision_date > previous.decision_date:
            candidates[period_key] = observation
    return sorted(candidates.values(), key=lambda item: (item.decision_date, item.symbol))


def attach_future_quality_labels(samples: list[TrainingSample]) -> list[TrainingSample]:
    """Attach 4/8-quarter forward quality persistence labels when possible.

    The label is built only from later PIT snapshots of the same symbol. It is
    intentionally conservative: fewer than four/eight later snapshots leaves
    the corresponding label unavailable instead of forward-filling it.
    """
    latest: dict[tuple[str, date], TrainingSample] = {}
    for sample in samples:
        key = (sample.symbol, _period_key(sample.as_of_date, "quarterly"))
        previous = latest.get(key)
        if previous is None or sample.as_of_date > previous.as_of_date:
            latest[key] = sample
    by_symbol: dict[str, list[TrainingSample]] = {}
    for sample in latest.values():
        by_symbol.setdefault(sample.symbol, []).append(sample)
    result = []
    for sample in samples:
        key = (sample.symbol, _period_key(sample.as_of_date, "quarterly"))
        if latest.get(key) is not sample:
            result.append(sample)
            continue
        timeline = sorted(by_symbol[sample.symbol], key=lambda item: item.as_of_date)
        index = next(i for i, item in enumerate(timeline) if item is sample)
        future = timeline[index + 1 :]
        quality_4q = _future_quality_mean(future[:4]) if len(future) >= 4 else None
        quality_8q = _future_quality_mean(future[:8]) if len(future) >= 8 else None
        labels = sample.labels.model_copy(update={
            "future_quality_persistence_4q": quality_4q,
            "future_quality_persistence_8q": quality_8q,
            "long_term_label_available": bool(sample.labels.long_term_label_available or quality_4q is not None),
        })
        result.append(sample.model_copy(update={"labels": labels}))
    return result


def _future_quality_mean(samples: list[TrainingSample]) -> float | None:
    values = [_quality_signal(sample.features) for sample in samples]
    values = [value for value in values if value is not None]
    return _mean(values) if values else None


def _quality_signal(features: dict[str, float]) -> float | None:
    parts = []
    for name in QUALITY_FEATURES:
        if name not in features or not _finite(float(features[name])):
            continue
        value = float(features[name])
        if "liability_to_asset" in name:
            parts.append(1.0 - _bounded(value, 0.0, 1.0))
        elif "cfo_to_net_profit" in name:
            parts.append(_bounded(value, -1.0, 3.0))
        elif "current_ratio" in name or "quick_ratio" in name:
            parts.append(_bounded(value, 0.0, 3.0))
        else:
            parts.append(_bounded(value, -0.2, 0.5))
    return _mean(parts) * 100.0 if parts else None


def _period_key(value: date, frequency: str) -> date:
    if frequency == "monthly":
        return date(value.year, value.month, 1)
    quarter = (value.month - 1) // 3
    return date(value.year, quarter * 3 + 1, 1)


def evaluate_cross_sectional(
    observations: list[LongTermObservation],
    scores: list[float],
    *,
    top_k: int = 20,
    transaction_cost_bps: float = 15.0,
) -> dict[str, Any]:
    """Evaluate rank quality and a simple long-only top-k portfolio.

    Scores and targets are compared within each decision date. The cost model
    is intentionally explicit and conservative; capacity remains unavailable
    until turnover, volume and market-impact data are supplied.
    """
    if len(observations) != len(scores):
        raise ValueError("observations and scores must have equal length")
    grouped: dict[date, list[int]] = {}
    for index, observation in enumerate(observations):
        grouped.setdefault(observation.decision_date, []).append(index)
    ics: list[float] = []
    top_returns: list[float] = []
    spreads: list[float] = []
    turnovers: list[float] = []
    previous_symbols: set[str] = set()
    for day in sorted(grouped):
        indexes = grouped[day]
        if len(indexes) < 5:
            continue
        ranked = sorted(indexes, key=lambda idx: scores[idx], reverse=True)
        actual = [observations[idx].target for idx in indexes]
        predicted = [scores[idx] for idx in indexes]
        ic = _rank_correlation(predicted, actual)
        if ic is not None:
            ics.append(ic)
        k = min(max(1, top_k), len(indexes) // 2)
        top = ranked[:k]
        bottom = ranked[-k:]
        top_return = _mean(observations[idx].target for idx in top)
        bottom_return = _mean(observations[idx].target for idx in bottom)
        top_returns.append(top_return)
        spreads.append(top_return - bottom_return)
        current_symbols = {observations[idx].symbol for idx in top}
        turnovers.append(1.0 if not previous_symbols else 1.0 - len(current_symbols & previous_symbols) / k)
        previous_symbols = current_symbols
    point_mae = _mean(abs(float(score) - observation.target) for score, observation in zip(scores, observations))
    median_pinball = _mean(
        0.5 * (
            (observation.target - float(score)) if observation.target >= float(score)
            else (float(score) - observation.target)
        )
        for score, observation in zip(scores, observations)
    )
    if not top_returns:
        return {
            "sample_count": len(observations),
            "decision_date_count": 0,
            "rank_ic": None,
            "rank_icir": None,
            "top_k_excess_return": None,
            "top_bottom_excess_return": None,
            "turnover": None,
            "top_k_excess_return_after_cost": None,
            "top_bottom_spread_after_cost": None,
            "max_drawdown_after_cost": None,
            "capacity_estimate": None,
            "year_rank_ic": {},
            "industry_sample_counts": {},
            "industry_rank_ic": {},
            "regime_rank_ic": {},
            "regime_sample_counts": {},
            "data_completeness_rank_ic": {},
            "data_completeness_sample_counts": {},
            "mae": point_mae,
            "pinball_loss": median_pinball,
            "interval_coverage": None,
        }
    turnover = _mean(turnovers)
    cost = turnover * transaction_cost_bps / 10000.0
    net_returns = [value - cost for value in top_returns]
    year_ic: dict[str, list[float]] = {}
    industry_counts: dict[str, int] = {}
    industry_ics: dict[str, list[float]] = {}
    regime_ics: dict[str, list[float]] = {}
    regime_counts: dict[str, int] = {}
    completeness_ics: dict[str, list[float]] = {}
    completeness_counts: dict[str, int] = {}
    for day, indexes in grouped.items():
        day_ic = _rank_correlation([scores[idx] for idx in indexes], [observations[idx].target for idx in indexes])
        if day_ic is not None:
            year_ic.setdefault(str(day.year), []).append(day_ic)
        for idx in indexes:
            key = observations[idx].industry_key or "unknown"
            industry_counts[key] = industry_counts.get(key, 0) + 1
            regime = observations[idx].regime or "unknown"
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
            completeness = _completeness_bucket(observations[idx])
            completeness_counts[completeness] = completeness_counts.get(completeness, 0) + 1
        for industry in sorted({observations[idx].industry_key or "unknown" for idx in indexes}):
            industry_indexes = [idx for idx in indexes if (observations[idx].industry_key or "unknown") == industry]
            if len(industry_indexes) >= 5:
                industry_ic = _rank_correlation(
                    [scores[idx] for idx in industry_indexes],
                    [observations[idx].target for idx in industry_indexes],
                )
                if industry_ic is not None:
                    industry_ics.setdefault(industry, []).append(industry_ic)
        for regime in sorted({observations[idx].regime or "unknown" for idx in indexes}):
            regime_indexes = [idx for idx in indexes if (observations[idx].regime or "unknown") == regime]
            if len(regime_indexes) >= 5:
                regime_ic = _rank_correlation(
                    [scores[idx] for idx in regime_indexes],
                    [observations[idx].target for idx in regime_indexes],
                )
                if regime_ic is not None:
                    regime_ics.setdefault(regime, []).append(regime_ic)
        for completeness in sorted({_completeness_bucket(observations[idx]) for idx in indexes}):
            completeness_indexes = [
                idx for idx in indexes if _completeness_bucket(observations[idx]) == completeness
            ]
            if len(completeness_indexes) >= 5:
                completeness_ic = _rank_correlation(
                    [scores[idx] for idx in completeness_indexes],
                    [observations[idx].target for idx in completeness_indexes],
                )
                if completeness_ic is not None:
                    completeness_ics.setdefault(completeness, []).append(completeness_ic)
    return {
        "sample_count": len(observations),
        "decision_date_count": len(top_returns),
        "rank_ic": _mean(ics) if ics else None,
        "rank_icir": (_mean(ics) / _std(ics) * sqrt(len(ics))) if len(ics) > 1 and _std(ics) > 0 else None,
        "top_k_excess_return": _mean(top_returns),
        "top_bottom_excess_return": _mean(spreads),
        "turnover": turnover,
        "top_k_excess_return_after_cost": _mean(net_returns),
        "top_bottom_spread_after_cost": _mean(spreads) - cost,
        "max_drawdown_after_cost": _max_drawdown(net_returns),
        "capacity_estimate": None,
        "mae": point_mae,
        "pinball_loss": median_pinball,
        "interval_coverage": None,
        "year_rank_ic": {year: _mean(values) for year, values in sorted(year_ic.items())},
        "industry_sample_counts": dict(sorted(industry_counts.items())),
        "industry_rank_ic": {industry: _mean(values) for industry, values in sorted(industry_ics.items())},
        "regime_rank_ic": {regime: _mean(values) for regime, values in sorted(regime_ics.items())},
        "regime_sample_counts": dict(sorted(regime_counts.items())),
        "data_completeness_rank_ic": {
            bucket: _mean(values) for bucket, values in sorted(completeness_ics.items())
        },
        "data_completeness_sample_counts": dict(sorted(completeness_counts.items())),
    }


def run_long_term_baselines(
    observations: list[LongTermObservation],
    *,
    config: LongTermTrainingConfig,
    prediction_rows: list[dict] | None = None,
    checkpoint_dir: Path | None = None,
    resume: bool = True,
) -> dict:
    """Run baselines with fold checkpoints and one final test.

    A completed fold is an independent, immutable unit of work.  If a process
    is interrupted, the next invocation reuses only a checkpoint whose
    observation context, feature list, model and fold all match the current
    run.  This makes resume safe across process restarts without silently
    mixing results from different data snapshots.
    """
    if not observations:
        return {"status": "blocked", "blocking_reasons": ["no_mature_long_term_observations"]}
    dates = sorted({item.decision_date for item in observations})
    holdout_start_index = len(dates) - config.final_holdout_periods
    if holdout_start_index <= 0:
        return {"status": "blocked", "blocking_reasons": ["insufficient_dates_for_final_holdout"]}
    holdout_start = dates[holdout_start_index]
    stress_start = dates[-config.stress_periods]
    development = [item for item in observations if item.decision_date < holdout_start]
    holdout = [item for item in observations if item.decision_date >= holdout_start]
    stress = [item for item in holdout if item.decision_date >= stress_start]
    folds = build_period_walk_forward_folds(
        [item.decision_date for item in development],
        train_periods=config.train_window_periods,
        validation_periods=config.validation_periods,
        purge_periods=config.purge_periods,
        embargo_periods=config.embargo_periods,
        label_horizon_days=max(config.horizons_days),
    )
    if not folds:
        return {"status": "blocked", "blocking_reasons": ["no_purged_walk_forward_folds"]}
    feature_names = sorted({name for item in observations for name in item.features})
    models = _models()
    checkpoint_root = Path(checkpoint_dir) if checkpoint_dir is not None else None
    if checkpoint_root is not None:
        checkpoint_root.mkdir(parents=True, exist_ok=True)
    context_hash = _observations_context_hash(observations, feature_names)
    report = {
        "status": "research_only",
        "deployment_ready": False,
        "feature_names": feature_names,
        "holdout_start": holdout_start.isoformat(),
        "stress_start": stress_start.isoformat(),
        "fold_count": len(folds),
        "capacity_status": "unavailable_without_volume_and_impact_model",
        "multiple_testing_note": "baseline comparison is exploratory; final holdout is evaluated once",
        "checkpoint": {
            "enabled": checkpoint_root is not None,
            "resume": bool(resume),
            "context_sha256": context_hash,
            "loaded_fold_count": 0,
            "written_fold_count": 0,
            "invalidated_fold_count": 0,
        },
        "models": {},
    }
    gpu_fallbacks: dict[str, str] = {}
    for model_name, factory in models.items():
        oof_observations: list[LongTermObservation] = []
        oof_scores: list[float] = []
        for fold in folds:
            train = [item for item in development if fold.train_start <= item.decision_date <= fold.train_end and item.decision_date < fold.validation_start]
            validation = [item for item in development if fold.validation_start <= item.decision_date <= fold.validation_end]
            if not train or not validation:
                continue
            checkpoint_path = _fold_checkpoint_path(checkpoint_root, model_name, fold.fold_id) if checkpoint_root else None
            cached = _load_fold_checkpoint(
                checkpoint_path,
                model_name=model_name,
                fold_id=fold.fold_id,
                context_hash=context_hash,
                feature_names=feature_names,
            ) if resume else None
            if cached is not None:
                cached_observations, fold_scores = cached
                oof_observations.extend(cached_observations)
                oof_scores.extend(fold_scores)
                report["checkpoint"]["loaded_fold_count"] += 1
                if prediction_rows is not None:
                    prediction_rows.extend(_prediction_rows(model_name, "oof", cached_observations, fold_scores))
                continue
            if checkpoint_path is not None and checkpoint_path.exists():
                report["checkpoint"]["invalidated_fold_count"] += 1
            model, fallback_reason = _fit_model(model_name, factory, train, feature_names)
            if fallback_reason:
                gpu_fallbacks[model_name] = fallback_reason
            oof_observations.extend(validation)
            fold_scores = [float(value) for value in model.predict(validation if model_name == "industry-mean-baseline" else _matrix(validation, feature_names))]
            oof_scores.extend(fold_scores)
            if checkpoint_path is not None:
                _write_fold_checkpoint(
                    checkpoint_path,
                    model_name=model_name,
                    fold_id=fold.fold_id,
                    context_hash=context_hash,
                    feature_names=feature_names,
                    observations=validation,
                    scores=fold_scores,
                )
                report["checkpoint"]["written_fold_count"] += 1
            if prediction_rows is not None:
                prediction_rows.extend(
                    _prediction_rows(model_name, "oof", validation, fold_scores)
                )
        if not oof_observations:
            report["models"][model_name] = {"status": "blocked", "reason": "no_oof_predictions"}
            continue
        oof_metrics = evaluate_cross_sectional(oof_observations, oof_scores, top_k=config.top_k, transaction_cost_bps=config.transaction_cost_bps)
        final_model, fallback_reason = _fit_model(model_name, factory, development, feature_names)
        if fallback_reason:
            gpu_fallbacks[model_name] = fallback_reason
        if model_name == "industry-mean-baseline":
            holdout_scores = [float(value) for value in final_model.predict(holdout)]
            stress_scores = [float(value) for value in final_model.predict(stress)]
        else:
            holdout_scores = [float(value) for value in final_model.predict(_matrix(holdout, feature_names))]
            stress_scores = [float(value) for value in final_model.predict(_matrix(stress, feature_names))]
        if prediction_rows is not None:
            prediction_rows.extend(_prediction_rows(model_name, "holdout", holdout, holdout_scores))
            prediction_rows.extend(_prediction_rows(model_name, "stress", stress, stress_scores))
        report["models"][model_name] = {
            "status": "research_only",
            "oof_metrics": oof_metrics,
            "holdout_metrics": evaluate_cross_sectional(holdout, holdout_scores, top_k=config.top_k, transaction_cost_bps=config.transaction_cost_bps),
            "stress_metrics": evaluate_cross_sectional(stress, stress_scores, top_k=config.top_k, transaction_cost_bps=config.transaction_cost_bps),
        }
    if gpu_fallbacks:
        report["gpu_fallbacks"] = gpu_fallbacks
    return report


def _observations_context_hash(observations: list[LongTermObservation], feature_names: list[str]) -> str:
    rows = [
        {
            "symbol": item.symbol,
            "decision_date": item.decision_date.isoformat(),
            "industry_key": item.industry_key,
            "regime": item.regime,
            "feature_coverage": item.feature_coverage,
            "data_quality_status": item.data_quality_status,
            "features": {name: item.features.get(name) for name in feature_names},
            "target": item.target,
        }
        for item in sorted(observations, key=lambda value: (value.decision_date, value.symbol))
    ]
    encoded = json.dumps({"feature_names": feature_names, "rows": rows}, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fold_checkpoint_path(root: Path | None, model_name: str, fold_id: str) -> Path | None:
    if root is None:
        return None
    safe_model = "".join(character if character.isalnum() or character in "-_" else "_" for character in model_name)
    return root / safe_model / f"{fold_id}.json"


def _load_fold_checkpoint(
    path: Path | None,
    *,
    model_name: str,
    fold_id: str,
    context_hash: str,
    feature_names: list[str],
) -> tuple[list[LongTermObservation], list[float]] | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "long-term-fold-checkpoint-v1":
            return None
        if payload.get("model_name") != model_name or payload.get("fold_id") != fold_id:
            return None
        if payload.get("context_sha256") != context_hash or payload.get("feature_names") != feature_names:
            return None
        observations = []
        scores = []
        for row in payload.get("rows", []):
            observations.append(LongTermObservation(
                symbol=str(row["symbol"]),
                decision_date=date.fromisoformat(str(row["decision_date"])),
                industry_key=row.get("industry_key"),
                features={},
                target=float(row["target"]),
                regime=str(row.get("regime") or "unknown"),
                feature_coverage=float(row.get("feature_coverage", 1.0)),
                data_quality_status=str(row.get("data_quality_status") or "passed"),
            ))
            scores.append(float(row["score"]))
        if not observations or len(observations) != len(scores):
            return None
        return observations, scores
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_fold_checkpoint(
    path: Path,
    *,
    model_name: str,
    fold_id: str,
    context_hash: str,
    feature_names: list[str],
    observations: list[LongTermObservation],
    scores: list[float],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "long-term-fold-checkpoint-v1",
        "model_name": model_name,
        "fold_id": fold_id,
        "context_sha256": context_hash,
        "feature_names": feature_names,
        "row_count": len(observations),
        "rows": _prediction_rows(model_name, "oof", observations, scores),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


QUALITY_FEATURES = (
    "fundamental_roe_avg", "fundamental_dupont_roe", "fundamental_net_margin",
    "fundamental_cfo_to_revenue", "fundamental_cfo_to_net_profit",
    "fundamental_current_ratio", "fundamental_quick_ratio",
    "fundamental_liability_to_asset", "fundamental_net_income_yoy",
    "fundamental_eps_yoy", "fundamental_parent_net_income_yoy",
)
GROWTH_FEATURES = (
    "fundamental_net_income_yoy", "fundamental_eps_yoy",
    "fundamental_parent_net_income_yoy", "fundamental_asset_yoy",
    "fundamental_equity_yoy",
)
SHAREHOLDER_RETURN_FEATURES = (
    "fundamental_dividend_yield", "fundamental_payout_ratio",
    "fundamental_buyback_yield", "fundamental_roe_avg", "fundamental_dupont_roe",
)
VALUATION_FEATURES = (
    "valuation_pe_ttm", "valuation_pb_mrq", "valuation_ps_ttm", "valuation_pcf_ttm",
)
RISK_FEATURES = (
    "vol_20d", "vol_60d", "regulatory_risk_score_30d", "negative_event_score_7d",
    "halted_flag", "st_flag", "market_return_dispersion_1d", "margin_financing_change_5d",
)


def score_long_term_snapshot(
    features: dict[str, float],
    *,
    feature_coverage: float,
    status_bands: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Create an auditable research scorecard from one PIT snapshot.

    This is deliberately an evidence scorecard, not a disguised trained label:
    the learned heads remain relative-return and drawdown models. It provides
    the requested long-term research language while data for future financial
    persistence labels is still being normalized.
    """
    bands = status_bands or {"robust": 70.0, "observe": 45.0}
    quality_parts = []
    for name in QUALITY_FEATURES:
        if name not in features:
            continue
        value = float(features[name])
        if "liability_to_asset" in name:
            quality_parts.append(1.0 - _bounded(value, 0.0, 1.0))
        elif "cfo_to_net_profit" in name:
            quality_parts.append(_bounded(value, -1.0, 3.0))
        elif "current_ratio" in name or "quick_ratio" in name:
            quality_parts.append(_bounded(value, 0.0, 3.0))
        else:
            quality_parts.append(_bounded(value, -0.2, 0.5))
    valuation_parts = [
        _bounded(float(features[name]), low, high)
        for name, low, high in (
            ("valuation_pe_ttm", 0.0, 80.0),
            ("valuation_pb_mrq", 0.0, 12.0),
            ("valuation_ps_ttm", 0.0, 20.0),
            ("valuation_pcf_ttm", 0.0, 80.0),
        )
        if name in features and float(features[name]) >= 0
    ]
    risk_parts = []
    for name in RISK_FEATURES:
        if name not in features:
            continue
        value = float(features[name])
        if name in {"halted_flag", "st_flag"}:
            risk_parts.append(_bounded(value, 0.0, 1.0))
        elif "vol_" in name:
            risk_parts.append(_bounded(value, 0.0, 0.1))
        elif "risk_score" in name or "negative_event" in name:
            risk_parts.append(_bounded(value, 0.0, 1.0))
        elif "dispersion" in name:
            risk_parts.append(_bounded(abs(value), 0.0, 0.1))
        else:
            risk_parts.append(_bounded(abs(value), 0.0, 0.2))
    quality_score = _mean(quality_parts) * 100.0 if quality_parts else None
    valuation_position = _mean(valuation_parts) * 100.0 if valuation_parts else None
    growth_parts = [
        _bounded(float(features[name]), -0.5, 0.5)
        for name in GROWTH_FEATURES
        if name in features
    ]
    shareholder_parts = []
    for name in SHAREHOLDER_RETURN_FEATURES:
        if name not in features:
            continue
        low, high = ((0.0, 0.2) if "yield" in name else (-0.2, 0.5))
        shareholder_parts.append(_bounded(float(features[name]), low, high))
    growth_stability = _mean(growth_parts) * 100.0 if growth_parts else None
    shareholder_return = _mean(shareholder_parts) * 100.0 if shareholder_parts else None
    risk_score = _mean(risk_parts) * 100.0 if risk_parts else None
    evidence_completeness = _bounded(float(feature_coverage), 0.0, 1.0) * 100.0
    composite_parts = [value for value in (
        quality_score,
        growth_stability,
        100.0 - valuation_position if valuation_position is not None else None,
        shareholder_return,
        100.0 - risk_score if risk_score is not None else None,
        evidence_completeness,
    ) if value is not None]
    composite_score = _mean(composite_parts) if composite_parts else 0.0
    if risk_score is not None and risk_score >= 70.0:
        status = "risk_high"
    elif composite_score >= bands.get("robust", 70.0):
        status = "robust"
    else:
        status = "observe"
    evidence = []
    if not quality_parts:
        evidence.append("quality_features_missing")
    if not growth_parts:
        evidence.append("growth_features_missing")
    if not valuation_parts:
        evidence.append("valuation_features_missing")
    if not shareholder_parts:
        evidence.append("shareholder_return_features_missing")
    if not risk_parts:
        evidence.append("risk_features_missing")
    if evidence_completeness < 80.0:
        evidence.append("feature_coverage_below_80pct")
    return {
        "long_term_quality": quality_score,
        "growth_stability": growth_stability,
        "valuation_position": valuation_position,
        "shareholder_return": shareholder_return,
        "long_term_risk": risk_score,
        "evidence_completeness": evidence_completeness,
        "composite_score": composite_score,
        "status": status,
        "evidence": evidence,
        "score_type": "pit_evidence_scorecard_not_trained_label",
    }


def _models():
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import ElasticNet, Ridge
    from sklearn.pipeline import make_pipeline

    use_gpu = os.environ.get("INVESTMENT_RESEARCH_USE_GPU", "0") == "1"
    models = {
        "constant-baseline": lambda: _ConstantRegressor(),
        "industry-mean-baseline": lambda: _IndustryMeanRegressor(),
        "ridge-baseline": lambda: make_pipeline(SimpleImputer(strategy="median"), Ridge(alpha=1.0)),
        "elastic-net": lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            ElasticNet(alpha=0.001, l1_ratio=0.5, max_iter=5000, random_state=42),
        ),
        "random-forest": lambda: make_pipeline(SimpleImputer(strategy="median"), RandomForestRegressor(n_estimators=200, min_samples_leaf=10, random_state=42, n_jobs=-1)),
    }
    # Optional challengers: the research run remains reproducible when these
    # packages are not installed in the execution environment.
    try:
        from lightgbm import LGBMRegressor
        lightgbm_kwargs = dict(
            n_estimators=300, learning_rate=0.03, num_leaves=31,
            min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbosity=-1, n_jobs=-1,
        )
        models["lightgbm"] = lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            LGBMRegressor(**lightgbm_kwargs),
        )
        if use_gpu:
            models["lightgbm-gpu"] = lambda: make_pipeline(
                SimpleImputer(strategy="median"),
                LGBMRegressor(**lightgbm_kwargs, device_type="gpu"),
            )
    except ImportError:
        pass
    try:
        from xgboost import XGBRegressor
        xgb_kwargs = dict(
            n_estimators=300, max_depth=4, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            objective="reg:squarederror", random_state=42, n_jobs=-1,
        )
        models["xgboost"] = lambda: make_pipeline(
            SimpleImputer(strategy="median"),
            XGBRegressor(**xgb_kwargs),
        )
        if use_gpu:
            models["xgboost-gpu"] = lambda: make_pipeline(
                SimpleImputer(strategy="median"),
                XGBRegressor(**xgb_kwargs, device="cuda"),
            )
    except ImportError:
        pass
    return models


def _fit_model(model_name, factory, observations, feature_names):
    """Fit a model, falling back from an unavailable GPU backend explicitly."""
    matrix = observations if model_name == "industry-mean-baseline" else _matrix(observations, feature_names)
    targets = None if model_name == "industry-mean-baseline" else [item.target for item in observations]
    model = factory()
    try:
        model.fit(matrix, targets) if targets is not None else model.fit(matrix)
        return model, None
    except Exception as exc:
        if not model_name.endswith("-gpu"):
            raise
        cpu_factory = _models().get(model_name.removesuffix("-gpu"))
        if cpu_factory is None:
            raise
        fallback = cpu_factory()
        fallback.fit(matrix, targets) if targets is not None else fallback.fit(matrix)
        return fallback, f"{type(exc).__name__}:{exc}"


class _ConstantRegressor:
    """Historical/distribution baseline with no feature signal."""

    def fit(self, _matrix, targets):
        self.value = _mean(float(target) for target in targets)
        return self

    def predict(self, matrix):
        return [self.value for _ in matrix]


class _IndustryMeanRegressor:
    """Leakage-safe cross-sectional industry mean baseline."""

    def fit(self, observations: list[LongTermObservation]):
        buckets: dict[str, list[float]] = {}
        for observation in observations:
            buckets.setdefault(observation.industry_key or "unknown", []).append(observation.target)
        self.global_mean = _mean(item.target for item in observations)
        self.means = {key: _mean(values) for key, values in buckets.items()}
        return self

    def predict(self, observations: list[LongTermObservation]):
        return [self.means.get(item.industry_key or "unknown", self.global_mean) for item in observations]


def _matrix(items: list[LongTermObservation], feature_names: list[str]):
    return [[item.features.get(name, float("nan")) for name in feature_names] for item in items]


def _prediction_rows(
    model_name: str,
    split: str,
    observations: list[LongTermObservation],
    scores: list[float],
) -> list[dict]:
    return [
        {
            "model": model_name,
            "split": split,
            "symbol": item.symbol,
            "decision_date": item.decision_date.isoformat(),
            "industry_key": item.industry_key,
            "regime": item.regime,
            "feature_coverage": item.feature_coverage,
            "data_quality_status": item.data_quality_status,
            "target": item.target,
            "score": score,
        }
        for item, score in zip(observations, scores)
    ]


def _rank_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    left_mean = _mean(left_ranks)
    right_mean = _mean(right_ranks)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left_ranks, right_ranks))
    denominator = sqrt(sum((a - left_mean) ** 2 for a in left_ranks) * sum((b - right_mean) ** 2 for b in right_ranks))
    return numerator / denominator if denominator else None


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    for rank, index in enumerate(order):
        result[index] = float(rank)
    return result


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = equity
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return worst


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _bounded(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _completeness_bucket(observation: LongTermObservation) -> str:
    """Bucket observed feature coverage without turning missingness into zero."""
    coverage = max(0.0, min(1.0, float(observation.feature_coverage)))
    if observation.data_quality_status in {"blocked", "unavailable", "error"}:
        return "quality_blocked"
    if coverage < 0.95:
        return "coverage_below_95%"
    if coverage < 0.98:
        return "coverage_95_to_98%"
    return "coverage_at_least_98%"


def _infer_feature_regime(features: dict[str, float]) -> str:
    """Classify a decision-time market state without using future labels.

    Long-term samples do not always carry a separate benchmark-bar reference.
    When they do carry PIT market return/volatility features, this provides a
    transparent diagnostic split. Missing inputs deliberately remain
    ``unknown`` rather than being inferred from the target.
    """
    market_return = next(
        (float(features[name]) for name in ("market_return_20d", "benchmark_ret_20d", "market_return_60d") if name in features),
        None,
    )
    volatility = next(
        (float(features[name]) for name in ("market_volatility_20d", "vol_20d", "vol_60d") if name in features),
        None,
    )
    if market_return is None and volatility is None:
        return "unknown"
    if volatility is not None and volatility >= 0.03:
        return "high_vol"
    if market_return is None:
        return "unknown"
    if market_return >= 0.10:
        return "bull"
    if market_return <= -0.10:
        return "bear"
    return "range"
