import type { AnalysisBundle, AuditRecord, RunLineageEntry, RunLineageTimeline } from "./types";

export function buildRunLineageTimeline(
  assetId: string,
  bundles: AnalysisBundle[],
  auditRecords: AuditRecord[]
): RunLineageTimeline {
  const entries: RunLineageEntry[] = bundles.map((bundle) => {
    const report = bundle.reports[0];
    const judge = bundle.judge_scores[0];
    const recommendation = bundle.recommendations[0];
    const prediction = bundle.predictions[0];
    const relevantAudit = auditRecords.filter((record) => {
      return (
        record.target_id === bundle.run.id ||
        (report ? record.target_id === report.id : false) ||
        record.details.analysis_run_id === bundle.run.id ||
        record.details.asset_id === bundle.asset.id
      );
    });
    const reportGenerated = relevantAudit.find(
      (record) => record.action === "report.generated" && record.details.analysis_run_id === bundle.run.id
    );

    return {
      run_id: bundle.run.id,
      created_at: bundle.run.created_at,
      input_snapshot_ref: bundle.run.input_snapshot_ref,
      mode: bundle.snapshot.mode,
      provider: bundle.snapshot.provider,
      as_of: bundle.snapshot.as_of ?? null,
      overrides: bundle.snapshot.overrides,
      evidence_count: bundle.evidence.length,
      synthetic_share: bundle.snapshot.synthetic_share,
      real_share: bundle.snapshot.real_share,
      evidence_items: bundle.evidence.map((item) => ({
        id: item.id,
        title: item.title,
        summary: item.summary,
        source_type: item.provenance.source_type,
        data_mode: item.provenance.data_mode
      })),
      report_id: report?.id,
      report_title: report?.title,
      report_version: report?.report_version,
      report_thesis: report?.thesis ?? null,
      report_generated_at: reportGenerated?.created_at ?? null,
      judge_verdict: judge?.verdict ?? null,
      judge_score: judge?.score ?? null,
      recommendation_action: recommendation?.action ?? null,
      recommendation_reasoning: recommendation?.reasoning ?? null,
      model_version: prediction?.model_version ?? null,
      price_provider_status: bundle.snapshot.price_provider_status,
      evidence_provider_status: bundle.snapshot.evidence_provider_status,
      fallback_reasons: bundle.snapshot.fallback_reasons,
      gating_reasons: judge?.gating_reasons ?? [],
      audit_actions: Array.from(new Set(relevantAudit.map((record) => record.action))).sort()
    };
  });

  return {
    asset_id: assetId,
    entries
  };
}
