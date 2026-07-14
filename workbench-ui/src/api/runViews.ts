import type {
  AnalysisBundle,
  RunDossierSummary,
  RunLineageDetailSummary,
  RunReplaySummary,
  RunScopeSummary
} from "./types";

export type { RunDossierSummary, RunLineageDetailSummary, RunReplaySummary, RunScopeSummary } from "./types";
export type RunViewKind = "replay" | "dossier" | "scope" | "lineage-detail";
export type RunViewSummaryMap = {
  replay: RunReplaySummary;
  dossier: RunDossierSummary;
  scope: RunScopeSummary;
  "lineage-detail": RunLineageDetailSummary;
};

export function runViewQueryKey(kind: RunViewKind, mode: string, runId: string | null, assetId: string | null) {
  return [`run-view:${kind}`, mode, runId, assetId] as const;
}

export function buildRunReplaySummary(bundle: AnalysisBundle): RunReplaySummary {
  const report = bundle.reports[0];
  const judge = bundle.judge_scores[0];
  const recommendation = bundle.recommendations[0];

  return {
    run_id: bundle.run.id,
    asset_id: bundle.asset.id,
    asset_ticker: bundle.asset.ticker,
    asset_name: bundle.asset.name,
    created_at: bundle.run.created_at,
    captured_at: bundle.snapshot.captured_at,
    report_version: report?.report_version ?? "pending",
    report_title: report?.title ?? "Pending fixed report",
    judge_verdict: judge?.verdict ?? "n/a",
    recommendation_action: recommendation?.action ?? "n/a",
    mode: bundle.snapshot.mode,
    provider: bundle.snapshot.provider,
    as_of: bundle.snapshot.as_of ?? null,
    overrides: bundle.snapshot.overrides,
    synthetic_ratio: bundle.snapshot.synthetic_ratio,
    data_mode: bundle.run.provenance.data_mode,
    source_type: bundle.run.provenance.source_type,
    source_name: bundle.run.provenance.source_name,
    observed_at: bundle.run.provenance.observed_at,
    confidence: bundle.run.provenance.confidence,
    synthetic_share: bundle.snapshot.synthetic_share,
    evidence_count: bundle.evidence.length,
    report_count: bundle.reports.length,
    gate_count: judge?.gating_reasons.length ?? 0,
    fallback_count: bundle.snapshot.fallback_reasons.length,
    source_meta: bundle.source_meta
  };
}

export function buildRunDossierSummary(bundle: AnalysisBundle): RunDossierSummary {
  const report = bundle.reports[0];
  const judge = bundle.judge_scores[0];
  const recommendation = bundle.recommendations[0];
  const prediction = bundle.predictions[0];
  const risk = bundle.risk_conclusions[0];

  return {
    run_id: bundle.run.id,
    asset_ticker: bundle.asset.ticker,
    report_title: report?.title ?? "Pending fixed report",
    report_version: report?.report_version ?? "pending",
    report_thesis: report?.thesis ?? "No fixed report has been generated from this run yet.",
    report_body_markdown: report?.body_markdown ?? null,
    judge_verdict: judge?.verdict ?? "n/a",
    judge_score: judge?.score ?? 0,
    gate_count: judge?.gating_reasons.length ?? 0,
    gating_reasons: judge?.gating_reasons ?? [],
    fallback_count: bundle.snapshot.fallback_reasons.length,
    fallback_reasons: bundle.snapshot.fallback_reasons,
    recommendation_action: recommendation?.action ?? "n/a",
    recommendation_reasoning: recommendation?.reasoning ?? "No recommendation available.",
    recommendation_guardrails: recommendation?.guardrails ?? [],
    mode: bundle.snapshot.mode,
    provider: bundle.snapshot.provider,
    as_of: bundle.snapshot.as_of ?? null,
    overrides: bundle.snapshot.overrides,
    synthetic_ratio: bundle.snapshot.synthetic_ratio,
    confidence: prediction?.confidence ?? 0,
    model_name: prediction?.model_name ?? "n/a",
    model_version: prediction?.model_version ?? "n/a",
    model_status: prediction?.model_status ?? "unknown",
    risk_probability: prediction?.risk_probability ?? null,
    feature_coverage: prediction?.feature_coverage ?? 0,
    missing_features: prediction?.missing_features ?? [],
    deployment_approved: prediction?.deployment_approved ?? false,
    inference_warnings: prediction?.inference_warnings ?? [],
    synthetic_share: bundle.snapshot.synthetic_share,
    risk_level: risk?.risk_level ?? "n/a",
    risk_summary: risk?.summary ?? "No risk conclusion generated for this run.",
    risk_stale_after: risk?.stale_after ?? null,
    price_freshness_status: bundle.snapshot.price_freshness_status,
    evidence_freshness_status: bundle.snapshot.evidence_freshness_status,
    refresh_recommendation: bundle.snapshot.refresh_recommendation,
    stale_reasons: bundle.snapshot.stale_reasons,
    evidence_citation_ids: bundle.snapshot.evidence_citation_ids,
    source_meta: bundle.source_meta
  };
}

export function buildRunScopeSummary(bundle: AnalysisBundle): RunScopeSummary {
  return {
    run_id: bundle.run.id,
    asset_id: bundle.asset.id,
    mode: bundle.snapshot.mode,
    provider: bundle.snapshot.provider,
    as_of: bundle.snapshot.as_of ?? null,
    overrides: bundle.snapshot.overrides,
    synthetic_ratio: bundle.snapshot.synthetic_ratio,
    evidence_ids: bundle.run.evidence_ids,
    report_ids: bundle.run.report_ids,
    evidence_count: bundle.run.evidence_ids.length,
    report_count: bundle.run.report_ids.length,
    source_meta: bundle.source_meta
  };
}

export function buildRunLineageDetailSummary(bundle: AnalysisBundle): RunLineageDetailSummary {
  const report = bundle.reports[0];
  const judge = bundle.judge_scores[0];
  const recommendation = bundle.recommendations[0];
  const prediction = bundle.predictions[0];

  return {
    run_id: bundle.run.id,
    asset_id: bundle.asset.id,
    input_snapshot_ref: bundle.run.input_snapshot_ref,
    intake_strategy: bundle.snapshot.intake_strategy,
    captured_at: bundle.snapshot.captured_at,
    mode: bundle.snapshot.mode,
    provider: bundle.snapshot.provider,
    as_of: bundle.snapshot.as_of ?? null,
    overrides: bundle.snapshot.overrides,
    synthetic_ratio: bundle.snapshot.synthetic_ratio,
    data_modes: bundle.snapshot.data_modes,
    source_types: bundle.snapshot.source_types,
    latest_close: bundle.snapshot.latest_close ?? null,
    price_provider_name: bundle.snapshot.price_provider_name,
    price_provider_version: bundle.snapshot.price_provider_version,
    price_provider_status: bundle.snapshot.price_provider_status,
    evidence_provider_name: bundle.snapshot.evidence_provider_name,
    evidence_provider_version: bundle.snapshot.evidence_provider_version,
    evidence_provider_status: bundle.snapshot.evidence_provider_status,
    judge_verdict: judge?.verdict ?? "n/a",
    judge_score: judge?.score ?? 0,
    recommendation_action: recommendation?.action ?? "n/a",
    recommendation_reasoning: recommendation?.reasoning ?? "No recommendation reasoning.",
    model_confidence: prediction?.confidence ?? 0,
    model_name: prediction?.model_name ?? "n/a",
    model_version: prediction?.model_version ?? "n/a",
    model_status: prediction?.model_status ?? "unknown",
    risk_probability: prediction?.risk_probability ?? null,
    feature_coverage: prediction?.feature_coverage ?? 0,
    missing_features: prediction?.missing_features ?? [],
    deployment_approved: prediction?.deployment_approved ?? false,
    inference_warnings: prediction?.inference_warnings ?? [],
    report_version: report?.report_version ?? "pending",
    report_title: report?.title ?? null,
    fallback_reasons: bundle.snapshot.fallback_reasons,
    price_freshness_status: bundle.snapshot.price_freshness_status,
    evidence_freshness_status: bundle.snapshot.evidence_freshness_status,
    refresh_recommendation: bundle.snapshot.refresh_recommendation,
    stale_reasons: bundle.snapshot.stale_reasons,
    evidence_citation_ids: bundle.snapshot.evidence_citation_ids,
    source_meta: bundle.source_meta
  };
}

export function buildRunViewSummary<K extends RunViewKind>(kind: K, bundle: AnalysisBundle): RunViewSummaryMap[K] {
  if (kind === "replay") {
    return buildRunReplaySummary(bundle) as RunViewSummaryMap[K];
  }
  if (kind === "dossier") {
    return buildRunDossierSummary(bundle) as RunViewSummaryMap[K];
  }
  if (kind === "scope") {
    return buildRunScopeSummary(bundle) as RunViewSummaryMap[K];
  }
  return buildRunLineageDetailSummary(bundle) as RunViewSummaryMap[K];
}
