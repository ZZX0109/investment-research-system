from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field


class GateDecision(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


class DirectionGateEvidence(BaseModel):
    macro_f1: float
    balanced_accuracy: float
    log_loss: float
    ece: float
    best_simple_baseline_macro_f1: float
    regime_macro_f1: dict[str, float]
    recent_window_macro_f1: list[float]


def evaluate_direction_gate(evidence: DirectionGateEvidence) -> GateDecision:
    reasons: list[str] = []
    if evidence.macro_f1 < 0.45:
        reasons.append("macro_f1_below_0.45")
    if evidence.balanced_accuracy < 0.45:
        reasons.append("balanced_accuracy_below_0.45")
    if evidence.log_loss > 1.05:
        reasons.append("log_loss_above_1.05")
    if evidence.ece > 0.15:
        reasons.append("ece_above_0.15")
    if any(value < 0.35 for value in evidence.regime_macro_f1.values()):
        reasons.append("regime_macro_f1_below_0.35")
    if len(evidence.recent_window_macro_f1) < 2 or any(
        value < 0.40 for value in evidence.recent_window_macro_f1[-2:]
    ):
        reasons.append("recent_window_macro_f1_below_0.40")
    if evidence.macro_f1 + 1e-12 < evidence.best_simple_baseline_macro_f1:
        reasons.append("weaker_than_best_simple_baseline")
    return GateDecision(passed=not reasons, reasons=reasons)


class ReturnGateEvidence(BaseModel):
    mean_pinball_loss: float
    best_baseline_pinball_loss: float
    p50_mae: float
    best_baseline_p50_mae: float
    direction_accuracy: float
    best_baseline_direction_accuracy: float
    spearman_ic: float
    interval_coverage: float
    group_pinball_loss: dict[str, float]
    group_baseline_pinball_loss: dict[str, float]
    holdout_12m_passed: bool
    stress_6m_passed: bool


def evaluate_return_gate(evidence: ReturnGateEvidence) -> GateDecision:
    reasons: list[str] = []
    if evidence.mean_pinball_loss >= evidence.best_baseline_pinball_loss:
        reasons.append("pinball_loss_not_better_than_baseline")
    if evidence.p50_mae > evidence.best_baseline_p50_mae:
        reasons.append("p50_mae_worse_than_baseline")
    if evidence.direction_accuracy < evidence.best_baseline_direction_accuracy:
        reasons.append("direction_accuracy_worse_than_baseline")
    if evidence.spearman_ic <= 0:
        reasons.append("spearman_ic_not_positive")
    if not 0.75 <= evidence.interval_coverage <= 0.85:
        reasons.append("p10_p90_coverage_outside_75_85pct")
    for group, value in evidence.group_pinball_loss.items():
        baseline = evidence.group_baseline_pinball_loss.get(group)
        if baseline is None or value > baseline * 1.05:
            reasons.append(f"group_pinball_loss_exceeds_baseline:{group}")
    if not evidence.holdout_12m_passed:
        reasons.append("holdout_12m_not_passed")
    if not evidence.stress_6m_passed:
        reasons.append("stress_6m_not_passed")
    return GateDecision(passed=not reasons, reasons=reasons)


class RegimeAurocObservation(BaseModel):
    regime: str
    fold_id: str
    model_name: str
    algorithm_family: str
    auroc: float


class DeepRegimeGateResult(BaseModel):
    passed: bool
    deep_regime_auroc: dict[str, float]
    best_tabular_regime_auroc: dict[str, float]
    regime_deltas: dict[str, float]
    qualifying_regimes: list[str]
    required_regime_count: int
    minimum_delta: float


class DeepClassificationPromotionEvidence(BaseModel):
    observations: list[RegimeAurocObservation]
    deep_model_name: str
    best_tabular_brier: float
    deep_brier: float
    best_tabular_ece: float
    deep_ece: float
    best_tabular_coverage: float
    deep_coverage: float
    seed_aurocs: dict[int, float]


class DeepReturnPromotionEvidence(BaseModel):
    best_tabular_pinball_loss: float
    deep_pinball_loss: float
    regime_improvement_ratios: dict[str, float]
    seed_pinball_losses: dict[int, float]


def evaluate_deep_regime_gate(
    observations: list[RegimeAurocObservation],
    *,
    deep_model_name: str,
    deep_families: set[str],
    required_regime_count: int = 2,
    minimum_delta: float = 0.03,
) -> DeepRegimeGateResult:
    """Aggregate every matching fold by regime before comparing model families."""
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    family_by_model: dict[str, str] = {}
    for item in observations:
        grouped[(item.model_name, item.regime)].append(item.auroc)
        family_by_model[item.model_name] = item.algorithm_family
    means = {
        key: sum(values) / len(values)
        for key, values in grouped.items()
        if values
    }
    deep = {
        regime: value
        for (model, regime), value in means.items()
        if model == deep_model_name
    }
    tabular: dict[str, float] = {}
    for (model, regime), value in means.items():
        if family_by_model.get(model) in deep_families:
            continue
        tabular[regime] = max(tabular.get(regime, float("-inf")), value)
    shared = sorted(set(deep) & set(tabular))
    deltas = {regime: deep[regime] - tabular[regime] for regime in shared}
    qualifying = sorted(
        regime for regime, delta in deltas.items() if delta + 1e-12 >= minimum_delta
    )
    return DeepRegimeGateResult(
        passed=len(qualifying) >= required_regime_count,
        deep_regime_auroc={key: deep[key] for key in sorted(deep)},
        best_tabular_regime_auroc={key: tabular[key] for key in sorted(tabular)},
        regime_deltas=deltas,
        qualifying_regimes=qualifying,
        required_regime_count=required_regime_count,
        minimum_delta=minimum_delta,
    )


def evaluate_deep_classification_promotion(
    evidence: DeepClassificationPromotionEvidence,
    *,
    deep_families: set[str] | None = None,
) -> GateDecision:
    regime = evaluate_deep_regime_gate(
        evidence.observations, deep_model_name=evidence.deep_model_name,
        deep_families=deep_families or {"mlp", "patchtst", "tcn", "itransformer", "deep_learning"},
        required_regime_count=2, minimum_delta=0.03,
    )
    reasons = [] if regime.passed else ["deep_model_lacks_two_regime_auroc_delta_0.03"]
    if evidence.deep_brier > evidence.best_tabular_brier + 1e-12:
        reasons.append("deep_brier_worse_than_tabular")
    if evidence.deep_ece > evidence.best_tabular_ece + 1e-12:
        reasons.append("deep_ece_worse_than_tabular")
    if evidence.best_tabular_coverage - evidence.deep_coverage > 0.02 + 1e-12:
        reasons.append("deep_coverage_drop_exceeds_2pp")
    if set(evidence.seed_aurocs) != {42, 2026, 3407}:
        reasons.append("deep_three_seed_evidence_missing")
    elif max(evidence.seed_aurocs.values()) - min(evidence.seed_aurocs.values()) > 0.03:
        reasons.append("deep_seed_auroc_unstable")
    return GateDecision(passed=not reasons, reasons=reasons)


def evaluate_deep_return_promotion(evidence: DeepReturnPromotionEvidence) -> GateDecision:
    reasons: list[str] = []
    improvement = 1 - evidence.deep_pinball_loss / max(evidence.best_tabular_pinball_loss, 1e-12)
    if improvement < 0.05:
        reasons.append("deep_pinball_improvement_below_5pct")
    qualifying = [name for name, value in evidence.regime_improvement_ratios.items() if value >= 0.05]
    if len(qualifying) < 2:
        reasons.append("deep_return_lacks_two_regime_5pct_improvements")
    if set(evidence.seed_pinball_losses) != {42, 2026, 3407}:
        reasons.append("deep_three_seed_evidence_missing")
    elif max(evidence.seed_pinball_losses.values()) / max(min(evidence.seed_pinball_losses.values()), 1e-12) - 1 > 0.05:
        reasons.append("deep_seed_pinball_unstable")
    return GateDecision(passed=not reasons, reasons=reasons)
