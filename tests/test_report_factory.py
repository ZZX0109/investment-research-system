from datetime import datetime, timezone

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
from investment_research.domain.models import (
    Asset,
    Evidence,
    InvestmentRecommendation,
    JudgeScore,
    ModelPrediction,
    RiskConclusion,
    User,
)
from investment_research.pipeline.models import AnalysisBundle, AnalysisSnapshot
from investment_research.pipeline.run_factory import AnalysisRunFactory
from investment_research.report.factory import DEFAULT_REPORT_VERSION, ReportBuildOptions, ResearchReportFactory


def provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="market-feed",
        observed_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        confidence=0.92,
    )


def build_bundle() -> AnalysisBundle:
    asset = Asset(
        ticker="CRM",
        name="Salesforce",
        asset_type=AssetType.EQUITY,
        provenance=provenance(),
    )
    user = User(
        email="investor@example.com",
        display_name="Investor",
        auth_subject="user:investor@example.com",
        provenance=provenance(),
    )
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.RESEARCH_NOTE,
        title="Renewal checks",
        summary="Enterprise renewals remain resilient.",
        collected_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        provenance=provenance(),
    )
    snapshot = AnalysisSnapshot(
        asset_id=str(asset.id),
        asset_snapshot=asset,
        captured_at=datetime(2026, 7, 3, 12, tzinfo=timezone.utc),
        mode="real",
        provider="persisted-market@1.0.0 | persisted-evidence@1.0.0",
        as_of=datetime(2026, 7, 3, tzinfo=timezone.utc),
        overrides=["manual backfill"],
        synthetic_ratio=0.2,
        data_modes=["real"],
        source_types=["real", "backfilled"],
        latest_close=267.2,
        price_provider_name="persisted-market",
        price_provider_version="1.0.0",
        price_provider_status="fallback_backfilled",
        evidence_provider_name="persisted-evidence",
        evidence_provider_version="1.0.0",
        evidence_provider_status="available",
        fallback_reasons=["Real-time market data unavailable; analysis fell back to backfilled price history."],
        evidence_citation_ids=[str(evidence.id)],
        evidence_snapshot=[evidence],
    )
    run = AnalysisRunFactory().build_run(asset=asset, user=user, snapshot=snapshot, evidence=[evidence])
    prediction = ModelPrediction(
        asset_id=asset.id,
        analysis_run_id=run.id,
        model_name="heuristic-trend-ensemble",
        model_version="2026.07.0",
        horizon="90d",
        signal="outperform",
        confidence=0.71,
        rationale="Trend remains positive.",
        provenance=provenance(),
    )
    risk = RiskConclusion(
        asset_id=asset.id,
        analysis_run_id=run.id,
        risk_level=RiskLevel.MEDIUM,
        summary="Inputs include a backfilled market source.",
        evidence_ids=[evidence.id],
        provenance=provenance(),
    )
    recommendation = InvestmentRecommendation(
        asset_id=asset.id,
        analysis_run_id=run.id,
        action=RecommendationAction.HOLD,
        conviction=0.48,
        reasoning="Provider fallback keeps the run conservative.",
        guardrails=["Refresh live market data before action."],
        provenance=provenance(),
    )
    judge = JudgeScore(
        analysis_run_id=run.id,
        score=0.64,
        verdict=JudgeVerdict.WARN,
        gating_reasons=["Real-time market data unavailable; analysis fell back to backfilled price history."],
        provenance=provenance(),
    )
    return AnalysisBundle(
        asset=asset,
        run=run,
        snapshot=snapshot,
        source_meta=snapshot.source_meta,
        evidence=[evidence],
        predictions=[prediction],
        risk_conclusions=[risk],
        recommendations=[recommendation],
        judge_scores=[judge],
    )


def test_report_factory_builds_report_from_fixed_run_bundle() -> None:
    bundle = build_bundle()

    report = ResearchReportFactory().build_report(bundle)

    assert report.analysis_run_id == bundle.run.id
    assert report.report_version == DEFAULT_REPORT_VERSION
    assert report.title == "CRM Analysis Report"
    assert report.evidence_ids == [bundle.evidence[0].id]
    assert "Provider fallback keeps the run conservative." in report.thesis
    assert "judge=warn" in report.thesis
    assert "fallback-active:Real-time market data unavailable" in report.thesis
    assert f"- Run ID: `{bundle.run.id}`" in report.body_markdown
    assert f"- Snapshot hash: `{bundle.run.input_snapshot_hash}`" in report.body_markdown
    assert "- Source mode: real" in report.body_markdown
    assert "- Synthetic ratio: 0.20" in report.body_markdown
    assert "- Latest close: 267.20" in report.body_markdown
    assert "- Model: heuristic-trend-ensemble" in report.body_markdown
    assert "- Model status: unknown" in report.body_markdown
    assert "- Feature coverage: 1.00" in report.body_markdown
    assert "## Evidence References" in report.body_markdown
    assert "Renewal checks" in report.body_markdown


def test_report_factory_accepts_explicit_report_version() -> None:
    bundle = build_bundle()

    report = ResearchReportFactory().build_report(
        bundle,
        options=ReportBuildOptions(report_version="manual-review-2.0.0"),
    )

    assert report.report_version == "manual-review-2.0.0"
