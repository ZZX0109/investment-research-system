import type { AnalysisBundle, RunComparisonSummary } from "./types";

function difference(source: string[], other: string[]) {
  return source.filter((item) => !other.includes(item));
}

export function buildRunComparisonSummary(
  current: AnalysisBundle,
  baseline: AnalysisBundle
): RunComparisonSummary {
  const currentJudge = current.judge_scores[0];
  const baselineJudge = baseline.judge_scores[0];
  const currentPrediction = current.predictions[0];
  const baselinePrediction = baseline.predictions[0];
  const currentReport = current.reports[0];
  const baselineReport = baseline.reports[0];

  return {
    current_run_id: current.run.id,
    baseline_run_id: baseline.run.id,
    current_report_version: currentReport?.report_version ?? "pending",
    baseline_report_version: baselineReport?.report_version ?? "pending",
    current_model_version: currentPrediction?.model_version ?? "n/a",
    baseline_model_version: baselinePrediction?.model_version ?? "n/a",
    judge_score_delta: (currentJudge?.score ?? 0) - (baselineJudge?.score ?? 0),
    confidence_delta: (currentPrediction?.confidence ?? 0) - (baselinePrediction?.confidence ?? 0),
    latest_close_delta:
      current.snapshot.latest_close != null && baseline.snapshot.latest_close != null
        ? current.snapshot.latest_close - baseline.snapshot.latest_close
        : null,
    added_gates: difference(currentJudge?.gating_reasons ?? [], baselineJudge?.gating_reasons ?? []),
    removed_gates: difference(baselineJudge?.gating_reasons ?? [], currentJudge?.gating_reasons ?? []),
    added_fallbacks: difference(current.snapshot.fallback_reasons, baseline.snapshot.fallback_reasons),
    removed_fallbacks: difference(baseline.snapshot.fallback_reasons, current.snapshot.fallback_reasons),
    thesis_changed: (currentReport?.thesis ?? "") !== (baselineReport?.thesis ?? "")
  };
}
