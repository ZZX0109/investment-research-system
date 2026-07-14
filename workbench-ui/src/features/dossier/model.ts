import type { RunDossierSummary } from "../../api/runViews";

export type SelectedRunDossier = {
  runId: string;
  assetTicker: string;
  reportTitle: string;
  reportVersion: string;
  reportThesis: string;
  reportBodyMarkdown: string | null;
  judgeVerdict: string;
  judgeScore: number;
  gateCount: number;
  gatingReasons: string[];
  fallbackCount: number;
  fallbackReasons: string[];
  recommendationAction: string;
  recommendationReasoning: string;
  recommendationGuardrails: string[];
  mode: string;
  provider: string;
  asOf: string | null;
  overrides: string[];
  syntheticRatio: number;
  confidence: number;
  modelName: string;
  modelVersion: string;
  modelStatus: string;
  riskProbability: number | null;
  featureCoverage: number;
  missingFeatures: string[];
  deploymentApproved: boolean;
  inferenceWarnings: string[];
  modelDiagnostic?: RunDossierSummary["model_diagnostic"];
  syntheticShare: number;
  riskLevel: string;
  riskSummary: string;
  riskStaleAfter: string | null;
  priceFreshnessStatus: string;
  evidenceFreshnessStatus: string;
  refreshRecommendation: string;
  staleReasons: string[];
  evidenceCitationIds: string[];
};

export function buildSelectedRunDossier(summary?: RunDossierSummary | null): SelectedRunDossier | undefined {
  if (!summary) {
    return undefined;
  }

  return {
    runId: summary.run_id,
    assetTicker: summary.asset_ticker,
    reportTitle: summary.report_title,
    reportVersion: summary.report_version,
    reportThesis: summary.report_thesis,
    reportBodyMarkdown: summary.report_body_markdown,
    judgeVerdict: summary.judge_verdict,
    judgeScore: summary.judge_score,
    gateCount: summary.gate_count,
    gatingReasons: summary.gating_reasons,
    fallbackCount: summary.fallback_count,
    fallbackReasons: summary.fallback_reasons,
    recommendationAction: summary.recommendation_action,
    recommendationReasoning: summary.recommendation_reasoning,
    recommendationGuardrails: summary.recommendation_guardrails,
    mode: summary.mode,
    provider: summary.provider,
    asOf: summary.as_of,
    overrides: summary.overrides,
    syntheticRatio: summary.synthetic_ratio,
    confidence: summary.confidence,
    modelName: summary.model_name,
    modelVersion: summary.model_version,
    modelStatus: summary.model_status,
    riskProbability: summary.risk_probability,
    featureCoverage: summary.feature_coverage,
    missingFeatures: summary.missing_features,
    deploymentApproved: summary.deployment_approved,
    inferenceWarnings: summary.inference_warnings,
    modelDiagnostic: summary.model_diagnostic,
    syntheticShare: summary.synthetic_share,
    riskLevel: summary.risk_level,
    riskSummary: summary.risk_summary,
    riskStaleAfter: summary.risk_stale_after,
    priceFreshnessStatus: summary.price_freshness_status,
    evidenceFreshnessStatus: summary.evidence_freshness_status,
    refreshRecommendation: summary.refresh_recommendation,
    staleReasons: summary.stale_reasons,
    evidenceCitationIds: summary.evidence_citation_ids
  };
}
