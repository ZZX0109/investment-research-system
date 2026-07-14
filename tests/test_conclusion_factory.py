from datetime import datetime, timezone

import pytest

from investment_research.domain.base import Provenance
from investment_research.domain.enums import (
    AssetType,
    DataMode,
    DataSourceType,
    EvidenceType,
    JudgeVerdict,
    RecommendationAction,
    RiskLevel,
)
from investment_research.domain.models import Asset, Evidence, User
from investment_research.pipeline.conclusion_factory import AnalysisConclusionFactory
from investment_research.pipeline.model_inference import (
    ModelInferenceError,
    ModelInferenceResult,
)
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.pipeline.run_factory import AnalysisRunFactory


def provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="market-feed",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        confidence=0.95,
    )


def asset() -> Asset:
    return Asset(
        ticker="MSFT",
        name="Microsoft",
        asset_type=AssetType.EQUITY,
        provenance=provenance(),
    )


def user() -> User:
    return User(
        email="investor@example.com",
        display_name="Investor",
        auth_subject="user:investor@example.com",
        provenance=provenance(),
    )


def evidence_item(target_asset: Asset, title: str) -> Evidence:
    return Evidence(
        asset_id=target_asset.id,
        evidence_type=EvidenceType.RESEARCH_NOTE,
        title=title,
        summary=f"{title} summary",
        collected_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        provenance=provenance(),
    )


def snapshot(target_asset: Asset, **overrides) -> AnalysisSnapshot:
    values = {
        "asset_id": str(target_asset.id),
        "asset_snapshot": target_asset,
        "captured_at": datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
        "mode": "real",
        "provider": "persisted-market@1.0.0 | persisted-evidence@1.0.0",
        "as_of": datetime(2026, 7, 3, tzinfo=timezone.utc),
        "synthetic_ratio": 0.0,
        "data_modes": ["real"],
        "source_types": ["real"],
        "latest_close": 420.0,
        "latest_price_timestamp": datetime(2026, 7, 3, tzinfo=timezone.utc),
        "price_freshness_status": "fresh",
        "evidence_freshness_status": "fresh",
        "refresh_recommendation": "fresh_enough_for_current_mode",
        "synthetic_share": 0.0,
        "real_share": 1.0,
    }
    values.update(overrides)
    return AnalysisSnapshot(**values)


class StubInferenceService:
    def __init__(
        self, result: ModelInferenceResult | None = None, error: str | None = None
    ) -> None:
        self.result = result
        self.error = error

    def predict(self, frozen_snapshot: AnalysisSnapshot) -> ModelInferenceResult:
        if self.error:
            raise ModelInferenceError(self.error)
        assert self.result is not None
        return self.result


def approved_low_risk_prediction(**overrides) -> ModelInferenceResult:
    values = {
        "model_name": "linear-baseline",
        "model_version": "2026-07-08T08:21:00+00:00",
        "model_status": "approved",
        "deployment_approved": True,
        "target_name": "future_max_drawdown_20d",
        "manifest_version": "2026-07-08T08:21:00+00:00",
        "signal": "risk_low",
        "confidence": 0.9,
        "risk_probability": 0.22,
        "feature_coverage": 1.0,
        "missing_features": [],
        "inference_warnings": [],
        "rationale": "Approved model sees low drawdown risk.",
    }
    values.update(overrides)
    return ModelInferenceResult(**values)


def test_conclusion_factory_keeps_passed_low_risk_output_observational() -> None:
    target_asset = asset()
    evidence = [
        evidence_item(target_asset, "Channel checks"),
        evidence_item(target_asset, "Margin checks"),
    ]
    frozen_snapshot = snapshot(
        target_asset,
        evidence_snapshot=evidence,
        evidence_ids=[str(item.id) for item in evidence],
    )
    run = AnalysisRunFactory().build_run(
        asset=target_asset, user=user(), snapshot=frozen_snapshot, evidence=evidence
    )

    conclusions = AnalysisConclusionFactory(
        inference_service=StubInferenceService(approved_low_risk_prediction())
    ).build_outputs(
        asset=target_asset,
        run=run,
        snapshot=frozen_snapshot,
        evidence=evidence,
    )

    assert conclusions.prediction.model_name == "linear-baseline"
    assert conclusions.prediction.model_status == "approved"
    assert conclusions.prediction.deployment_approved is True
    assert conclusions.prediction.risk_probability == 0.22
    assert conclusions.prediction.confidence == 0.9
    assert conclusions.risk.risk_level == RiskLevel.LOW
    assert conclusions.risk.evidence_ids == [item.id for item in evidence]
    assert conclusions.judge.verdict == JudgeVerdict.PASS
    assert conclusions.judge.gating_reasons == []
    assert conclusions.recommendation.action == RecommendationAction.HOLD
    assert conclusions.recommendation.conviction == 0.9
    assert "Approved risk model" in conclusions.recommendation.reasoning
    assert conclusions.recommendation.guardrails == [
        "This risk assessment is not a buy or sell instruction."
    ]


def test_conclusion_factory_blocks_and_avoids_when_required_inputs_are_missing() -> (
    None
):
    target_asset = asset()
    frozen_snapshot = snapshot(
        target_asset,
        latest_close=None,
        latest_price_timestamp=None,
        synthetic_share=0.8,
        synthetic_ratio=0.8,
        real_share=0.2,
        evidence_snapshot=[],
        evidence_ids=[],
    )
    run = AnalysisRunFactory().build_run(
        asset=target_asset, user=user(), snapshot=frozen_snapshot, evidence=[]
    )

    conclusions = AnalysisConclusionFactory(
        inference_service=StubInferenceService(error="manifest missing")
    ).build_outputs(
        asset=target_asset,
        run=run,
        snapshot=frozen_snapshot,
        evidence=[],
    )

    assert conclusions.prediction.confidence == 0.0
    assert conclusions.prediction.signal == "risk_unavailable"
    assert conclusions.prediction.horizon == "20d"
    assert conclusions.prediction.model_name == "heuristic-fallback"
    assert conclusions.prediction.deployment_approved is False
    assert conclusions.risk.risk_level == RiskLevel.HIGH
    assert conclusions.judge.verdict == JudgeVerdict.BLOCK
    assert "Evidence set is empty" in conclusions.judge.gating_reasons
    assert "No persisted price series available" in conclusions.judge.gating_reasons
    assert "Synthetic data share exceeds 75%" in conclusions.judge.gating_reasons
    assert (
        "Prediction confidence below block threshold"
        in conclusions.judge.gating_reasons
    )
    assert (
        "Prediction model is not approved for deployment"
        in conclusions.judge.gating_reasons
    )
    assert "Prediction model status is fallback" in conclusions.judge.gating_reasons
    assert conclusions.recommendation.action == RecommendationAction.AVOID
    assert conclusions.recommendation.conviction == 0.2
    assert conclusions.recommendation.guardrails == conclusions.judge.gating_reasons
