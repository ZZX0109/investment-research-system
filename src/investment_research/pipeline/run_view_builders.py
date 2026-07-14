from __future__ import annotations

from investment_research.domain.models import AnalysisRun, AuditRecord, JudgeScore
from investment_research.pipeline.models import (
    AnalysisBundle,
    RunComparisonSummary,
    RunLineageEntry,
    RunLineageTimeline,
)
from investment_research.pipeline.source_meta import SourceLayerMetadata
from investment_research.pipeline.run_views import (
    AssetRefreshStatusSummary,
    RunDossierSummary,
    RunRefreshStatusSummary,
    RunLineageDetailSummary,
    RunReplaySummary,
    RunScopeSummary,
)


def _judge_verdict_value(judge: JudgeScore | None, *, fallback: str = "n/a") -> str:
    return judge.verdict.value if judge else fallback


def build_run_replay_summary(bundle: AnalysisBundle) -> RunReplaySummary:
    report = bundle.reports[0] if bundle.reports else None
    judge = bundle.judge_scores[0] if bundle.judge_scores else None
    recommendation = bundle.recommendations[0] if bundle.recommendations else None

    return RunReplaySummary(
        run_id=str(bundle.run.id),
        asset_id=str(bundle.asset.id),
        asset_ticker=bundle.asset.ticker,
        asset_name=bundle.asset.name,
        created_at=bundle.run.created_at,
        captured_at=bundle.snapshot.captured_at,
        report_version=report.report_version if report else "pending",
        report_title=report.title if report else "Pending fixed report",
        judge_verdict=_judge_verdict_value(judge),
        recommendation_action=recommendation.action.value if recommendation else "n/a",
        mode=bundle.snapshot.mode,
        provider=bundle.snapshot.provider,
        as_of=bundle.snapshot.as_of,
        overrides=bundle.snapshot.overrides,
        synthetic_ratio=bundle.snapshot.synthetic_ratio,
        data_mode=bundle.run.provenance.data_mode.value,
        source_type=bundle.run.provenance.source_type.value,
        source_name=bundle.run.provenance.source_name,
        observed_at=bundle.run.provenance.observed_at,
        confidence=bundle.run.provenance.confidence,
        synthetic_share=bundle.snapshot.synthetic_share,
        evidence_count=len(bundle.evidence),
        report_count=len(bundle.reports),
        gate_count=len(judge.gating_reasons) if judge else 0,
        fallback_count=len(bundle.snapshot.fallback_reasons),
        source_meta=bundle.snapshot.source_meta,
    )


def build_run_dossier_summary(bundle: AnalysisBundle) -> RunDossierSummary:
    report = bundle.reports[0] if bundle.reports else None
    judge = bundle.judge_scores[0] if bundle.judge_scores else None
    recommendation = bundle.recommendations[0] if bundle.recommendations else None
    prediction = bundle.predictions[0] if bundle.predictions else None
    risk = bundle.risk_conclusions[0] if bundle.risk_conclusions else None

    return RunDossierSummary(
        run_id=str(bundle.run.id),
        asset_ticker=bundle.asset.ticker,
        report_title=report.title if report else "Pending fixed report",
        report_version=report.report_version if report else "pending",
        report_thesis=report.thesis if report else "No fixed report has been generated from this run yet.",
        report_body_markdown=None if report is None else report.body_markdown,
        judge_verdict=_judge_verdict_value(judge),
        judge_score=judge.score if judge else 0.0,
        gate_count=len(judge.gating_reasons) if judge else 0,
        gating_reasons=[] if judge is None else judge.gating_reasons,
        fallback_count=len(bundle.snapshot.fallback_reasons),
        fallback_reasons=bundle.snapshot.fallback_reasons,
        recommendation_action=recommendation.action.value if recommendation else "n/a",
        recommendation_reasoning=recommendation.reasoning if recommendation else "No recommendation available.",
        recommendation_guardrails=[] if recommendation is None else recommendation.guardrails,
        mode=bundle.snapshot.mode,
        provider=bundle.snapshot.provider,
        as_of=bundle.snapshot.as_of,
        overrides=bundle.snapshot.overrides,
        synthetic_ratio=bundle.snapshot.synthetic_ratio,
        confidence=prediction.confidence if prediction else 0.0,
        model_name=prediction.model_name if prediction else "n/a",
        model_version=prediction.model_version if prediction else "n/a",
        model_status=prediction.model_status if prediction else "unknown",
        risk_probability=None if prediction is None else prediction.risk_probability,
        feature_coverage=prediction.feature_coverage if prediction else 0.0,
        missing_features=[] if prediction is None else prediction.missing_features,
        deployment_approved=prediction.deployment_approved if prediction else False,
        inference_warnings=[] if prediction is None else prediction.inference_warnings,
        model_diagnostic=None if prediction is None else prediction.diagnostic,
        synthetic_share=bundle.snapshot.synthetic_share,
        risk_level=risk.risk_level.value if risk else "n/a",
        risk_summary=risk.summary if risk else "No risk conclusion generated for this run.",
        risk_stale_after=None if risk is None else risk.stale_after,
        price_freshness_status=bundle.snapshot.price_freshness_status,
        evidence_freshness_status=bundle.snapshot.evidence_freshness_status,
        refresh_recommendation=bundle.snapshot.refresh_recommendation,
        stale_reasons=bundle.snapshot.stale_reasons,
        evidence_citation_ids=bundle.snapshot.evidence_citation_ids,
        source_meta=bundle.snapshot.source_meta,
    )


def build_run_scope_summary(run: AnalysisRun) -> RunScopeSummary:
    return RunScopeSummary(
        run_id=str(run.id),
        asset_id=str(run.asset_id),
        mode=run.data_mode or run.provenance.data_mode.value,
        provider=run.provider or run.provenance.source_name,
        as_of=run.as_of,
        overrides=run.overrides,
        synthetic_ratio=run.synthetic_ratio,
        evidence_ids=[str(evidence_id) for evidence_id in run.evidence_ids],
        report_ids=[str(report_id) for report_id in run.report_ids],
        evidence_count=len(run.evidence_ids),
        report_count=len(run.report_ids),
        source_meta=SourceLayerMetadata(
            mode=run.data_mode or run.provenance.data_mode.value,
            provider=run.provider or run.provenance.source_name,
            as_of=run.as_of,
            overrides=run.overrides,
            synthetic_ratio=run.synthetic_ratio,
        ),
    )


def build_run_comparison_summary(current: AnalysisBundle, baseline: AnalysisBundle) -> RunComparisonSummary:
    current_judge = current.judge_scores[0] if current.judge_scores else None
    baseline_judge = baseline.judge_scores[0] if baseline.judge_scores else None
    current_prediction = current.predictions[0] if current.predictions else None
    baseline_prediction = baseline.predictions[0] if baseline.predictions else None
    current_report = current.reports[0] if current.reports else None
    baseline_report = baseline.reports[0] if baseline.reports else None
    current_recommendation = current.recommendations[0] if current.recommendations else None
    baseline_recommendation = baseline.recommendations[0] if baseline.recommendations else None

    def difference(source: list[str], other: list[str]) -> list[str]:
        return [item for item in source if item not in other]

    latest_close_delta = None
    if current.snapshot.latest_close is not None and baseline.snapshot.latest_close is not None:
        latest_close_delta = current.snapshot.latest_close - baseline.snapshot.latest_close

    return RunComparisonSummary(
        current_run_id=str(current.run.id),
        baseline_run_id=str(baseline.run.id),
        current_report_version=current_report.report_version if current_report else "pending",
        baseline_report_version=baseline_report.report_version if baseline_report else "pending",
        current_model_version=current_prediction.model_version if current_prediction else "n/a",
        baseline_model_version=baseline_prediction.model_version if baseline_prediction else "n/a",
        judge_score_delta=(current_judge.score if current_judge else 0.0) - (baseline_judge.score if baseline_judge else 0.0),
        confidence_delta=(
            current_prediction.confidence if current_prediction else 0.0
        ) - (baseline_prediction.confidence if baseline_prediction else 0.0),
        latest_close_delta=latest_close_delta,
        added_gates=difference(
            current_judge.gating_reasons if current_judge else [],
            baseline_judge.gating_reasons if baseline_judge else [],
        ),
        removed_gates=difference(
            baseline_judge.gating_reasons if baseline_judge else [],
            current_judge.gating_reasons if current_judge else [],
        ),
        added_fallbacks=difference(current.snapshot.fallback_reasons, baseline.snapshot.fallback_reasons),
        removed_fallbacks=difference(baseline.snapshot.fallback_reasons, current.snapshot.fallback_reasons),
        thesis_changed=(
            (current_report.thesis if current_report else "") != (baseline_report.thesis if baseline_report else "")
            or (current_recommendation.reasoning if current_recommendation else "")
            != (baseline_recommendation.reasoning if baseline_recommendation else "")
            or current.snapshot.fallback_reasons != baseline.snapshot.fallback_reasons
        ),
        current_source_meta=current.snapshot.source_meta,
        baseline_source_meta=baseline.snapshot.source_meta,
    )


def build_run_lineage_detail_summary(bundle: AnalysisBundle) -> RunLineageDetailSummary:
    report = bundle.reports[0] if bundle.reports else None
    judge = bundle.judge_scores[0] if bundle.judge_scores else None
    recommendation = bundle.recommendations[0] if bundle.recommendations else None
    prediction = bundle.predictions[0] if bundle.predictions else None

    return RunLineageDetailSummary(
        run_id=str(bundle.run.id),
        asset_id=str(bundle.asset.id),
        input_snapshot_ref=bundle.run.input_snapshot_ref,
        intake_strategy=bundle.snapshot.intake_strategy,
        captured_at=bundle.snapshot.captured_at,
        mode=bundle.snapshot.mode,
        provider=bundle.snapshot.provider,
        as_of=bundle.snapshot.as_of,
        overrides=bundle.snapshot.overrides,
        synthetic_ratio=bundle.snapshot.synthetic_ratio,
        data_modes=bundle.snapshot.data_modes,
        source_types=bundle.snapshot.source_types,
        latest_close=bundle.snapshot.latest_close,
        price_provider_name=bundle.snapshot.price_provider_name,
        price_provider_version=bundle.snapshot.price_provider_version,
        price_provider_status=bundle.snapshot.price_provider_status,
        evidence_provider_name=bundle.snapshot.evidence_provider_name,
        evidence_provider_version=bundle.snapshot.evidence_provider_version,
        evidence_provider_status=bundle.snapshot.evidence_provider_status,
        judge_verdict=_judge_verdict_value(judge),
        judge_score=judge.score if judge else 0.0,
        recommendation_action=recommendation.action.value if recommendation else "n/a",
        recommendation_reasoning=recommendation.reasoning if recommendation else "No recommendation reasoning.",
        model_confidence=prediction.confidence if prediction else 0.0,
        model_name=prediction.model_name if prediction else "n/a",
        model_version=prediction.model_version if prediction else "n/a",
        model_status=prediction.model_status if prediction else "unknown",
        risk_probability=None if prediction is None else prediction.risk_probability,
        feature_coverage=prediction.feature_coverage if prediction else 0.0,
        missing_features=[] if prediction is None else prediction.missing_features,
        deployment_approved=prediction.deployment_approved if prediction else False,
        inference_warnings=[] if prediction is None else prediction.inference_warnings,
        model_diagnostic=None if prediction is None else prediction.diagnostic,
        report_version=report.report_version if report else "pending",
        report_title=report.title if report else None,
        fallback_reasons=bundle.snapshot.fallback_reasons,
        price_freshness_status=bundle.snapshot.price_freshness_status,
        evidence_freshness_status=bundle.snapshot.evidence_freshness_status,
        refresh_recommendation=bundle.snapshot.refresh_recommendation,
        stale_reasons=bundle.snapshot.stale_reasons,
        evidence_citation_ids=bundle.snapshot.evidence_citation_ids,
        source_meta=bundle.snapshot.source_meta,
    )


def build_run_refresh_status_summary(bundle: AnalysisBundle) -> RunRefreshStatusSummary:
    judge = bundle.judge_scores[0] if bundle.judge_scores else None
    report = bundle.reports[0] if bundle.reports else None
    return RunRefreshStatusSummary(
        run_id=str(bundle.run.id),
        asset_id=str(bundle.asset.id),
        report_version=report.report_version if report else "pending",
        judge_verdict=_judge_verdict_value(judge),
        mode=bundle.snapshot.mode,
        provider=bundle.snapshot.provider,
        as_of=bundle.snapshot.as_of,
        overrides=bundle.snapshot.overrides,
        synthetic_ratio=bundle.snapshot.synthetic_ratio,
        price_freshness_status=bundle.snapshot.price_freshness_status,
        evidence_freshness_status=bundle.snapshot.evidence_freshness_status,
        refresh_recommendation=bundle.snapshot.refresh_recommendation,
        stale_reasons=bundle.snapshot.stale_reasons,
        evidence_citation_ids=bundle.snapshot.evidence_citation_ids,
        source_meta=bundle.snapshot.source_meta,
    )


def build_asset_refresh_status_summary(
    asset_id: str,
    bundle: AnalysisBundle | None,
) -> AssetRefreshStatusSummary:
    if bundle is None:
        return AssetRefreshStatusSummary(
            asset_id=asset_id,
            latest_run_id=None,
            has_run=False,
            status="missing_run",
            refresh_recommendation="create_first_run",
            stale_reasons=["No analysis run exists yet for this asset."],
            source_meta=None,
        )

    run_status = build_run_refresh_status_summary(bundle)
    status = "fresh"
    if "missing" in {run_status.price_freshness_status, run_status.evidence_freshness_status}:
        status = "blocked"
    elif "stale" in {run_status.price_freshness_status, run_status.evidence_freshness_status}:
        status = "stale"

    return AssetRefreshStatusSummary(
        asset_id=asset_id,
        latest_run_id=run_status.run_id,
        has_run=True,
        status=status,
        mode=run_status.mode,
        provider=run_status.provider,
        as_of=run_status.as_of,
        overrides=run_status.overrides,
        synthetic_ratio=run_status.synthetic_ratio,
        price_freshness_status=run_status.price_freshness_status,
        evidence_freshness_status=run_status.evidence_freshness_status,
        refresh_recommendation=run_status.refresh_recommendation,
        stale_reasons=run_status.stale_reasons,
        evidence_citation_ids=run_status.evidence_citation_ids,
        source_meta=run_status.source_meta,
    )


def build_run_lineage_entry(bundle: AnalysisBundle, audit_records: list[AuditRecord]) -> RunLineageEntry:
    report = bundle.reports[0] if bundle.reports else None
    judge = bundle.judge_scores[0] if bundle.judge_scores else None
    recommendation = bundle.recommendations[0] if bundle.recommendations else None
    prediction = bundle.predictions[0] if bundle.predictions else None

    relevant_audit = [
        record
        for record in audit_records
        if str(record.target_id) in {str(bundle.run.id), str(report.id) if report else ""}
        or record.details.get("analysis_run_id") == str(bundle.run.id)
        or record.details.get("asset_id") == str(bundle.asset.id)
    ]
    report_generated = next(
        (
            record
            for record in relevant_audit
            if record.action == "report.generated" and record.details.get("analysis_run_id") == str(bundle.run.id)
        ),
        None,
    )

    return RunLineageEntry(
        run_id=str(bundle.run.id),
        created_at=bundle.run.created_at,
        input_snapshot_ref=bundle.run.input_snapshot_ref,
        mode=bundle.snapshot.mode,
        provider=bundle.snapshot.provider,
        as_of=bundle.snapshot.as_of,
        overrides=bundle.snapshot.overrides,
        evidence_count=len(bundle.evidence),
        synthetic_share=bundle.snapshot.synthetic_share,
        real_share=bundle.snapshot.real_share,
        evidence_items=[
            RunLineageEntry.EvidenceItem(
                id=str(item.id),
                title=item.title,
                summary=item.summary,
                source_type=item.provenance.source_type.value,
                data_mode=item.provenance.data_mode.value,
            )
            for item in bundle.evidence
        ],
        report_id=None if report is None else str(report.id),
        report_title=None if report is None else report.title,
        report_version=None if report is None else report.report_version,
        report_thesis=None if report is None else report.thesis,
        report_generated_at=None if report_generated is None else report_generated.created_at,
        judge_verdict=None if judge is None else judge.verdict.value,
        judge_score=None if judge is None else judge.score,
        recommendation_action=None if recommendation is None else recommendation.action.value,
        recommendation_reasoning=None if recommendation is None else recommendation.reasoning,
        model_version=None if prediction is None else prediction.model_version,
        price_provider_status=bundle.snapshot.price_provider_status,
        evidence_provider_status=bundle.snapshot.evidence_provider_status,
        fallback_reasons=bundle.snapshot.fallback_reasons,
        gating_reasons=[] if judge is None else judge.gating_reasons,
        audit_actions=sorted({record.action for record in relevant_audit}),
    )


def build_run_lineage_timeline(
    asset_id: str,
    bundles: list[AnalysisBundle],
    audit_records: list[AuditRecord],
) -> RunLineageTimeline:
    return RunLineageTimeline(
        asset_id=asset_id,
        entries=[build_run_lineage_entry(bundle, audit_records) for bundle in bundles],
    )
