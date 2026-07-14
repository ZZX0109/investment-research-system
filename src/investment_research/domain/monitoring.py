from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AbstainReason(str, Enum):
    DATA_MISSING = "data_missing"
    INPUT_OUT_OF_RANGE = "input_out_of_range"
    CALIBRATION_FAILED = "calibration_failed"
    MODEL_UNSUPPORTED = "model_unsupported"
    SNAPSHOT_EXPIRED = "snapshot_expired"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    EVENT_COVERAGE_INCOMPLETE = "event_coverage_incomplete"


class RuntimeMetricSnapshot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    market: str
    decision_context: str
    task: str
    observed_at: datetime
    data_latency_seconds: float | None = None
    missing_rate: float
    coverage_ratio: float
    input_psi: float | None = None
    abstain_rate: float
    ece: float | None = None
    brier: float | None = None
    provider_switch_count: int = 0
    artifact_hash_ok: bool = True


class RuntimeRouteDecision(BaseModel):
    market: str
    decision_context: str
    task: str
    selected_tier: str
    selected_model_version: str | None = None
    abstain_reason: AbstainReason | None = None
    reasons: list[str] = Field(default_factory=list)


def choose_runtime_route(
    *,
    metric: RuntimeMetricSnapshot,
    primary_version: str | None,
    baseline_version: str | None,
    max_psi: float = 0.25,
    max_missing_rate: float = 0.2,
    min_coverage: float = 0.98,
) -> RuntimeRouteDecision:
    healthy = (
        metric.artifact_hash_ok
        and metric.missing_rate <= max_missing_rate
        and metric.coverage_ratio >= min_coverage
        and (metric.input_psi is None or metric.input_psi <= max_psi)
    )
    if healthy and primary_version:
        return RuntimeRouteDecision(
            market=metric.market,
            decision_context=metric.decision_context,
            task=metric.task,
            selected_tier="primary",
            selected_model_version=primary_version,
        )
    reasons = []
    if not metric.artifact_hash_ok:
        reasons.append("artifact_hash_mismatch")
    if metric.missing_rate > max_missing_rate:
        reasons.append("missing_rate_threshold")
    if metric.coverage_ratio < min_coverage:
        reasons.append("coverage_threshold")
    if metric.input_psi is not None and metric.input_psi > max_psi:
        reasons.append("input_psi_threshold")
    if baseline_version and metric.artifact_hash_ok:
        return RuntimeRouteDecision(
            market=metric.market,
            decision_context=metric.decision_context,
            task=metric.task,
            selected_tier="baseline",
            selected_model_version=baseline_version,
            reasons=reasons,
        )
    reason = (
        AbstainReason.ARTIFACT_HASH_MISMATCH
        if not metric.artifact_hash_ok
        else AbstainReason.DATA_MISSING
    )
    return RuntimeRouteDecision(
        market=metric.market,
        decision_context=metric.decision_context,
        task=metric.task,
        selected_tier="abstain",
        abstain_reason=reason,
        reasons=reasons,
    )
