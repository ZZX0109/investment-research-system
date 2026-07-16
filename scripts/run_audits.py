#!/usr/bin/env python3
"""Authoritative training audits for real + full artifacts."""
from __future__ import annotations

import csv
import json
import os
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = Path(os.environ.get("INVESTMENT_RESEARCH_OUTPUT_DIR", PROJECT / "output"))
AUDITS = Path(os.environ.get("INVESTMENT_RESEARCH_AUDIT_DIR", PROJECT / "audits"))
TEMP = Path(os.environ.get("INVESTMENT_RESEARCH_TEMP_DIR", PROJECT / "temp"))
RUNS = Path(os.environ.get("INVESTMENT_RESEARCH_RUNS_DIR", PROJECT / "runs"))
AUDITS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.catalog import TARGET_MARKET_TYPE_COUNTS, UNIVERSE_PRESETS, iter_market_presets


def load_pickle(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_with_aliases(filename: str, payload: dict, *, aliases: list[str] | None = None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    (AUDITS / filename).write_text(text, encoding="utf-8")
    for alias in aliases or []:
        (AUDITS / alias).write_text(text, encoding="utf-8")


def _instrument_distribution(market: str) -> dict[str, int]:
    counter = Counter(preset.instrument_type.value for preset in iter_market_presets(market))
    return dict(counter)


def _industry_distribution(market: str) -> dict[str, int]:
    counter = Counter(preset.industry_key for preset in iter_market_presets(market))
    return dict(counter)


def _coverage_group_distribution(market: str) -> dict[str, int]:
    counter = Counter(preset.coverage_group.value for preset in iter_market_presets(market))
    return dict(counter)


def _expected_distribution(market: str) -> dict[str, int]:
    presets = iter_market_presets(market)
    if not presets:
        return {}
    return {
        instrument_type.value: count
        for instrument_type, count in TARGET_MARKET_TYPE_COUNTS[presets[0].market].items()
    }


def _event_feature_names() -> list[str]:
    return [
        "event_score_1d",
        "event_score_7d",
        "event_score_30d",
        "negative_event_score_7d",
        "official_event_score_30d",
        "earnings_surprise_score_30d",
        "guidance_cut_flag_30d",
        "regulatory_risk_score_30d",
        "mna_event_flag_30d",
        "filing_8k_count_30d",
    ]


def main() -> int:
    results = load_json(OUTPUT / "results.json")
    labels_rows: list[dict] = []
    if (OUTPUT / "labels.csv").exists():
        with open(OUTPUT / "labels.csv", encoding="utf-8") as f:
            labels_rows = list(csv.DictReader(f))

    sample_cache = load_pickle(TEMP / "all_samples.pkl") if (TEMP / "all_samples.pkl").exists() else {}
    selected_samples = sample_cache.get("samples", [])
    raw_samples = sample_cache.get("raw_samples", selected_samples)
    bundles = {
        market: load_pickle(OUTPUT / f"bundle_{market}.pkl")
        for market in ("us", "cn", "hk", "jp")
        if (OUTPUT / f"bundle_{market}.pkl").exists()
    }
    price_validation = load_json(TEMP / "fetch_validation.json")
    event_validation = load_json(TEMP / "fetch_events_validation.json")
    training_status = load_json(RUNS / "training-status.json")

    generated_at = results.get("generated_at")
    artifact_identity = {
        "training_run_id": results.get("run_label"),
        "sample_snapshot_hash": results.get("sample_snapshot_hash"),
        "feature_contract_version": results.get("feature_contract_version"),
        "data_version": results.get("data_source"),
        "generated_at": generated_at,
    }

    data_coverage = {
        **artifact_identity,
        "training_status": training_status,
        "symbol_total": len(UNIVERSE_PRESETS),
        "global_summary": {
            "included_markets": results.get("included_markets", []),
            "excluded_markets": results.get("excluded_markets", []),
            "excluded_market_reasons": results.get("excluded_market_reasons", {}),
            "universe_distribution": results.get("universe_distribution", {}),
            "coverage_group_distribution": results.get("coverage_group_distribution", {}),
            "reference_missing_rates": results.get("reference_missing_rates", {}),
            "event_task_sample_counts": results.get("event_task_sample_counts", {}),
            "training_status": training_status,
        },
        "markets": {},
    }
    for market in ("us", "cn", "hk", "jp"):
        expected_symbols = [preset.symbol for preset in iter_market_presets(market)]
        bundle = bundles.get(market, {})
        bundle_symbols = sorted({getattr(bar, "symbol", "") for bar in bundle.get("price_bars", [])})
        market_price_report = price_validation.get(market, {})
        market_event_report = event_validation.get(market, {})
        provenance_coverage = _bundle_provenance_coverage(bundle)
        data_coverage["markets"][market] = {
            "expected_symbol_count": len(expected_symbols),
            "fetched_symbol_count": len(bundle_symbols),
            "coverage_rate": round(len(bundle_symbols) / len(expected_symbols), 4) if expected_symbols else 0.0,
            "instrument_distribution": _instrument_distribution(market),
            "expected_distribution": _expected_distribution(market),
            "industry_distribution": _industry_distribution(market),
            "coverage_group_distribution": _coverage_group_distribution(market),
            "missing_symbols": sorted(set(expected_symbols) - set(bundle_symbols)),
            "provider_usage": market_price_report.get("provider_usage", {}),
            "fallback_usage": {
                provider: count
                for provider, count in market_price_report.get("provider_usage", {}).items()
                if "fallback" in provider
            },
            "price_rows": len(bundle.get("price_bars", [])),
            "event_count": len(bundle.get("events", [])),
            "event_provider_counts": market_event_report.get("provider_counts", {}),
            "event_type_counts": market_event_report.get("event_type_counts", {}),
            "event_density_by_symbol": market_event_report.get("event_density_by_symbol", {}),
            "provider_coverage": market_event_report.get("provider_coverage", {}),
            "provider_failures": market_event_report.get("provider_failures", []),
            "provenance_coverage": provenance_coverage,
        }
    write_json_with_aliases("data_coverage.json", data_coverage, aliases=["audit_data.json"])

    reference_coverage = {
        "generated_at": generated_at,
        "reference_preflight": results.get("reference_preflight", {}),
        "reference_missing_rates": results.get("reference_missing_rates", {}),
        "reference_risk_flag": results.get("reference_risk_flag", False),
        "threshold_checks": (results.get("reference_preflight", {}) or {}).get("threshold_checks", {}),
    }
    write_json_with_aliases("reference_coverage.json", reference_coverage)

    label_fields = [
        field
        for field in labels_rows[0].keys()
        if field not in {"symbol", "market", "instrument_type", "as_of_date", "training_weight", "selected_for_training"}
    ] if labels_rows else []
    label_coverage = {
        **artifact_identity,
        "label_distributions": {},
        "market_coverage": _selection_coverage(labels_rows, "market"),
        "asset_type_coverage": _selection_coverage(labels_rows, "instrument_type"),
        "coverage_group_coverage": _selection_coverage_from_samples(raw_samples, "coverage_group"),
        "index_low_weight_summary": {
            "row_count": sum(1 for row in labels_rows if row.get("instrument_type") == "index"),
            "selected_for_training": sum(
                int(row.get("selected_for_training", "0")) for row in labels_rows if row.get("instrument_type") == "index"
            ),
            "configured_weight": 0.35,
        },
    }
    for field in label_fields:
        values = []
        market_counter = Counter()
        for row in labels_rows:
            value = row.get(field)
            if value in ("", None):
                continue
            try:
                values.append(float(value))
                market_counter[row.get("market", "unknown")] += 1
            except (TypeError, ValueError):
                continue
        total = len(labels_rows)
        label_coverage["label_distributions"][field] = {
            "total_rows": total,
            "present_rows": len(values),
            "missing_rows": total - len(values),
            "missing_ratio": round((total - len(values)) / total, 4) if total else 0.0,
            "market_distribution": dict(sorted(market_counter.items())),
        }
    write_json_with_aliases("label_coverage.json", label_coverage, aliases=["label_audit.json"])

    event_feature_coverage = {
        **artifact_identity,
        "generated_at": generated_at,
        "sample_count": len(selected_samples),
        "raw_sample_count": len(raw_samples),
        "feature_coverage": {},
        "feature_schema": sorted(selected_samples[0].features.keys()) if selected_samples else [],
        "sample_feature_coverage": _sample_feature_coverage(selected_samples),
        "missing_feature_counts": _missing_feature_counts(selected_samples),
        "reference_missing_rates": results.get("reference_missing_rates", {}),
        "market_non_zero_coverage": _market_event_feature_coverage(selected_samples),
    }
    for feature_name in _event_feature_names():
        non_zero = sum(1 for sample in selected_samples if abs(sample.features.get(feature_name, 0.0)) > 1e-12)
        event_feature_coverage["feature_coverage"][feature_name] = {
            "non_zero_samples": non_zero,
            "non_zero_ratio": round(non_zero / len(selected_samples), 4) if selected_samples else 0.0,
        }
    write_json_with_aliases(
        "event_feature_coverage.json",
        event_feature_coverage,
        aliases=["feature_audit.json"],
    )

    event_semantic_coverage = {
        **artifact_identity,
        "feature_coverage": event_feature_coverage["feature_coverage"],
        "market_non_zero_coverage": event_feature_coverage["market_non_zero_coverage"],
        "provider_counts": {
            market: (event_validation.get(market, {}) or {}).get("provider_counts", {})
            for market in ("us", "cn", "hk", "jp")
        },
        "event_type_counts": {
            market: (event_validation.get(market, {}) or {}).get("event_type_counts", {})
            for market in ("us", "cn", "hk", "jp")
        },
        "semantic_fields": {
            "negative_event_score_7d": "direction=negative in the last 7 days, decay weighted",
            "guidance_cut_flag_30d": "guidance_bucket=cut in the last 30 days",
            "regulatory_risk_score_30d": "regulation/litigation/policy event types in the last 30 days",
            "mna_event_flag_30d": "m&a event type in the last 30 days",
            "earnings_surprise_score_30d": "surprise_bucket mapped to signed score in the last 30 days",
        },
        "source_availability": {
            "available_samples": sum(1 for sample in selected_samples if getattr(sample, "event_source_available", False)),
            "unavailable_samples": sum(1 for sample in selected_samples if not getattr(sample, "event_source_available", False)),
            "mean_provider_count": round(sum(getattr(sample, "event_provider_count", 0) for sample in selected_samples) / len(selected_samples), 4) if selected_samples else 0.0,
            "mean_semantic_coverage": round(sum(getattr(sample, "event_semantic_coverage", 0.0) for sample in selected_samples) / len(selected_samples), 4) if selected_samples else 0.0,
        },
    }
    write_json_with_aliases("event_semantic_coverage.json", event_semantic_coverage)

    pit_details = []
    pit_failure_rows = []
    for sample in raw_samples:
        pit_details.append(
            {
                "symbol": sample.symbol,
                "market": sample.market.value,
                "coverage_group": sample.coverage_group.value,
                "as_of_date": sample.as_of_date.isoformat(),
                "feature_cutoff": sample.feature_cutoff.isoformat(),
                "published_at": None if sample.published_at is None else sample.published_at.isoformat(),
                "provider": sample.provider,
                "data_version": sample.data_version,
                "point_in_time_event_count": sample.point_in_time_event_count,
                "data_issues": sample.data_issues,
            }
        )
        for issue in sample.data_issues:
            if issue.startswith("future_"):
                pit_failure_rows.append(
                    {
                        "symbol": sample.symbol,
                        "as_of_date": sample.as_of_date.isoformat(),
                        "leak_field": issue,
                        "leak_time_diff": "",
                    }
                )
    pit_report = {
        **artifact_identity,
        "total_samples_checked": len(raw_samples),
        "failure_count": len(pit_failure_rows),
        "included_markets": results.get("included_markets", []),
        "excluded_markets": results.get("excluded_markets", []),
        "provider_coverage": _sample_provenance_coverage(raw_samples),
    }
    write_json_with_aliases("pit_audit.json", pit_report)
    write_json_with_aliases("pit_audit_details.json", {"rows": pit_details})
    with open(AUDITS / "pit_failures.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "as_of_date", "leak_field", "leak_time_diff"])
        writer.writeheader()
        writer.writerows(pit_failure_rows)

    regime_breakdown = {
        **artifact_identity,
        "included_markets": results.get("included_markets", []),
        "excluded_markets": results.get("excluded_markets", []),
        "excluded_market_reasons": results.get("excluded_market_reasons", {}),
        "regime_rule_version": "per-market-v2",
        "primary_task": results.get("regime_breakdown", {}),
        "task_matrix": {
            task_name: task_payload.get("regime_breakdown", {})
            for task_name, task_payload in results.get("task_matrix", {}).items()
        },
    }
    write_json_with_aliases("regime_breakdown.json", regime_breakdown)

    regime_balance = {
        "generated_at": generated_at,
        "regime_rule_version": "per-market-v2",
        "primary_task": _regime_balance_summary(results.get("regime_breakdown", {})),
        "task_matrix": {
            task_name: _regime_balance_summary(task_payload.get("regime_breakdown", {}))
            for task_name, task_payload in results.get("task_matrix", {}).items()
        },
    }
    write_json_with_aliases("regime_balance.json", regime_balance)

    recent_window_breakdown = {
        "generated_at": generated_at,
        "primary_task": results.get("recent_window_breakdown", {}),
        "task_matrix": {
            task_name: task_payload.get("recent_window_breakdown", {})
            for task_name, task_payload in results.get("task_matrix", {}).items()
        },
    }
    write_json_with_aliases("recent_window_breakdown.json", recent_window_breakdown)

    wf_audit = {
        "generated_at": generated_at,
        "included_markets": results.get("included_markets", []),
        "excluded_markets": results.get("excluded_markets", []),
        "excluded_market_reasons": results.get("excluded_market_reasons", {}),
        "regime_breakdown": results.get("regime_breakdown", {}),
        "recent_window_breakdown": results.get("recent_window_breakdown", {}),
        "models": {
            model["trainer_name"]: {
                "fold_count": len(model.get("folds", [])),
                "fold_windows": [
                    {
                        "fold_id": fold.get("fold_id"),
                        "train_start": fold.get("train_start"),
                        "train_end": fold.get("train_end"),
                        "val_start": fold.get("val_start"),
                        "val_end": fold.get("val_end"),
                        "regime": fold.get("regime"),
                        "metrics": fold.get("metrics", {}),
                    }
                    for fold in model.get("folds", [])
                ],
            }
            for model in results.get("models", [])
        },
    }
    write_json_with_aliases("wf_audit.json", wf_audit)

    evaluation = load_json(OUTPUT / "evaluation.json")
    approval_report = _build_random_forest_approval_report(results, evaluation, reference_coverage, event_semantic_coverage)
    write_json_with_aliases("approval_report_random_forest.json", approval_report)
    (AUDITS / "approval_report_random_forest.md").write_text(
        _approval_report_markdown(approval_report),
        encoding="utf-8",
    )
    paper_simulation = {
        "generated_at": generated_at,
        "mode": "historical_out_of_time_walk_forward",
        "target": results.get("target_name", "future_max_drawdown_20d"),
        "models": {
            name: {
                "auc": metrics.get("auc_mean"),
                "brier": metrics.get("brier_mean"),
                "ece": metrics.get("ece_mean"),
                "alert_precision": metrics.get("alert_precision_mean"),
                "drawdown_lift": metrics.get("drawdown_lift_mean"),
                "decision_useful": bool((metrics.get("drawdown_lift_mean") or 0) > 0 and (metrics.get("alert_precision_mean") or 0) >= 0.5),
            }
            for name, metrics in evaluation.get("models", {}).items()
        },
        "prospective_status": "paper_observations_enabled",
    }
    write_json_with_aliases("paper_simulation.json", paper_simulation)

    print(
        "Wrote data_coverage.json, label_coverage.json, event_feature_coverage.json, "
        "pit_audit.json, regime_breakdown.json, recent_window_breakdown.json"
    )
    return 0


def _selection_coverage(rows: list[dict], key_name: str) -> dict[str, dict[str, int | float]]:
    coverage: dict[str, dict[str, int | float]] = {}
    keys = sorted({row.get(key_name, "") for row in rows if row.get(key_name)})
    for key in keys:
        subset = [row for row in rows if row.get(key_name) == key]
        selected = sum(int(row.get("selected_for_training", "0")) for row in subset)
        coverage[key] = {
            "row_count": len(subset),
            "selected_for_training": selected,
            "selection_ratio": round(selected / len(subset), 4) if subset else 0.0,
        }
    return coverage


def _selection_coverage_from_samples(samples: list, key_name: str) -> dict[str, dict[str, int | float]]:
    counter = Counter(getattr(getattr(sample, key_name, None), "value", getattr(sample, key_name, "unknown")) for sample in samples)
    total = len(samples)
    return {
        str(key): {
            "row_count": count,
            "selection_ratio": round(count / total, 4) if total else 0.0,
        }
        for key, count in sorted(counter.items())
    }


def _sample_feature_coverage(samples: list) -> dict[str, float | int]:
    if not samples:
        return {"sample_count": 0, "mean_feature_coverage": 0.0}
    coverages = [float(getattr(sample, "feature_coverage", 1.0)) for sample in samples]
    return {
        "sample_count": len(samples),
        "mean_feature_coverage": round(sum(coverages) / len(coverages), 4),
        "min_feature_coverage": round(min(coverages), 4),
        "max_feature_coverage": round(max(coverages), 4),
    }


def _missing_feature_counts(samples: list) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for sample in samples:
        counter.update(getattr(sample, "missing_features", []))
    return dict(sorted(counter.items()))


def _market_event_feature_coverage(samples: list) -> dict[str, dict[str, float]]:
    coverage: dict[str, dict[str, float]] = {}
    for market in sorted({sample.market.value for sample in samples}):
        subset = [sample for sample in samples if sample.market.value == market]
        coverage[market] = {}
        for feature_name in _event_feature_names():
            non_zero = sum(1 for sample in subset if abs(sample.features.get(feature_name, 0.0)) > 1e-12)
            coverage[market][feature_name] = round(non_zero / len(subset), 4) if subset else 0.0
    return coverage


def _sample_provenance_coverage(samples: list) -> dict[str, float]:
    total = len(samples)
    if total == 0:
        return {}
    fields = ["provider", "published_at", "as_of", "raw_hash", "normalized_hash", "data_version"]
    return {
        field: round(sum(1 for sample in samples if getattr(sample, field, None) is not None) / total, 4)
        for field in fields
    }


def _bundle_provenance_coverage(bundle: dict) -> dict[str, dict[str, float]]:
    price_bars = list(bundle.get("price_bars", []))
    events = list(bundle.get("events", []))
    return {
        "price_bars": _record_provenance_coverage(price_bars),
        "events": _record_provenance_coverage(events),
    }


def _record_provenance_coverage(records: list) -> dict[str, float]:
    total = len(records)
    if total == 0:
        return {}
    fields = ["provider", "published_at", "as_of", "payload_ref", "source_url", "raw_hash", "normalized_hash", "data_version"]
    return {
        field: round(sum(1 for record in records if getattr(record, field, None) is not None) / total, 4)
        for field in fields
    }


def _regime_balance_summary(regime_breakdown: dict) -> dict:
    required = ["bull", "bear", "range", "high_vol"]
    fold_counts = {
        regime: int((regime_breakdown.get(regime) or {}).get("fold_count", 0))
        for regime in required
    }
    total = sum(fold_counts.values())
    non_zero = {regime: count for regime, count in fold_counts.items() if count > 0}
    max_count = max(non_zero.values()) if non_zero else 0
    min_count = min(non_zero.values()) if non_zero else 0
    return {
        "required_regimes": required,
        "fold_counts": fold_counts,
        "all_required_present": len(non_zero) == len(required),
        "dominant_regime": max(fold_counts, key=fold_counts.get) if fold_counts else None,
        "dominance_ratio": round(max_count / total, 4) if total else 0.0,
        "min_to_max_ratio": round(min_count / max_count, 4) if max_count else 0.0,
    }


def _build_random_forest_approval_report(
    results: dict,
    evaluation: dict,
    reference_coverage: dict,
    event_semantic_coverage: dict,
) -> dict:
    champion_name = "linear-baseline"
    challenger_name = "random-forest"
    models = {model.get("trainer_name"): model for model in results.get("models", [])}
    champion = models.get(champion_name, {})
    challenger = models.get(challenger_name, {})
    overall = {
        "champion": evaluation.get("models", {}).get(champion_name, {}),
        "challenger": evaluation.get("models", {}).get(challenger_name, {}),
        "delta": _metric_delta(
            evaluation.get("models", {}).get(challenger_name, {}),
            evaluation.get("models", {}).get(champion_name, {}),
        ),
    }
    regime_comparison = _fold_metric_comparison_by_dimension(challenger, champion, "regime")
    market_comparison = _model_breakdown_comparison(challenger, champion, "market_breakdown")
    coverage_group_comparison = _model_breakdown_comparison(challenger, champion, "coverage_group_breakdown")
    recent_comparison = _recent_window_comparison(
        results.get("recent_window_breakdown", {}).get(challenger_name, []),
        results.get("recent_window_breakdown", {}).get(champion_name, []),
    )
    required_regime_summary = _regime_balance_summary(results.get("regime_breakdown", {}))
    guardrails = {
        "challenger_exists": bool(challenger),
        "challenger_gate_eligible": bool(challenger.get("eligible_for_approval")),
        "required_regimes_present": required_regime_summary["all_required_present"],
        "reference_thresholds_clear": not bool(reference_coverage.get("reference_risk_flag")),
        "pit_clean": _pit_clean(),
        "market_comparison_available": bool(market_comparison),
        "coverage_group_comparison_available": bool(coverage_group_comparison),
    }
    guardrails["all_passed"] = all(
        value for key, value in guardrails.items()
    )
    return {
        "generated_at": results.get("generated_at"),
        "candidate": challenger_name,
        "champion": champion_name,
        "recommendation": "primary_approved" if guardrails["all_passed"] else "conditional_or_fallback_to_champion",
        "overall": overall,
        "regime_comparison": regime_comparison,
        "recent_window_comparison": recent_comparison,
        "market_comparison": market_comparison or {"status": "unavailable"},
        "coverage_group_comparison": coverage_group_comparison or {"status": "unavailable"},
        "reference_risk": reference_coverage,
        "event_semantic_coverage": event_semantic_coverage,
        "regime_balance": required_regime_summary,
        "guardrails": guardrails,
    }


def _metric_delta(candidate: dict, champion: dict) -> dict[str, float | None]:
    keys = ["auc_mean", "ece_mean", "brier_mean", "alert_precision_mean", "drawdown_lift_mean"]
    out: dict[str, float | None] = {}
    for key in keys:
        c_value = candidate.get(key)
        b_value = champion.get(key)
        out[key] = None if c_value is None or b_value is None else round(float(c_value) - float(b_value), 6)
    return out


def _model_breakdown_comparison(candidate: dict, champion: dict, field_name: str) -> dict[str, dict]:
    candidate_groups = candidate.get(field_name, {}) or {}
    champion_groups = champion.get(field_name, {}) or {}
    out: dict[str, dict] = {}
    for key in sorted(set(candidate_groups) | set(champion_groups)):
        out[key] = {
            "candidate": candidate_groups.get(key, {}),
            "champion": champion_groups.get(key, {}),
            "delta": _metric_delta(candidate_groups.get(key, {}), champion_groups.get(key, {})),
        }
    return out


def _fold_metric_comparison_by_dimension(candidate: dict, champion: dict, dimension: str) -> dict[str, dict]:
    candidate_groups = _fold_metric_means(candidate, dimension)
    champion_groups = _fold_metric_means(champion, dimension)
    out: dict[str, dict] = {}
    for key in sorted(set(candidate_groups) | set(champion_groups)):
        out[key] = {
            "candidate": candidate_groups.get(key, {}),
            "champion": champion_groups.get(key, {}),
            "delta": _metric_delta(candidate_groups.get(key, {}), champion_groups.get(key, {})),
        }
    return out


def _fold_metric_means(model: dict, dimension: str) -> dict[str, dict]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for fold in model.get("folds", []):
        key = str(fold.get(dimension, "unknown"))
        for metric_name, value in (fold.get("metrics", {}) or {}).items():
            if isinstance(value, (int, float)):
                grouped[key][metric_name].append(float(value))
    out: dict[str, dict] = {}
    mapping = {
        "auc_roc": "auc_mean",
        "expected_calibration_error": "ece_mean",
        "brier_score": "brier_mean",
        "top_bucket_alert_precision": "alert_precision_mean",
        "top_bucket_drawdown_lift": "drawdown_lift_mean",
    }
    for key, metrics in grouped.items():
        out[key] = {
            output_name: round(sum(metrics[source_name]) / len(metrics[source_name]), 6)
            for source_name, output_name in mapping.items()
            if metrics.get(source_name)
        }
        out[key]["fold_count"] = len([fold for fold in model.get("folds", []) if str(fold.get(dimension, "unknown")) == key])
    return out


def _recent_window_comparison(candidate_windows: list[dict], champion_windows: list[dict]) -> list[dict]:
    champion_by_fold = {item.get("fold_id"): item for item in champion_windows}
    out = []
    for candidate in candidate_windows:
        champion = champion_by_fold.get(candidate.get("fold_id"), {})
        out.append(
            {
                "fold_id": candidate.get("fold_id"),
                "validation_end": candidate.get("validation_end"),
                "regime": candidate.get("regime"),
                "candidate": candidate.get("metrics", {}),
                "champion": champion.get("metrics", {}),
                "delta": _metric_delta(
                    _normalize_metric_names(candidate.get("metrics", {})),
                    _normalize_metric_names(champion.get("metrics", {})),
                ),
            }
        )
    return out


def _normalize_metric_names(metrics: dict) -> dict:
    return {
        "auc_mean": metrics.get("auc_roc"),
        "ece_mean": metrics.get("expected_calibration_error"),
        "brier_mean": metrics.get("brier_score"),
        "alert_precision_mean": metrics.get("top_bucket_alert_precision"),
        "drawdown_lift_mean": metrics.get("top_bucket_drawdown_lift"),
    }


def _pit_clean() -> bool:
    report = load_json(AUDITS / "pit_audit.json")
    return int(report.get("failure_count", 0) or 0) == 0


def _approval_report_markdown(report: dict) -> str:
    overall = report.get("overall", {})
    challenger = overall.get("challenger", {})
    champion = overall.get("champion", {})
    guardrails = report.get("guardrails", {})
    lines = [
        "# Random Forest Approval Report",
        "",
        f"- Recommendation: `{report.get('recommendation')}`",
        f"- Candidate: `{report.get('candidate')}`",
        f"- Champion: `{report.get('champion')}`",
        f"- Guardrails all passed: `{guardrails.get('all_passed')}`",
        "",
        "## Overall",
        "",
        "| Metric | Champion | Random Forest | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ["auc_mean", "ece_mean", "brier_mean", "alert_precision_mean", "drawdown_lift_mean"]:
        lines.append(
            f"| {key} | {champion.get(key)} | {challenger.get(key)} | {overall.get('delta', {}).get(key)} |"
        )
    lines.extend(["", "## Guardrails", ""])
    for key, value in guardrails.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Notes", ""])
    lines.append("- Market and coverage-group comparisons are generated from persisted fold prediction summaries when available.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
