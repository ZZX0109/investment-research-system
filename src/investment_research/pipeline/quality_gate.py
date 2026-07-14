from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from investment_research.domain.enums import JudgeVerdict
from investment_research.domain.models import ModelPrediction
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.service.data_mode import DataModePolicyService


class QualityGateInput(BaseModel):
    data_modes: list[str] = Field(default_factory=list)
    fallback_reasons: list[str] = Field(default_factory=list)
    evidence_count: int = Field(ge=0)
    synthetic_share: float = Field(ge=0.0, le=1.0)
    real_share: float = Field(ge=0.0, le=1.0)
    latest_price_timestamp: datetime | None = None
    price_freshness_status: str = "unknown"
    evidence_freshness_status: str = "unknown"
    prediction_confidence: float = Field(ge=0.0, le=1.0)
    model_status: str = "approved"
    deployment_approved: bool = True
    feature_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    missing_features: list[str] = Field(default_factory=list)
    inference_warnings: list[str] = Field(default_factory=list)


class QualityGateResult(BaseModel):
    verdict: JudgeVerdict
    score: float = Field(ge=0.0, le=1.0)
    gating_reasons: list[str] = Field(default_factory=list)


class QualityGateService:
    """Reusable quality gate for turning run inputs into a Judge verdict."""

    def __init__(self, mode_policy: DataModePolicyService | None = None) -> None:
        self.mode_policy = mode_policy or DataModePolicyService()

    def evaluate(
        self,
        *,
        snapshot: AnalysisSnapshot,
        prediction: ModelPrediction,
        evidence_count: int,
    ) -> QualityGateResult:
        return self.evaluate_input(
            QualityGateInput(
                data_modes=snapshot.data_modes,
                fallback_reasons=snapshot.fallback_reasons,
                evidence_count=evidence_count,
                synthetic_share=snapshot.synthetic_share,
                real_share=snapshot.real_share,
                latest_price_timestamp=snapshot.latest_price_timestamp,
                price_freshness_status=snapshot.price_freshness_status,
                evidence_freshness_status=snapshot.evidence_freshness_status,
                prediction_confidence=prediction.confidence,
                model_status=prediction.model_status,
                deployment_approved=prediction.deployment_approved,
                feature_coverage=prediction.feature_coverage,
                missing_features=prediction.missing_features,
                inference_warnings=prediction.inference_warnings,
            )
        )

    def evaluate_input(self, gate_input: QualityGateInput) -> QualityGateResult:
        gating_reasons = self.mode_policy.build_judge_mode_gates(gate_input.data_modes)
        gating_reasons.extend(gate_input.fallback_reasons)

        if gate_input.evidence_count == 0:
            gating_reasons.append("Evidence set is empty")
        elif gate_input.evidence_count < 2:
            gating_reasons.append("Evidence set is insufficient")

        if gate_input.synthetic_share >= 0.75:
            gating_reasons.append("Synthetic data share exceeds 75%")
        elif gate_input.synthetic_share > 0.5:
            gating_reasons.append("Synthetic data share exceeds 50%")

        if gate_input.real_share < 0.4:
            gating_reasons.append("Real data share below 40%")

        if gate_input.latest_price_timestamp is None:
            gating_reasons.append("No persisted price series available")
        elif gate_input.price_freshness_status == "stale":
            gating_reasons.append("Latest price data is older than 7 days")

        if gate_input.evidence_freshness_status == "stale":
            gating_reasons.append("Latest evidence data is older than freshness policy allows")

        if gate_input.prediction_confidence < 0.45:
            gating_reasons.append("Prediction confidence below block threshold")
        elif gate_input.prediction_confidence < 0.55:
            gating_reasons.append("Prediction confidence below quality threshold")

        if not gate_input.deployment_approved:
            gating_reasons.append("Prediction model is not approved for deployment")
        if gate_input.model_status != "approved":
            gating_reasons.append(f"Prediction model status is {gate_input.model_status}")
        if gate_input.feature_coverage < 0.5:
            gating_reasons.append("Model feature coverage below minimum threshold")
        elif gate_input.feature_coverage < 0.75:
            gating_reasons.append("Model feature coverage below quality threshold")
        gating_reasons.extend(gate_input.inference_warnings)

        score = self._score(gate_input=gate_input, gating_reasons=gating_reasons)
        return QualityGateResult(
            verdict=self._verdict(gate_input=gate_input, gating_reasons=gating_reasons),
            score=score,
            gating_reasons=gating_reasons,
        )

    def _score(self, *, gate_input: QualityGateInput, gating_reasons: list[str]) -> float:
        penalty = 0.12 * len(gating_reasons)
        return max(0.15, min(0.95, gate_input.prediction_confidence - penalty + gate_input.real_share * 0.2))

    def _verdict(self, *, gate_input: QualityGateInput, gating_reasons: list[str]) -> JudgeVerdict:
        if not gating_reasons:
            return JudgeVerdict.PASS
        if (
            gate_input.latest_price_timestamp is None
            or gate_input.evidence_count == 0
            or gate_input.synthetic_share >= 0.75
            or gate_input.prediction_confidence < 0.45
            or not gate_input.deployment_approved
        ):
            return JudgeVerdict.BLOCK
        if (
            gate_input.price_freshness_status == "stale"
            or gate_input.evidence_freshness_status == "stale"
            or gate_input.real_share < 0.25
            or gate_input.feature_coverage < 0.5
            or gate_input.feature_coverage < 0.75
        ):
            return JudgeVerdict.HOLD
        return JudgeVerdict.WARN
