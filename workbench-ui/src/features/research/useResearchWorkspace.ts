import { useAnalysisRunsQuery, useDomainCatalogQuery, useEvidenceQuery, usePriceSeriesQuery, useReportsQuery, useRunDossierSummaryQuery, useRunScopeSummaryQuery } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { buildSelectedRunDossier } from "../dossier/model";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "../governance/runStatus";
import { buildFocusedEvidenceList, filterEvidenceForSelectedRun, filterReportsForSelectedRun } from "./model";

export function useResearchWorkspace() {
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const selectedEvidenceId = useWorkbenchStore((state) => state.selectedEvidenceId);
  const setSelectedEvidenceId = useWorkbenchStore((state) => state.setSelectedEvidenceId);
  const onlySelectedRunResearch = useWorkbenchStore((state) => state.onlySelectedRunResearch);
  const setOnlySelectedRunResearch = useWorkbenchStore((state) => state.setOnlySelectedRunResearch);

  const catalogQuery = useDomainCatalogQuery();
  const evidenceQuery = useEvidenceQuery(assetId);
  const priceSeriesQuery = usePriceSeriesQuery(assetId);
  const reportsQuery = useReportsQuery(assetId);
  const runsQuery = useAnalysisRunsQuery(assetId);
  const dossierSummaryQuery = useRunDossierSummaryQuery(selectedRunId, assetId);
  const runScopeSummaryQuery = useRunScopeSummaryQuery(selectedRunId, assetId);

  const assetSeries =
    priceSeriesQuery.data?.find((series) => series.series_role === "asset") ??
    priceSeriesQuery.data?.[0];
  const latestPoint = assetSeries?.points.at(-1);
  const chartPoints = (assetSeries?.points ?? []).slice(-90);
  const initialClose = chartPoints[0]?.close;
  let runningPeak = initialClose ?? 0;
  const priceChart = chartPoints.map((point) => {
    runningPeak = Math.max(runningPeak, point.close);
    return {
      date: point.timestamp.slice(0, 10),
      returnPct: initialClose ? ((point.close / initialClose) - 1) * 100 : 0,
      drawdownPct: runningPeak ? ((point.close / runningPeak) - 1) * 100 : 0
    };
  });
  const filteredEvidence = filterEvidenceForSelectedRun(
    evidenceQuery.data ?? [],
    runScopeSummaryQuery.data?.evidence_ids,
    onlySelectedRunResearch
  );
  const filteredReports = filterReportsForSelectedRun(
    reportsQuery.data ?? [],
    selectedRunId,
    runScopeSummaryQuery.data?.report_ids,
    onlySelectedRunResearch
  );
  const evidenceView = buildFocusedEvidenceList(filteredEvidence, selectedEvidenceId);
  const dossier = buildSelectedRunDossier(dossierSummaryQuery.data);
  const providerNames = (catalogQuery.data?.analysis_providers ?? []).map((provider) => provider.provider_name);
  const queryError =
    evidenceQuery.error ??
    priceSeriesQuery.error ??
    reportsQuery.error ??
    runsQuery.error ??
    dossierSummaryQuery.error ??
    runScopeSummaryQuery.error ??
    catalogQuery.error;
  const hasQueryFailure = Boolean(
    evidenceQuery.isError ||
      priceSeriesQuery.isError ||
      reportsQuery.isError ||
      runsQuery.isError ||
      dossierSummaryQuery.isError ||
      runScopeSummaryQuery.isError ||
      catalogQuery.isError
  );

  function toggleRunScopedResearch() {
    setOnlySelectedRunResearch(!onlySelectedRunResearch);
  }

  function clearFocusedEvidence() {
    setSelectedEvidenceId(null);
  }

  return {
    assetId,
    selectedRunId,
    selectedEvidenceId,
    onlySelectedRunResearch,
    latestCloseLabel: latestPoint ? latestPoint.close.toFixed(2) : "n/a",
    priceChart,
    providerNamesLabel: providerNames.join(", ") || "n/a",
    evidenceCount: evidenceView.orderedEvidence.length,
    totalEvidenceCount: evidenceQuery.data?.length ?? 0,
    runCount: runsQuery.data?.length ?? 0,
    hasRuns: (runsQuery.data?.length ?? 0) > 0,
    filteredReportsCount: filteredReports.length,
    hasQueryFailure,
    failureMessage: formatQueryFailure(queryError, "Unable to load research data for this asset."),
    selectedRunMissingSource: dossier
      ? hasMissingSourceMetadata({ mode: dossier.mode, provider: dossier.provider, as_of: dossier.asOf })
      : false,
    selectedRunStaleSource: dossier ? isStaleAsOf(dossier.asOf) : false,
    evidenceView,
    filteredReports,
    dossier,
    runScopeSummary: runScopeSummaryQuery.data,
    toggleRunScopedResearch,
    clearFocusedEvidence
  };
}
