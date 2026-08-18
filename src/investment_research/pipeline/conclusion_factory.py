from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from investment_research.domain.base import GenerationLink, Provenance
from investment_research.domain.enums import (
    JudgeVerdict,
    RecommendationAction,
    RiskLevel,
)
from investment_research.domain.models import (
    AnalysisRun,
    Asset,
    Evidence,
    InvestmentRecommendation,
    JudgeScore,
    ModelPrediction,
    RiskConclusion,
)
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.pipeline.model_inference import (
    APPROVED_STATUS,
    DeploymentModelInferenceService,
    ModelInferenceError,
    ModelInferenceResult,
)
from investment_research.pipeline.quality_gate import QualityGateService


PREDICTION_MODEL_NAME = "approved-deployment-model"
PREDICTION_MODEL_VERSION = "manifest"
FALLBACK_PREDICTION_MODEL_NAME = "heuristic-fallback"
FALLBACK_PREDICTION_MODEL_VERSION = "2026.07.0"


class AnalysisConclusionSet(BaseModel):
    prediction: ModelPrediction
    risk: RiskConclusion
    judge: JudgeScore
    recommendation: InvestmentRecommendation


class AnalysisConclusionFactory:
    """Build model, risk, judge, and recommendation outputs for a fixed analysis run."""

    def __init__(
        self,
        *,
        quality_gate: QualityGateService | None = None,
        inference_service: DeploymentModelInferenceService | None = None,
    ) -> None:
        self.quality_gate = quality_gate or QualityGateService()
        self.inference_service = inference_service or DeploymentModelInferenceService()

    def build_outputs(
        self,
        *,
        asset: Asset,
        run: AnalysisRun,
        snapshot: AnalysisSnapshot,
        evidence: list[Evidence],
    ) -> AnalysisConclusionSet:
        prediction = self.build_prediction(asset=asset, run=run, snapshot=snapshot)
        risk = self.build_risk(
            asset=asset,
            run=run,
            snapshot=snapshot,
            evidence=evidence,
            prediction=prediction,
        )
        judge = self.build_judge(
            run=run, snapshot=snapshot, prediction=prediction, evidence=evidence
        )
        recommendation = self.build_recommendation(
            asset=asset,
            run=run,
            snapshot=snapshot,
            prediction=prediction,
            risk=risk,
            judge=judge,
        )
        return AnalysisConclusionSet(
            prediction=prediction,
            risk=risk,
            judge=judge,
            recommendation=recommendation,
        )

    def build_prediction(
        self, *, asset: Asset, run: AnalysisRun, snapshot: AnalysisSnapshot
    ) -> ModelPrediction:
        try:
            inference = self.inference_service.predict(snapshot)
        except ModelInferenceError as exc:
            return self._fallback_prediction(
                asset=asset, run=run, snapshot=snapshot, reason=str(exc)
            )
        return self._prediction_from_inference(
            asset=asset, run=run, snapshot=snapshot, inference=inference
        )

    def _prediction_from_inference(
        self,
        *,
        asset: Asset,
        run: AnalysisRun,
        snapshot: AnalysisSnapshot,
        inference: ModelInferenceResult,
    ) -> ModelPrediction:
        return ModelPrediction(
            asset_id=asset.id,
            analysis_run_id=run.id,
            model_name=inference.model_name,
            model_version=inference.model_version,
            horizon="20d",
            signal=inference.signal,
            confidence=inference.confidence,
            rationale=inference.rationale,
            risk_probability=inference.risk_probability,
            model_status=inference.model_status,
            feature_coverage=inference.feature_coverage,
            missing_features=inference.missing_features,
            deployment_approved=inference.deployment_approved,
            manifest_version=inference.manifest_version,
            target_name=inference.target_name,
            inference_warnings=inference.inference_warnings,
            diagnostic=inference.diagnostic,
            provenance=self._derive_provenance(
                asset, producer="deployment_model", captured_at=snapshot.captured_at
            ),
        )

    def _fallback_prediction(
        self,
        *,
        asset: Asset,
        run: AnalysisRun,
        snapshot: AnalysisSnapshot,
        reason: str,
    ) -> ModelPrediction:
        return ModelPrediction(
            asset_id=asset.id,
            analysis_run_id=run.id,
            model_name=FALLBACK_PREDICTION_MODEL_NAME,
            model_version=FALLBACK_PREDICTION_MODEL_VERSION,
            horizon="20d",
            signal="risk_unavailable",
            confidence=0.0,
            rationale=(
                "Deployment risk model unavailable. This run must abstain from directional or "
                f"risk classification output. reason={reason}"
            ),
            risk_probability=None,
            model_status="fallback",
            feature_coverage=0.0,
            missing_features=[],
            deployment_approved=False,
            manifest_version=None,
            target_name=None,
            inference_warnings=[f"Deployment model unavailable: {reason}"],
            provenance=self._derive_provenance(
                asset, producer="prediction_model", captured_at=snapshot.captured_at
            ),
        )

    def build_risk(
        self,
        *,
        asset: Asset,
        run: AnalysisRun,
        snapshot: AnalysisSnapshot,
        evidence: list[Evidence],
        prediction: ModelPrediction | None = None,
    ) -> RiskConclusion:
        risk_level = RiskLevel.LOW
        summary = "Available data supports a stable baseline view."
        if prediction and not prediction.deployment_approved:
            risk_level = RiskLevel.HIGH
            summary = "The approved deployment model is unavailable, so the run cannot provide a complete risk classification."
        elif (
            prediction
            and prediction.risk_probability is not None
            and prediction.risk_probability >= 0.65
        ):
            risk_level = RiskLevel.HIGH
            summary = "The approved model flags elevated future drawdown risk for this frozen run."
        elif snapshot.synthetic_share > 0.5 or len(evidence) < 1:
            risk_level = RiskLevel.HIGH
            summary = "The run depends heavily on synthetic or sparse evidence, so conclusions should be treated cautiously."
        elif (
            prediction
            and prediction.risk_probability is not None
            and prediction.risk_probability >= 0.45
        ):
            risk_level = RiskLevel.MEDIUM
            summary = "The approved model flags moderate future drawdown risk, so the thesis should remain guarded."
        elif (
            snapshot.price_freshness_status == "stale"
            or snapshot.evidence_freshness_status == "stale"
        ):
            risk_level = RiskLevel.MEDIUM
            summary = "Inputs are aging and may no longer reflect current conditions."
        return RiskConclusion(
            asset_id=asset.id,
            analysis_run_id=run.id,
            risk_level=risk_level,
            summary=summary,
            evidence_ids=[item.id for item in evidence],
            stale_after=None
            if snapshot.latest_price_timestamp is None
            else snapshot.latest_price_timestamp + timedelta(days=7),
            provenance=self._derive_provenance(
                asset, producer="risk_engine", captured_at=snapshot.captured_at
            ),
        )

    def build_judge(
        self,
        *,
        run: AnalysisRun,
        snapshot: AnalysisSnapshot,
        prediction: ModelPrediction,
        evidence: list[Evidence],
    ) -> JudgeScore:
        gate_result = self.quality_gate.evaluate(
            snapshot=snapshot,
            prediction=prediction,
            evidence_count=len(evidence),
        )
        return JudgeScore(
            analysis_run_id=run.id,
            score=gate_result.score,
            verdict=gate_result.verdict,
            gating_reasons=gate_result.gating_reasons,
            provenance=run.provenance,
        )

    def build_recommendation(
        self,
        *,
        asset: Asset,
        run: AnalysisRun,
        snapshot: AnalysisSnapshot,
        prediction: ModelPrediction,
        risk: RiskConclusion,
        judge: JudgeScore,
    ) -> InvestmentRecommendation:
        action = RecommendationAction.HOLD
        reasoning = (
            "The pipeline defaults to hold until data quality gates are cleared."
        )
        conviction = max(0.2, prediction.confidence - 0.2)
        guardrails: list[str] = []
        if judge.verdict == JudgeVerdict.BLOCK:
            action = RecommendationAction.AVOID
            reasoning = "Judge blocked the conclusion because the run failed minimum data-quality requirements."
            conviction = 0.2
            guardrails.extend(judge.gating_reasons)
        elif judge.verdict == JudgeVerdict.HOLD:
            action = RecommendationAction.HOLD
            reasoning = "Judge downgraded the run to HOLD because evidence freshness or data quality is not sufficient."
            conviction = min(conviction, 0.35)
            guardrails.extend(judge.gating_reasons)
        elif judge.verdict == JudgeVerdict.WARN:
            action = RecommendationAction.HOLD
            reasoning = "Judge issued a warning, so the conclusion remains conservative until stronger inputs arrive."
            conviction = min(conviction, 0.5)
            guardrails.extend(judge.gating_reasons)
        elif risk.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            action = RecommendationAction.AVOID
            reasoning = "Risk gating downgrades the conclusion because the run leans on synthetic or incomplete inputs."
            guardrails.append(
                "Require fresher real-market inputs before taking action."
            )
            guardrails.extend(snapshot.fallback_reasons)
        elif snapshot.fallback_reasons:
            reasoning = "Provider fallback kept the run reproducible, but the conclusion remains downgraded until preferred real inputs recover."
            guardrails.extend(snapshot.fallback_reasons)
        elif (
            prediction.deployment_approved
            and prediction.model_status == APPROVED_STATUS
            and prediction.signal == "risk_low"
            and prediction.confidence > 0.7
            and snapshot.real_share >= 0.5
        ):
            action = RecommendationAction.HOLD
            reasoning = "Approved risk model and stronger real-data coverage indicate lower drawdown risk; keep the asset under observation and evaluate the stated conditions."
            conviction = min(0.9, prediction.confidence)
            guardrails.append("This risk assessment is not a buy or sell instruction.")
        return InvestmentRecommendation(
            asset_id=asset.id,
            analysis_run_id=run.id,
            action=action,
            conviction=conviction,
            reasoning=reasoning,
            guardrails=guardrails,
            provenance=self._derive_provenance(
                asset,
                producer="recommendation_engine",
                captured_at=snapshot.captured_at,
            ),
        )

    def _derive_provenance(
        self, asset: Asset, *, producer: str, captured_at
    ) -> Provenance:
        provenance = asset.provenance.model_copy(deep=True)
        provenance.observed_at = captured_at
        provenance.generation_chain = [
            *provenance.generation_chain,
            GenerationLink(step="analysis", producer=producer, version="1.0.0"),
        ]
        return provenance
