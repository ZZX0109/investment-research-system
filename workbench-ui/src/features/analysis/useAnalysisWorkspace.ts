import { startTransition } from "react";
import {
  useAnalysisRunsQuery,
  useGenerateReportMutation,
  useRunDossierSummaryQuery,
  useRunReplaySummaryQuery,
  useTriggerAnalysisMutation
} from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { buildSelectedRunDossier } from "../dossier/model";

export function useAnalysisWorkspace() {
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const setSelectedRunId = useWorkbenchStore((state) => state.setSelectedRunId);
  const triggerMutation = useTriggerAnalysisMutation();
  const reportMutation = useGenerateReportMutation();
  const runsQuery = useAnalysisRunsQuery(selectedAssetId);
  const replaySummaryQuery = useRunReplaySummaryQuery(selectedRunId, selectedAssetId);
  const dossierSummaryQuery = useRunDossierSummaryQuery(selectedRunId, selectedAssetId);
  const dossier = buildSelectedRunDossier(dossierSummaryQuery.data);

  async function triggerAnalysis() {
    if (!selectedAssetId) {
      return;
    }
    const nextBundle = await triggerMutation.mutateAsync(selectedAssetId);
    startTransition(() => {
      setSelectedRunId(nextBundle.run.id);
    });
  }

  async function generateReport() {
    if (!selectedRunId || !selectedAssetId) {
      return;
    }
    await reportMutation.mutateAsync({ runId: selectedRunId, assetId: selectedAssetId });
  }

  return {
    selectedAssetId,
    selectedRunId,
    replaySummary: replaySummaryQuery.data,
    dossier,
    hasRuns: (runsQuery.data?.length ?? 0) > 0,
    replayError: replaySummaryQuery.error,
    dossierError: dossierSummaryQuery.error,
    triggerError: triggerMutation.error,
    reportError: reportMutation.error,
    canTriggerAnalysis: Boolean(selectedAssetId),
    canGenerateReport: Boolean(selectedRunId && selectedAssetId),
    isTriggeringAnalysis: triggerMutation.isPending,
    isGeneratingReport: reportMutation.isPending,
    triggerAnalysis,
    generateReport
  };
}
