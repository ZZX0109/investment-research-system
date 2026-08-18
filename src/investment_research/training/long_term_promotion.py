"""Fail-closed promotion checks for the long-term research candidate."""

from __future__ import annotations

from typing import Any

from investment_research.training.long_term_config import LongTermTrainingConfig


def evaluate_long_term_promotion(
    report: dict[str, Any],
    *,
    valid_shadow_sessions: int,
    config: LongTermTrainingConfig,
) -> dict[str, Any]:
    reasons: list[str] = []
    if report.get("status") != "research_only":
        reasons.append("training_report_not_research_only")
    if report.get("deployment_ready") is not False:
        reasons.append("training_report_deployment_flag_invalid")
    if valid_shadow_sessions < config.minimum_shadow_sessions:
        reasons.append(f"shadow_sessions_below_{config.minimum_shadow_sessions}")
    models = report.get("models") if isinstance(report.get("models"), dict) else {}
    eligible_models: list[str] = []
    for name, model in models.items():
        if not isinstance(model, dict) or model.get("status") != "research_only":
            continue
        metrics = model.get("holdout_metrics") or {}
        # Sequence evaluation prefixes drawdown ranking metrics with
        # ``risk_`` while the tabular baseline report uses the common names.
        # Accept both representations so a drawdown task is not silently
        # excluded from the same cost/rank promotion contract as return tasks.
        rank_ic = metrics.get("rank_ic")
        if rank_ic is None:
            rank_ic = metrics.get("risk_rank_ic")
        net_return = metrics.get("top_k_excess_return_after_cost")
        if net_return is None:
            net_return = metrics.get("risk_top_k_excess_return_after_cost")
        if rank_ic is None or rank_ic < config.minimum_rank_ic:
            continue
        if net_return is None or net_return <= config.minimum_cost_adjusted_return:
            continue
        eligible_models.append(name)
    if not eligible_models:
        reasons.append("no_holdout_model_passes_cost_and_rank_thresholds")
    return {
        "schema_version": "long-term-promotion-evaluation-v1",
        "status": "candidate_for_review" if not reasons else "blocked",
        "research_only": True,
        "deployment_ready": False,
        "valid_shadow_sessions": valid_shadow_sessions,
        "minimum_shadow_sessions": config.minimum_shadow_sessions,
        "eligible_models": sorted(eligible_models),
        "blocking_reasons": sorted(set(reasons)),
        "policy": {
            "minimum_rank_ic": config.minimum_rank_ic,
            "minimum_cost_adjusted_return": config.minimum_cost_adjusted_return,
        },
    }
