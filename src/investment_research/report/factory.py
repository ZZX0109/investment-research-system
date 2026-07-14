from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from investment_research.domain.base import Provenance
from investment_research.domain.models import ResearchReport
from investment_research.pipeline.models import AnalysisBundle


DEFAULT_REPORT_VERSION = "auto-1.0.0"


class ReportBuildOptions(BaseModel):
    report_version: str = Field(default=DEFAULT_REPORT_VERSION, min_length=1)


class ReportContent(BaseModel):
    title: str
    thesis: str
    body_markdown: str
    evidence_ids: list[UUID] = Field(default_factory=list)


class ResearchReportFactory:
    """Build fixed-run report records from immutable analysis bundles."""

    def build_report(
        self,
        bundle: AnalysisBundle,
        *,
        options: ReportBuildOptions | None = None,
    ) -> ResearchReport:
        resolved_options = options or ReportBuildOptions()
        content = self.render_content(bundle)
        return ResearchReport(
            asset_id=bundle.asset.id,
            analysis_run_id=bundle.run.id,
            title=content.title,
            thesis=content.thesis,
            evidence_ids=content.evidence_ids,
            report_version=resolved_options.report_version,
            body_markdown=content.body_markdown,
            provenance=Provenance.model_validate(bundle.run.provenance.model_dump()),
        )

    def render_content(self, bundle: AnalysisBundle) -> ReportContent:
        return ReportContent(
            title=f"{bundle.asset.ticker} Analysis Report",
            thesis=self._build_thesis(bundle),
            body_markdown=self._render_markdown(bundle),
            evidence_ids=[item.id for item in bundle.evidence],
        )

    def _build_thesis(self, bundle: AnalysisBundle) -> str:
        recommendation = bundle.recommendations[0] if bundle.recommendations else None
        judge = bundle.judge_scores[0] if bundle.judge_scores else None
        fallback = (
            "fallback-cleared"
            if not bundle.snapshot.fallback_reasons
            else f"fallback-active:{'; '.join(bundle.snapshot.fallback_reasons)}"
        )
        verdict = judge.verdict.value if judge else "unknown"
        reasoning = (
            recommendation.reasoning
            if recommendation
            else "No recommendation available."
        )
        return f"{reasoning} | judge={verdict} | {fallback}"

    def _render_markdown(self, bundle: AnalysisBundle) -> str:
        judge = bundle.judge_scores[0] if bundle.judge_scores else None
        prediction = bundle.predictions[0] if bundle.predictions else None
        risk = bundle.risk_conclusions[0] if bundle.risk_conclusions else None
        recommendation = bundle.recommendations[0] if bundle.recommendations else None
        evidence_titles = ", ".join(item.title for item in bundle.evidence) or "None"
        evidence_references = (
            [
                f"- `{item.id}` | {item.title} | collected_at={item.collected_at.isoformat()}"
                for item in bundle.evidence
            ]
            if bundle.evidence
            else ["- None"]
        )
        gating = (
            ", ".join(judge.gating_reasons)
            if judge and judge.gating_reasons
            else "None"
        )
        latest_close = (
            "n/a"
            if bundle.snapshot.latest_close is None
            else f"{bundle.snapshot.latest_close:.2f}"
        )
        risk_probability = (
            "n/a"
            if prediction is None or prediction.risk_probability is None
            else f"{prediction.risk_probability:.2%}"
        )
        missing_features = (
            "None"
            if prediction is None or not prediction.missing_features
            else ", ".join(prediction.missing_features)
        )
        inference_warnings = (
            "None"
            if prediction is None or not prediction.inference_warnings
            else ", ".join(prediction.inference_warnings)
        )
        return "\n".join(
            [
                f"# {bundle.asset.ticker} Analysis Run",
                "",
                f"- Run ID: `{bundle.run.id}`",
                f"- Snapshot hash: `{bundle.run.input_snapshot_hash or 'n/a'}`",
                f"- Model version: {bundle.run.model_version or 'n/a'}",
                f"- Source mode: {bundle.snapshot.mode}",
                f"- Source provider: {bundle.snapshot.provider}",
                f"- Source as-of: {bundle.snapshot.as_of.isoformat() if bundle.snapshot.as_of else 'n/a'}",
                f"- Source overrides: {', '.join(bundle.snapshot.overrides) or 'None'}",
                f"- Synthetic ratio: {bundle.snapshot.synthetic_ratio:.2f}",
                f"- Data modes: {', '.join(bundle.snapshot.data_modes) or 'unknown'}",
                f"- Source types: {', '.join(bundle.snapshot.source_types) or 'unknown'}",
                f"- Intake strategy: {bundle.snapshot.intake_strategy}",
                f"- Price provider: {bundle.snapshot.price_provider_name}@{bundle.snapshot.price_provider_version}",
                f"- Price provider status: {bundle.snapshot.price_provider_status}",
                f"- Evidence provider: {bundle.snapshot.evidence_provider_name}@{bundle.snapshot.evidence_provider_version}",
                f"- Evidence provider status: {bundle.snapshot.evidence_provider_status}",
                f"- Price freshness: {bundle.snapshot.price_freshness_status}",
                f"- Evidence freshness: {bundle.snapshot.evidence_freshness_status}",
                f"- Refresh recommendation: {bundle.snapshot.refresh_recommendation}",
                f"- Latest close: {latest_close}",
                f"- Evidence: {evidence_titles}",
                f"- Evidence citation ids: {', '.join(bundle.snapshot.evidence_citation_ids) or 'None'}",
                f"- Fallback reasons: {', '.join(bundle.snapshot.fallback_reasons) or 'None'}",
                f"- Stale reasons: {', '.join(bundle.snapshot.stale_reasons) or 'None'}",
                "",
                "## Model View",
                "- Framework: trusted-risk-gate-v1 (PIT data, structured events, regime approval, Judge gate, frozen run replay)",
                f"- Model: {prediction.model_name if prediction else 'unknown'}",
                f"- Model version: {prediction.model_version if prediction else 'unknown'}",
                f"- Model status: {prediction.model_status if prediction else 'unknown'}",
                f"- Deployment approved: {prediction.deployment_approved if prediction else False}",
                f"- Signal: {prediction.signal if prediction else 'unknown'}",
                f"- Confidence: {prediction.confidence if prediction else 0:.2f}",
                f"- Risk probability: {risk_probability}",
                f"- Target: {prediction.target_name if prediction and prediction.target_name else 'n/a'}",
                f"- Feature coverage: {prediction.feature_coverage if prediction else 0:.2f}",
                f"- Missing features: {missing_features}",
                f"- Inference warnings: {inference_warnings}",
                f"- Rationale: {prediction.rationale if prediction else 'No model rationale'}",
                "",
                "## Risk",
                f"- Level: {risk.risk_level.value if risk else 'unknown'}",
                f"- Summary: {risk.summary if risk else 'No risk summary'}",
                "",
                "## Observation Stance",
                f"- Stance: {recommendation.action.value if recommendation else 'unknown'}",
                f"- Reasoning: {recommendation.reasoning if recommendation else 'No recommendation reasoning'}",
                "- Scope: Research assistance and risk observation only; no buy or sell instruction is produced.",
                "",
                "## Judge",
                f"- Verdict: {judge.verdict.value if judge else 'unknown'}",
                f"- Gating reasons: {gating}",
                "",
                "## Evidence References",
                *evidence_references,
            ]
        )
