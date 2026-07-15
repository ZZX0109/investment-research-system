"""Evidence helpers for the zero-budget CN research workflow."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


REGIMES = ("bull", "bear", "range", "high_vol")


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


def classify_market_regime(sample) -> str:
    volatility = float(sample.features.get("vol_20d", sample.features.get("realized_vol_20d", 0.0)))
    benchmark = float(sample.features.get("benchmark_ret_20d", 0.0))
    if volatility >= 0.30:
        return "high_vol"
    if benchmark >= 0.03:
        return "bull"
    if benchmark <= -0.03:
        return "bear"
    return "range"


def feature_coverage_report(samples: list) -> dict[str, Any]:
    feature_names = sorted({key for sample in samples for key in sample.features})
    rows = []
    for name in feature_names:
        values = [sample.features.get(name) for sample in samples]
        present = [value for value in values if value is not None]
        rows.append({
            "feature": name,
            "missing_ratio": 1 - len(present) / len(samples),
            "non_zero_ratio": sum(value not in (None, 0, 0.0) for value in values) / len(samples),
        })
    return {
        "sample_count": len(samples),
        "feature_count": len(feature_names),
        "mean_feature_coverage": (
            sum(float(getattr(sample, "feature_coverage", 1.0)) for sample in samples) / len(samples)
            if samples else 0.0
        ),
        "features": rows,
    }


def research_scope_reports(
    *, task: str, result: Any, samples: list, dataset_hash: str,
    snapshot_hash: str, cohort: str,
) -> dict[str, dict[str, Any]]:
    selected = next(item for item in result.candidates if item.name == result.selected_candidate)
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
        "ablation": {
            "status": "recorded_candidate_comparison",
            "candidate_count": len(result.candidates),
            "feature_group_ablation_available": False,
            "reason": "free_research_v1_preserves_missing_coverage_instead_of_claiming_ablation",
        },
        "calibration": {
            "source": "time_oof_only", "selected_candidate": selected.name,
            "ece": getattr(selected, "ece", None),
        },
        "market_industry_regime": {
            "market": "cn", "industry_status": "free_source_incomplete",
            "selected_regime_metrics": getattr(selected, "regime_metrics", {}),
            "regime_counts": {name: sum(classify_market_regime(item) == name for item in samples) for name in REGIMES},
        },
        "holdout_12m": {
            "evaluated_once": True,
            "observation_count": len(getattr(result, "holdout_labels", getattr(result, "holdout_targets", []))),
        },
        "stress_6m": {
            "subset_of_holdout": True,
            "observation_count": len(getattr(result, "stress_labels", getattr(result, "stress_targets", []))),
        },
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


def select_research_roster_candidates(task: str, result: Any) -> tuple[str, str, list[str]]:
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
        regime_values = [item.get("macro_f1", 0.0) for item in selected.regime_metrics.values()]
        passed = (
            selected.macro_f1 >= 0.45 and selected.balanced_accuracy >= 0.45
            and selected.log_loss <= 1.05 and selected.ece <= 0.15
            and selected.macro_f1 >= best_baseline.macro_f1
            and regime_values and min(regime_values) >= 0.35
            and _direction_macro_f1(result.holdout_probabilities, result.holdout_labels) >= 0.40
            and _direction_macro_f1(result.stress_probabilities, result.stress_labels) >= 0.40
        )
    elif task == "return_20d":
        best_baseline = min(present_baselines, key=lambda item: item.mean_pinball_loss)
        selected = candidates[result.selected_candidate]
        passed = (
            selected.mean_pinball_loss < best_baseline.mean_pinball_loss
            and selected.p50_mae <= best_baseline.p50_mae
            and selected.direction_accuracy >= best_baseline.direction_accuracy
            and 0.75 <= selected.interval_coverage <= 0.85
            and selected.spearman_ic > 0
            and all(
                value["mean_pinball_loss"]
                <= best_baseline.regime_metrics.get(regime, value)["mean_pinball_loss"] * 1.05
                for regime, value in selected.regime_metrics.items()
            )
        )
    else:
        best_baseline = min(present_baselines, key=lambda item: item.brier)
        selected = candidates[result.selected_candidate]
        positive_regimes = sum(
            float(values.get("drawdown_lift") or 0.0) > 0
            for values in selected.regime_metrics.values()
        )
        passed = (
            (selected.auroc or 0.0) >= 0.68 and selected.alert_precision >= 0.50
            and selected.ece <= 0.15 and selected.brier <= best_baseline.brier + 0.01
            and selected.drawdown_lift > 0 and positive_regimes >= 3
        )
    primary = selected if passed else best_baseline
    fallback = next(item for item in present_baselines if item.name != primary.name)
    challengers = [
        item.name for item in result.candidates
        if item.name not in {primary.name, fallback.name, "time-oof-weighted-ensemble"}
    ]
    return primary.name, fallback.name, challengers


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
