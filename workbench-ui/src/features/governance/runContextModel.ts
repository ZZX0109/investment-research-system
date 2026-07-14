import type { RunReplaySummary } from "../../api/runViews";

export type SelectedRunContext = {
  runId: string;
  runLabel: string;
  assetTicker: string;
  assetName: string;
  createdAt: string;
  capturedAt: string;
  reportVersion: string;
  reportTitle: string;
  judgeVerdict: string;
  recommendationAction: string;
  mode: string;
  provider: string;
  asOf: string | null;
  overrides: string[];
  syntheticRatio: number;
  dataMode: string;
  sourceType: string;
  sourceName: string;
  observedAt: string;
  confidence: number;
  syntheticShare: number;
  evidenceCount: number;
  reportCount: number;
  gateCount: number;
  fallbackCount: number;
  onlySelectedRunResearch: boolean;
};

export function buildSelectedRunContext(
  summary: RunReplaySummary | null | undefined,
  onlySelectedRunResearch: boolean
): SelectedRunContext | undefined {
  if (!summary) {
    return undefined;
  }

  return {
    runId: summary.run_id,
    runLabel: summary.run_id.slice(0, 8),
    assetTicker: summary.asset_ticker,
    assetName: summary.asset_name,
    createdAt: summary.created_at,
    capturedAt: summary.captured_at,
    reportVersion: summary.report_version,
    reportTitle: summary.report_title,
    judgeVerdict: summary.judge_verdict,
    recommendationAction: summary.recommendation_action,
    mode: summary.mode,
    provider: summary.provider,
    asOf: summary.as_of,
    overrides: summary.overrides,
    syntheticRatio: summary.synthetic_ratio,
    dataMode: summary.data_mode,
    sourceType: summary.source_type,
    sourceName: summary.source_name,
    observedAt: summary.observed_at,
    confidence: summary.confidence,
    syntheticShare: summary.synthetic_share,
    evidenceCount: summary.evidence_count,
    reportCount: summary.report_count,
    gateCount: summary.gate_count,
    fallbackCount: summary.fallback_count,
    onlySelectedRunResearch
  };
}
