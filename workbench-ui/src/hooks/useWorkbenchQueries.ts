import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  buildRunViewSummary,
  runViewQueryKey,
  type RunViewKind,
  type RunViewSummaryMap
} from "../api/runViews";
import { useWorkbenchClient } from "./useWorkbenchClient";
import type { ReportSchedule } from "../api/types";
import type { AgentRun } from "../api/types";

export function useSessionQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["session", client.mode],
    queryFn: () => client.getSession()
  });
}

export function useAssetsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["assets", client.mode],
    queryFn: () => client.getAssets()
  });
}

export function useDomainCatalogQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["domain-catalog", client.mode],
    queryFn: () => client.getDomainCatalog()
  });
}

export function usePositionsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["positions", client.mode],
    queryFn: () => client.getPositions()
  });
}

export function useWatchlistsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["watchlists", client.mode],
    queryFn: () => client.getWatchlists()
  });
}

export function useEvidenceQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["evidence", client.mode, assetId],
    queryFn: () => client.getEvidence(assetId ?? ""),
    enabled: Boolean(assetId)
  });
}

export function usePriceSeriesQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["price-series", client.mode, assetId],
    queryFn: () => client.getPriceSeries(assetId ?? ""),
    enabled: Boolean(assetId)
  });
}

export function useReportsQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["reports", client.mode, assetId],
    queryFn: () => client.getReports(assetId ?? ""),
    enabled: Boolean(assetId)
  });
}

export function useAnalysisRunsQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["analysis-runs", client.mode, assetId],
    queryFn: () => client.getAnalysisRuns(assetId ?? ""),
    enabled: Boolean(assetId)
  });
}

export function useRunLineageQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["run-lineage", client.mode, assetId],
    queryFn: () => client.getRunLineage(assetId ?? ""),
    enabled: Boolean(assetId)
  });
}

export function useAuditRecordsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["audit-records", client.mode],
    queryFn: () => client.getAuditRecords()
  });
}

export function useResearchCardQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["research-card", client.mode, assetId],
    queryFn: () => client.getResearchCard(assetId ?? ""),
    enabled: Boolean(assetId),
    retry: false
  });
}

export function useHistoricalAnalogiesQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["historical-analogies", client.mode, assetId],
    queryFn: () => client.getHistoricalAnalogies(assetId ?? ""),
    enabled: Boolean(assetId),
    retry: false
  });
}

export function usePortfolioRiskQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["portfolio-risk", client.mode],
    queryFn: () => client.getPortfolioRisk(),
    retry: false
  });
}

export function useReportSchedulesQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["report-schedules", client.mode],
    queryFn: () => client.getReportSchedules(),
    retry: false
  });
}

export function useDeploymentStatusQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["deployment-status", client.mode],
    queryFn: () => client.getDeploymentStatus(),
    enabled: client.mode === "research" || client.mode === "real",
    retry: false
  });
}

export function useMarketObservationQuery(assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({ queryKey: ["market-observation", client.mode, assetId], queryFn: () => client.getMarketObservation(assetId ?? ""), enabled: ["research", "real"].includes(client.mode) && Boolean(assetId), refetchInterval: 300000, retry: false });
}

export function useRefreshMarketObservationMutation(assetId: string | null) {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => client.refreshMarketObservation(assetId ?? ""),
    onSuccess: (result) => queryClient.setQueryData(["market-observation", client.mode, assetId], result)
  });
}

export function useDirectionalForecastQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({ queryKey: ["directional-forecast", client.mode, runId], queryFn: () => client.getDirectionalForecast(runId ?? ""), enabled: ["research", "real"].includes(client.mode) && Boolean(runId), retry: false });
}

export function useResearchForecastQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["research-forecast", client.mode, runId],
    queryFn: () => client.getResearchForecast(runId ?? ""),
    enabled: ["research", "real"].includes(client.mode) && Boolean(runId),
    retry: false
  });
}

export function useResearchShadowSessionsQuery(symbol?: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["research-shadow", client.mode, symbol],
    queryFn: () => client.getResearchShadowSessions({ symbol: symbol ?? undefined }),
    enabled: ["research", "real"].includes(client.mode),
    retry: false
  });
}

export function useResearchModelRostersQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["research-model-rosters", client.mode],
    queryFn: () => client.getResearchModelRosters(),
    enabled: client.mode === "research" || client.mode === "real",
    retry: false
  });
}

export function useResearchShadowSummaryQuery(symbol?: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["research-shadow-summary", client.mode, symbol],
    queryFn: () => client.getResearchShadowSummary({ symbol: symbol ?? undefined }),
    enabled: ["research", "real"].includes(client.mode),
    retry: false
  });
}

export function useIngestionJobQuery(jobId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["ingestion-job", client.mode, jobId],
    queryFn: () => client.getIngestionJob(jobId ?? ""),
    enabled: ["research", "real"].includes(client.mode) && Boolean(jobId),
    refetchInterval: (query) => ["queued", "running", "retrying"].includes(query.state.data?.state ?? "") ? 1500 : false,
    retry: false
  });
}

export function useCreateAgentRunMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { asset_id: string; task_text: string; as_of: string; user_preference: AgentRun["user_preference"] }) =>
      client.createAgentRun(payload),
    onSuccess: (run) => {
      queryClient.setQueryData(["agent-run", client.mode, run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["analysis-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["research-card"] });
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
    }
  });
}

export function useModelResearchFindingsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["model-research-findings", client.mode],
    queryFn: client.getModelResearchFindings,
    enabled: ["research", "real"].includes(client.mode),
    retry: false
  });
}

export function usePaperValidationSummaryQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["paper-validation", client.mode],
    queryFn: client.getPaperValidationSummary,
    enabled: ["research", "real"].includes(client.mode),
    retry: false
  });
}

export function useRunComparisonQuery(runId: string | null, baselineRunId: string | null, assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["run-comparison", client.mode, runId, baselineRunId, assetId],
    queryFn: () => client.getRunComparison(runId ?? "", baselineRunId, assetId ?? undefined),
    enabled: Boolean(runId && baselineRunId),
    retry: false
  });
}

function useRunViewQuery<K extends RunViewKind>(kind: K, runId: string | null, assetId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: runViewQueryKey(kind, client.mode, runId, assetId),
    queryFn: () => client.getRunView(kind, runId ?? "", assetId ?? undefined) as Promise<RunViewSummaryMap[K]>,
    enabled: Boolean(runId)
  });
}

export function useRunReplaySummaryQuery(runId: string | null, assetId: string | null) {
  return useRunViewQuery("replay", runId, assetId);
}

export function useRunDossierSummaryQuery(runId: string | null, assetId: string | null) {
  return useRunViewQuery("dossier", runId, assetId);
}

export function useRunScopeSummaryQuery(runId: string | null, assetId: string | null) {
  return useRunViewQuery("scope", runId, assetId);
}

export function useRunLineageDetailSummaryQuery(runId: string | null, assetId: string | null) {
  return useRunViewQuery("lineage-detail", runId, assetId);
}

function primeRunViewQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  mode: string,
  bundle: Parameters<typeof buildRunViewSummary>[1]
) {
  void queryClient.setQueryData(runViewQueryKey("replay", mode, bundle.run.id, bundle.asset.id), buildRunViewSummary("replay", bundle));
  void queryClient.setQueryData(runViewQueryKey("dossier", mode, bundle.run.id, bundle.asset.id), buildRunViewSummary("dossier", bundle));
  void queryClient.setQueryData(runViewQueryKey("scope", mode, bundle.run.id, bundle.asset.id), buildRunViewSummary("scope", bundle));
  void queryClient.setQueryData(
    runViewQueryKey("lineage-detail", mode, bundle.run.id, bundle.asset.id),
    buildRunViewSummary("lineage-detail", bundle)
  );
}

export function useRegisterMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { email: string; display_name: string; password: string }) =>
      client.register(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["session"] });
    }
  });
}

export function useLoginMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { email: string; password: string }) => client.login(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["session"] });
    }
  });
}

export function useLogoutMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => client.logout(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["session"] });
    }
  });
}

export function useCreateAssetMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.createAsset,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    }
  });
}

export function useTriggerAnalysisMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (assetId: string) => client.triggerAnalysis(assetId),
    onSuccess: (bundle) => {
      primeRunViewQueries(queryClient, client.mode, bundle);
      void queryClient.invalidateQueries({ queryKey: ["analysis-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["run-lineage"] });
      void queryClient.invalidateQueries({ queryKey: ["audit-records"] });
    }
  });
}

export function useRefreshAssetMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, refreshMode = "auto" }: { assetId: string; refreshMode?: "online" | "cache" | "auto" }) =>
      client.refreshAsset(assetId, refreshMode),
    onSuccess: (result) => {
      if (result.analysis_bundle) primeRunViewQueries(queryClient, client.mode, result.analysis_bundle);
      void queryClient.invalidateQueries({ queryKey: ["analysis-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["price-series"] });
      void queryClient.invalidateQueries({ queryKey: ["evidence"] });
      void queryClient.invalidateQueries({ queryKey: ["research-card"] });
      void queryClient.invalidateQueries({ queryKey: ["historical-analogies"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-risk"] });
    }
  });
}

export function useCreatePositionMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.createPosition,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["positions"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-risk"] });
    }
  });
}

export function useCreateResearchAuditMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => client.createResearchAudit(runId),
    onSuccess: (audit) => {
      queryClient.setQueryData(["research-audit", client.mode, audit.analysis_run_id], audit);
      void queryClient.invalidateQueries({ queryKey: ["research-card"] });
    }
  });
}

export function useCreateReportScheduleMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { asset_id?: string | null; frequency: ReportSchedule["frequency"]; enabled: boolean; timezone: string }) =>
      client.createReportSchedule(payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["report-schedules"] })
  });
}

export function useUpdateReportScheduleMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ scheduleId, payload }: { scheduleId: string; payload: { frequency?: ReportSchedule["frequency"]; enabled?: boolean } }) =>
      client.updateReportSchedule(scheduleId, payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["report-schedules"] })
  });
}

export function useUploadDocumentMutation() {
  const client = useWorkbenchClient();
  return useMutation({
    mutationFn: ({ file, assetId }: { file: File; assetId?: string | null }) => client.uploadDocument(file, assetId)
  });
}

export function useGenerateReportMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, assetId }: { runId: string; assetId: string | null }) =>
      client.generateReport(runId, assetId ?? undefined),
    onSuccess: (response) => {
      primeRunViewQueries(queryClient, client.mode, response.bundle);
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      void queryClient.invalidateQueries({ queryKey: ["run-lineage"] });
      void queryClient.invalidateQueries({ queryKey: ["audit-records"] });
    }
  });
}

export function useTestOfficerManifestQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-manifest", client.mode],
    queryFn: () => client.getTestOfficerManifest()
  });
}

export function useTestOfficerHistoryQuery(missionId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-history", client.mode, missionId],
    queryFn: () => client.getTestOfficerHistory(missionId ?? undefined),
    enabled: Boolean(missionId)
  });
}

export function useTestOfficerComparisonQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-comparison", client.mode, runId],
    queryFn: () => client.getTestOfficerComparison(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerRegistryManifestQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-registry", client.mode, runId],
    queryFn: () => client.getTestOfficerRegistryManifest(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerOnboardingProtocolQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-onboarding-protocol", client.mode, runId],
    queryFn: () => client.getTestOfficerOnboardingProtocol(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerMissionPackageQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-mission-package", client.mode, runId],
    queryFn: () => client.getTestOfficerMissionPackage(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerSelectorMapsQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-selector-maps", client.mode, runId],
    queryFn: () => client.getTestOfficerSelectorMaps(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerFixturesQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-fixtures", client.mode, runId],
    queryFn: () => client.getTestOfficerFixtures(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerScenariosQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-scenarios", client.mode, runId],
    queryFn: () => client.getTestOfficerScenarios(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerOraclesQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-oracles", client.mode, runId],
    queryFn: () => client.getTestOfficerOracles(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerEvidenceIndexQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-evidence-index", client.mode, runId],
    queryFn: () => client.getTestOfficerEvidenceIndex(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerJudgeReportResourceQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-judge-report-resource", client.mode, runId],
    queryFn: () => client.getTestOfficerJudgeReportResource(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function useTestOfficerAuditRunsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-audit-runs", client.mode],
    queryFn: () => client.getTestOfficerAuditRuns(),
    retry: false
  });
}

export function useTestOfficerAuditRunDetailQuery(runId: string | null) {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-audit-run-detail", client.mode, runId],
    queryFn: () => client.getTestOfficerAuditRunDetail(runId ?? ""),
    enabled: Boolean(runId),
    retry: false
  });
}

export function usePreviewTestOfficerMissionMutation() {
  const client = useWorkbenchClient();
  return useMutation({
    mutationFn: client.previewTestOfficerMission
  });
}

export function useCreateTestOfficerRunMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.createTestOfficerRun,
    onSuccess: (response) => {
      void queryClient.setQueryData(["test-officer-manifest", client.mode], response.manifest);
      void queryClient.invalidateQueries({ queryKey: ["test-officer-history"] });
      void queryClient.invalidateQueries({ queryKey: ["test-officer-comparison"] });
    }
  });
}

export function useTestOfficerCredentialsQuery() {
  const client = useWorkbenchClient();
  return useQuery({
    queryKey: ["test-officer-credentials", client.mode],
    queryFn: () => client.listTestOfficerCredentials()
  });
}

export function useUpsertTestOfficerCredentialMutation() {
  const client = useWorkbenchClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: client.upsertTestOfficerCredential,
    onSuccess: (credential) => {
      void queryClient.setQueryData(
        ["test-officer-credentials", client.mode],
        (existing: Awaited<ReturnType<typeof client.listTestOfficerCredentials>> | undefined) => {
          const current = existing ?? [];
          return [
            ...current.filter((item) => item.id !== credential.id),
            credential
          ].sort((left, right) => left.id.localeCompare(right.id));
        }
      );
      void queryClient.invalidateQueries({ queryKey: ["test-officer-credentials"] });
    }
  });
}
