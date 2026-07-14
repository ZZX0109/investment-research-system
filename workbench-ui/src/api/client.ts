import {
  getDemoAnalysisRuns,
  getDemoAssets,
  getDemoAuditRecords,
  getDemoBundle,
  getDemoCatalog,
  getDemoEvidence,
  getDemoPositions,
  getDemoPriceSeries,
  getDemoReports,
  getDemoSession,
  getDemoTestOfficerComparison,
  getDemoTestOfficerEvidenceIndex,
  getDemoTestOfficerFixtures,
  getDemoTestOfficerHistory,
  getDemoTestOfficerJudgeReport,
  getDemoTestOfficerManifest,
  getDemoTestOfficerMissionPackage,
  getDemoTestOfficerOnboardingProtocol,
  getDemoTestOfficerOracles,
  getDemoTestOfficerRegistryManifest,
  getDemoTestOfficerScenarios,
  getDemoTestOfficerSelectorMaps,
  getDemoWatchlists,
  getSandboxAssets,
  getSandboxAnalysisRuns,
  getSandboxAuditRecords,
  getSandboxBundle,
  getSandboxCatalog,
  getSandboxEvidence,
  getSandboxPositions,
  getSandboxPriceSeries,
  getSandboxReports,
  getSandboxSession,
  getSandboxWatchlists
} from "./demoData";
import { buildRunComparisonSummary } from "./runComparison";
import { buildRunLineageTimeline } from "./runLineage";
import {
  buildRunViewSummary,
  type RunViewKind,
  type RunViewSummaryMap
} from "./runViews";
import type {
  AgentRun,
  AnalysisRun,
  AnalysisBundle,
  Asset,
  AuditRecord,
  DomainCatalog,
  AuthResponse,
  Evidence,
  GeneratedReportResponse,
  DeploymentStatus,
  DocumentArtifact,
  HistoricalScenario,
  PortfolioRiskSnapshot,
  RefreshAnalysisResult,
  ReportSchedule,
  ResearchAudit,
  ResearchCard,
  Position,
  PriceSeries,
  RunComparisonSummary,
  RunDossierSummary,
  RunReplaySummary,
  RunScopeSummary,
  RunLineageTimeline,
  ResearchReport,
  TestOfficerComparisonReport,
  TestOfficerAuditRunDetail,
  TestOfficerAuditRun,
  TestOfficerCredentialSummary,
  TestOfficerCredentialUpsertRequest,
  TestOfficerEvidenceRegistryResource,
  TestOfficerFixtureRegistryResource,
  TestOfficerHistoryIndex,
  TestOfficerJudgeReportResource,
  TestOfficerManifest,
  TestOfficerMissionPackageResource,
  TestOfficerMissionPreview,
  TestOfficerOnboardingDraft,
  TestOfficerOnboardingProtocolResource,
  TestOfficerOracleRegistryResource,
  TestOfficerRegistryManifest,
  TestOfficerScenarioRegistryResource,
  TestOfficerSelectorMapResource,
  TestOfficerRunRequest,
  TestOfficerRunResponse,
  User,
  Watchlist,
  WorkbenchMode
} from "./types";

interface AssetCreateInput {
  ticker: string;
  name: string;
  asset_type: string;
  currency: string;
  exchange?: string;
  data_mode: string;
  source_type: string;
  source_name: string;
  observed_at: string;
  confidence: number;
}

export type WorkbenchDataSource = "api" | "seeded-demo" | "seeded-sandbox";

type ApiErrorPayload = {
  detail?: string;
  message?: string;
};

export type ApiErrorKind = "auth" | "csrf" | "not_found" | "validation" | "server" | "network";

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") {
    return undefined;
  }
  const prefix = `${name}=`;
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
}

export class ApiError extends Error {
  status: number;
  detail?: string;
  kind: ApiErrorKind;

  constructor(status: number, message: string, detail?: string, kind: ApiErrorKind = classifyApiError(status)) {
    super(message);
    this.status = status;
    this.detail = detail;
    this.kind = kind;
  }
}

function classifyApiError(status: number): ApiErrorKind {
  if (status === 401) {
    return "auth";
  }
  if (status === 403) {
    return "csrf";
  }
  if (status === 404) {
    return "not_found";
  }
  if (status >= 400 && status < 500) {
    return "validation";
  }
  return "server";
}

async function readErrorPayload(response: Response): Promise<ApiErrorPayload | undefined> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return (await response.json()) as ApiErrorPayload;
    } catch {
      return undefined;
    }
  }
  const text = await response.text();
  return text ? { detail: text } : undefined;
}

function shouldAttachCsrf(method: string) {
  return !["GET", "HEAD", "OPTIONS"].includes(method);
}

function buildHeaders(method: string, init?: RequestInit): HeadersInit {
  const csrfToken = shouldAttachCsrf(method) ? readCookie("airc_csrf_token") : undefined;
  return {
    ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
    ...(csrfToken ? { "x-csrf-token": csrfToken } : {}),
    ...(init?.headers ?? {})
  };
}

function createApiTransport() {
  let refreshInFlight: Promise<void> | null = null;

  async function rawFetch(path: string, init?: RequestInit): Promise<Response> {
    const method = (init?.method ?? "GET").toUpperCase();
    return fetch(path, {
      ...init,
      method,
      credentials: "include",
      headers: buildHeaders(method, init)
    });
  }

  async function refreshSession(): Promise<void> {
    if (!refreshInFlight) {
      refreshInFlight = (async () => {
        const response = await rawFetch("/api/v1/auth/refresh", { method: "POST" });
        if (!response.ok) {
          const payload = await readErrorPayload(response);
          const detail = payload?.detail ?? payload?.message;
          throw new ApiError(response.status, detail || `Session refresh failed with ${response.status}`, detail);
        }
      })().finally(() => {
        refreshInFlight = null;
      });
    }
    return refreshInFlight;
  }

  return async function apiFetch<T>(path: string, init?: RequestInit, allowRefresh = true): Promise<T> {
    const response = await rawFetch(path, init);

    if (response.status === 401 && allowRefresh && path !== "/api/v1/auth/refresh") {
      await refreshSession();
      return apiFetch<T>(path, init, false);
    }

    if (!response.ok) {
      const payload = await readErrorPayload(response);
      const detail = payload?.detail ?? payload?.message;
      throw new ApiError(response.status, detail || `Request failed with ${response.status}`, detail);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return (await response.json()) as T;
  };
}

function testOfficerHeaders(): Record<string, string> {
  const env = (import.meta as unknown as { env?: Record<string, string | boolean | undefined> }).env;
  const browserToken =
    (env?.DEV === true || env?.DEV === "true") && typeof window !== "undefined"
      ? window.localStorage.getItem("testOfficerToken") ?? undefined
      : undefined;
  const envToken = typeof env?.VITE_TEST_OFFICER_TOKEN === "string" ? env.VITE_TEST_OFFICER_TOKEN : undefined;
  const token = browserToken || envToken;
  return token ? { "x-test-officer-token": token } : {};
}

export function resolveWorkbenchDataSource(mode: WorkbenchMode): WorkbenchDataSource {
  if (mode === "demo") {
    return "seeded-demo";
  }
  if (mode === "sandbox") {
    return "seeded-sandbox";
  }
  return "api";
}

export function createWorkbenchClient(mode: WorkbenchMode) {
  const dataSource = resolveWorkbenchDataSource(mode);
  const usesSeededData = dataSource !== "api";
  const apiFetch = createApiTransport();

  return {
    mode,
    dataSource,
    getSession: () =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoSession())
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxSession())
        : apiFetch<User>("/api/v1/auth/me").then((user) => ({
            user,
            access_expires_at: "",
            refresh_expires_at: ""
          })),
    register: (payload: { email: string; display_name: string; password: string }) =>
      apiFetch<AuthResponse>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify(payload)
      }, false),
    login: (payload: { email: string; password: string }) =>
      apiFetch<AuthResponse>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(payload)
      }, false),
    logout: () =>
      usesSeededData
        ? Promise.resolve()
        : apiFetch<void>("/api/v1/auth/logout", {
            method: "POST"
          }, false),
    getAssets: () =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoAssets())
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxAssets())
        : apiFetch<Asset[]>("/api/v1/assets"),
    getDomainCatalog: () =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoCatalog())
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxCatalog())
        : apiFetch<DomainCatalog>("/api/v1/domain/catalog"),
    getPositions: () =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoPositions())
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxPositions())
        : apiFetch<Position[]>("/api/v1/positions/me"),
    createPosition: (payload: { asset_id: string; quantity: number; cost_basis: number; opened_at: string }) =>
      usesSeededData
        ? Promise.resolve((dataSource === "seeded-demo" ? getDemoPositions() : getSandboxPositions())[0])
        : apiFetch<Position>("/api/v1/positions", { method: "POST", body: JSON.stringify(payload) }),
    getWatchlists: () =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoWatchlists())
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxWatchlists())
        : apiFetch<Watchlist[]>("/api/v1/watchlists/me"),
    getEvidence: (assetId: string) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoEvidence(assetId))
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxEvidence(assetId))
        : apiFetch<Evidence[]>(`/api/v1/assets/${assetId}/evidence`),
    getPriceSeries: (assetId: string) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoPriceSeries(assetId))
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxPriceSeries(assetId))
        : apiFetch<PriceSeries[]>(`/api/v1/assets/${assetId}/price-series`),
    getReports: (assetId: string) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoReports(assetId))
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxReports(assetId))
        : apiFetch<ResearchReport[]>(`/api/v1/assets/${assetId}/reports`),
    getAuditRecords: () =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoAuditRecords())
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxAuditRecords())
        : apiFetch<AuditRecord[]>("/api/v1/audit-records/me"),
    createAsset: (payload: AssetCreateInput) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoAssets()[0])
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxAssets()[0])
        : apiFetch<Asset>("/api/v1/assets", {
            method: "POST",
            body: JSON.stringify(payload)
          }),
    triggerAnalysis: (assetId: string) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoBundle(assetId))
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxBundle(assetId))
        : apiFetch<AnalysisBundle>(`/api/v1/assets/${assetId}/analysis-runs`, { method: "POST" }),
    refreshAsset: (assetId: string, refreshMode: "online" | "cache" | "auto" = "auto") =>
      usesSeededData
        ? Promise.resolve<RefreshAnalysisResult>({
            refresh_run: {
              id: `seeded-refresh-${assetId}`,
              asset_id: assetId,
              refresh_mode: refreshMode,
              state: "degraded",
              started_at: new Date().toISOString(),
              completed_at: new Date().toISOString(),
              provider_attempts: [{ provider: dataSource, status: "seeded" }],
              cache_hit: true,
              price_count: 0,
              evidence_count: 0,
              failure_reasons: ["Seeded modes do not perform authoritative refreshes."]
            },
            analysis_bundle: dataSource === "seeded-demo" ? getDemoBundle(assetId) : getSandboxBundle(assetId)
          })
        : apiFetch<RefreshAnalysisResult>(`/api/v1/assets/${assetId}/refresh`, {
            method: "POST",
            body: JSON.stringify({ refresh_mode: refreshMode })
          }),
    getHistoricalAnalogies: (assetId: string) =>
      usesSeededData
        ? Promise.resolve<HistoricalScenario[]>([])
        : apiFetch<HistoricalScenario[]>(`/api/v1/assets/${assetId}/historical-analogies`),
    getPortfolioRisk: () =>
      usesSeededData
        ? Promise.resolve<PortfolioRiskSnapshot>({
            id: `seeded-risk-${dataSource}`,
            as_of: new Date().toISOString(),
            total_market_value: 0,
            concentration_hhi: 0,
            market_exposure: {},
            industry_exposure: {},
            position_risk_contributions: {},
            correlation_matrix: {},
            stress_scenarios: {},
            warnings: ["Portfolio risk requires real persisted positions and prices."]
          })
        : apiFetch<PortfolioRiskSnapshot>("/api/v1/portfolio/me/risk"),
    getResearchCard: (assetId: string) =>
      usesSeededData
        ? Promise.resolve<ResearchCard>({
            bundle: dataSource === "seeded-demo" ? getDemoBundle(assetId) : getSandboxBundle(assetId),
            historical_analogies: [],
            portfolio_risk: null,
            audit: null,
            observation_conditions: ["Switch to real mode for authoritative refresh and audit."],
            contrary_view: "Seeded mode is limited to workflow demonstration."
          })
        : apiFetch<ResearchCard>(`/api/v1/assets/${assetId}/research-card`),
    getResearchAudit: (runId: string) =>
      apiFetch<ResearchAudit>(`/api/v1/analysis-runs/${runId}/audit`),
    createResearchAudit: (runId: string) =>
      apiFetch<ResearchAudit>(`/api/v1/analysis-runs/${runId}/audit`, { method: "POST" }),
    getReportSchedules: () =>
      usesSeededData ? Promise.resolve<ReportSchedule[]>([]) : apiFetch<ReportSchedule[]>("/api/v1/report-schedules"),
    createReportSchedule: (payload: { asset_id?: string | null; frequency: ReportSchedule["frequency"]; enabled: boolean; timezone: string }) =>
      apiFetch<ReportSchedule>("/api/v1/report-schedules", { method: "POST", body: JSON.stringify(payload) }),
    updateReportSchedule: (scheduleId: string, payload: { frequency?: ReportSchedule["frequency"]; enabled?: boolean }) =>
      apiFetch<ReportSchedule>(`/api/v1/report-schedules/${scheduleId}`, { method: "PATCH", body: JSON.stringify(payload) }),
    deleteReportSchedule: (scheduleId: string) =>
      apiFetch<void>(`/api/v1/report-schedules/${scheduleId}`, { method: "DELETE" }),
    uploadDocument: (file: File, assetId?: string | null) => {
      const body = new FormData();
      body.append("file", file);
      if (assetId) body.append("asset_id", assetId);
      return apiFetch<DocumentArtifact>("/api/v1/documents", { method: "POST", body });
    },
    getDeploymentStatus: () => apiFetch<DeploymentStatus>("/api/v1/models/deployment-status"),
    getMarketObservation: (assetId: string) => apiFetch<import("./types").MarketObservation>(`/api/v1/assets/${assetId}/market-observation`),
    refreshMarketObservation: (assetId: string) => apiFetch<import("./types").MarketObservation>(`/api/v1/assets/${assetId}/market-observation/refresh`, { method: "POST" }),
    getDirectionalForecast: (runId: string) => apiFetch<import("./types").DirectionalForecastResponse>(`/api/v1/analysis-runs/${runId}/directional-forecast`),
    getResearchForecast: (runId: string) => apiFetch<import("./types").ResearchForecastBundle>(`/api/v1/analysis-runs/${runId}/research-forecast`),
    getIngestionJob: (jobId: string) => apiFetch<import("./types").IngestionJob>(`/api/v1/ingestion-jobs/${jobId}`),
    cancelIngestionJob: (jobId: string) => apiFetch<import("./types").IngestionJob>(`/api/v1/ingestion-jobs/${jobId}/cancel`, { method: "POST" }),
    createAgentRun: (payload: { asset_id: string; task_text: string; as_of: string; user_preference: AgentRun["user_preference"] }) =>
      usesSeededData
        ? Promise.resolve<AgentRun>({
            id: `seeded-agent-${payload.asset_id}`,
            owner_user_id: "seeded-user",
            asset_id: payload.asset_id,
            task_type: "single_asset_risk_research",
            task_text: payload.task_text,
            user_preference: payload.user_preference,
            as_of: payload.as_of,
            state: "abstained",
            current_node: "repair_or_abstain",
            correlation_id: `seeded-${payload.asset_id}`,
            verdict: "hold",
            abstain_reason: "Authoritative Agent runs require real mode.",
            budget: { max_llm_calls: 6, max_tool_calls: 12, max_input_tokens: 32000, max_output_tokens: 4000, max_evidence: 12, max_evidence_rounds: 2, max_repair_count: 1, llm_calls_used: 0, tool_calls_used: 0, input_tokens_used: 0, output_tokens_used: 0, repair_count: 0 },
            created_at: new Date().toISOString(), updated_at: new Date().toISOString(), completed_at: new Date().toISOString()
          })
        : apiFetch<AgentRun>("/api/v1/agent-runs", { method: "POST", body: JSON.stringify(payload) }),
    getAgentRun: (runId: string) => apiFetch<AgentRun>(`/api/v1/agent-runs/${runId}`),
    getModelResearchFindings: () => apiFetch<Record<string, unknown>>("/api/v1/models/research-findings"),
    getPaperValidationSummary: () => apiFetch<Record<string, unknown>>("/api/v1/paper-validation/summary"),
    getAnalysisRuns: (assetId: string) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoAnalysisRuns(assetId))
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxAnalysisRuns(assetId))
        : apiFetch<AnalysisRun[]>(`/api/v1/assets/${assetId}/analysis-runs`),
    getRunLineage: (assetId: string) =>
      dataSource === "seeded-demo" || dataSource === "seeded-sandbox"
        ? Promise.resolve(
            buildRunLineageTimeline(
              assetId,
              (dataSource === "seeded-demo" ? getDemoAnalysisRuns(assetId) : getSandboxAnalysisRuns(assetId)).map((run) =>
                dataSource === "seeded-demo" ? getDemoBundle(assetId, run.id) : getSandboxBundle(assetId, run.id)
              ),
              dataSource === "seeded-demo" ? getDemoAuditRecords() : getSandboxAuditRecords()
            )
          )
        : apiFetch<RunLineageTimeline>(`/api/v1/assets/${assetId}/lineage`),
    getBundle: (runId: string, assetId?: string) =>
      dataSource === "seeded-demo"
        ? Promise.resolve(getDemoBundle(assetId, runId))
        : dataSource === "seeded-sandbox"
          ? Promise.resolve(getSandboxBundle(assetId, runId))
        : apiFetch<AnalysisBundle>(`/api/v1/analysis-runs/${runId}/bundle`),
    getRunComparison: (runId: string, baselineRunId?: string | null, assetId?: string) =>
      dataSource === "seeded-demo" || dataSource === "seeded-sandbox"
        ? Promise.resolve(
            buildRunComparisonSummary(
              dataSource === "seeded-demo" ? getDemoBundle(assetId, runId) : getSandboxBundle(assetId, runId),
              baselineRunId
                ? dataSource === "seeded-demo"
                  ? getDemoBundle(assetId, baselineRunId)
                  : getSandboxBundle(assetId, baselineRunId)
                : dataSource === "seeded-demo"
                  ? getDemoBundle(assetId, runId)
                  : getSandboxBundle(assetId, runId)
            )
          )
        : apiFetch<RunComparisonSummary>(
            baselineRunId
              ? `/api/v1/analysis-runs/${runId}/comparison?baseline_run_id=${encodeURIComponent(baselineRunId)}`
              : `/api/v1/analysis-runs/${runId}/comparison`
          ),
    getRunView: <K extends RunViewKind>(kind: K, runId: string, assetId?: string): Promise<RunViewSummaryMap[K]> => {
      if (dataSource !== "api") {
        const bundle = dataSource === "seeded-demo" ? getDemoBundle(assetId, runId) : getSandboxBundle(assetId, runId);
        return Promise.resolve(buildRunViewSummary(kind, bundle));
      }

      const path =
        kind === "replay"
          ? "replay-summary"
          : kind === "dossier"
            ? "dossier"
            : kind === "scope"
              ? "scope"
              : "lineage-detail";
      return apiFetch<RunViewSummaryMap[K]>(`/api/v1/analysis-runs/${runId}/${path}`);
    },
    generateReport: (runId: string, assetId?: string) =>
      dataSource !== "api"
        ? Promise.resolve<GeneratedReportResponse>({
            report:
              dataSource === "seeded-demo"
                ? getDemoBundle(assetId, runId).reports[0]
                : getSandboxBundle(assetId, runId).reports[0],
            bundle: dataSource === "seeded-demo" ? getDemoBundle(assetId, runId) : getSandboxBundle(assetId, runId)
          })
        : apiFetch<GeneratedReportResponse>(`/api/v1/analysis-runs/${runId}/report`, { method: "POST" }),
    getTestOfficerManifest: () =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerManifest())
        : apiFetch<TestOfficerManifest>("/api/v1/test-officer/runs/latest/manifest", {
            headers: testOfficerHeaders()
          }),
    getTestOfficerHistory: (missionId?: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerHistory())
        : apiFetch<TestOfficerHistoryIndex>(
            missionId
              ? `/api/v1/test-officer/history?mission_id=${encodeURIComponent(missionId)}`
              : "/api/v1/test-officer/history",
            { headers: testOfficerHeaders() }
          ),
    getTestOfficerComparison: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerComparison())
        : apiFetch<TestOfficerComparisonReport>(`/api/v1/test-officer/runs/${runId}/comparison`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerRegistryManifest: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerRegistryManifest())
        : apiFetch<TestOfficerRegistryManifest>(`/api/v1/test-officer/runs/${runId}/registry`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerOnboardingProtocol: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerOnboardingProtocol())
        : apiFetch<TestOfficerOnboardingProtocolResource>(`/api/v1/test-officer/runs/${runId}/registry/onboarding`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerMissionPackage: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerMissionPackage())
        : apiFetch<TestOfficerMissionPackageResource>(`/api/v1/test-officer/runs/${runId}/registry/mission-package`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerSelectorMaps: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerSelectorMaps())
        : apiFetch<TestOfficerSelectorMapResource[]>(`/api/v1/test-officer/runs/${runId}/registry/selector-maps`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerFixtures: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerFixtures())
        : apiFetch<TestOfficerFixtureRegistryResource[]>(`/api/v1/test-officer/runs/${runId}/registry/fixtures`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerScenarios: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerScenarios())
        : apiFetch<TestOfficerScenarioRegistryResource[]>(`/api/v1/test-officer/runs/${runId}/registry/scenarios`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerOracles: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerOracles())
        : apiFetch<TestOfficerOracleRegistryResource[]>(`/api/v1/test-officer/runs/${runId}/registry/oracles`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerEvidenceIndex: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerEvidenceIndex())
        : apiFetch<TestOfficerEvidenceRegistryResource[]>(`/api/v1/test-officer/runs/${runId}/registry/evidence`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerJudgeReportResource: (runId: string) =>
      usesSeededData
        ? Promise.resolve(getDemoTestOfficerJudgeReport())
        : apiFetch<TestOfficerJudgeReportResource>(`/api/v1/test-officer/runs/${runId}/registry/judge-report`, {
            headers: testOfficerHeaders()
          }),
    getTestOfficerAuditRuns: () =>
      usesSeededData
        ? Promise.resolve(buildSeededAuditRuns())
        : apiFetch<TestOfficerAuditRun[]>("/api/v1/test-officer/audit/runs?limit=10", {
            headers: testOfficerHeaders()
          }),
    getTestOfficerAuditRunDetail: (runId: string) =>
      usesSeededData
        ? Promise.resolve(buildSeededAuditRunDetail(runId))
        : apiFetch<TestOfficerAuditRunDetail>(`/api/v1/test-officer/audit/runs/${runId}`, {
            headers: testOfficerHeaders()
          }),
    previewTestOfficerMission: (payload: TestOfficerOnboardingDraft) =>
      usesSeededData
        ? Promise.resolve(buildSeededMissionPreview(payload))
        : apiFetch<TestOfficerMissionPreview>("/api/v1/test-officer/mission-preview", {
          method: "POST",
          headers: testOfficerHeaders(),
          body: JSON.stringify(payload)
        }),
    createTestOfficerRun: (payload: TestOfficerRunRequest) =>
      usesSeededData
        ? Promise.resolve(buildSeededRunResponse(payload))
        : apiFetch<TestOfficerRunResponse>("/api/v1/test-officer/runs", {
          method: "POST",
          headers: testOfficerHeaders(),
          body: JSON.stringify(payload)
        }),
    listTestOfficerCredentials: () =>
      usesSeededData
        ? Promise.resolve(buildSeededCredentialSummaries())
        : apiFetch<TestOfficerCredentialSummary[]>("/api/v1/test-officer/credentials", {
            headers: testOfficerHeaders()
          }),
    upsertTestOfficerCredential: (payload: TestOfficerCredentialUpsertRequest) =>
      usesSeededData
        ? Promise.resolve(buildSeededCredentialSummary(payload))
        : apiFetch<TestOfficerCredentialSummary>("/api/v1/test-officer/credentials", {
            method: "POST",
            headers: testOfficerHeaders(),
            body: JSON.stringify(payload)
          })
  };
}

function buildSeededMissionPreview(payload: TestOfficerOnboardingDraft): TestOfficerMissionPreview {
  const enabledScenarios = payload.scenarioRequests.filter((scenario) => scenario.enabled);
  return {
    project: {
      id: "project_seeded-preview",
      name: payload.projectName,
      status: "active"
    },
    targetApp: {
      id: "targetapp_seeded-preview",
      name: payload.targetAppName,
      baseUrl: payload.baseUrl,
      status: "configured"
    },
    mission: {
      id: "mission_seeded-preview",
      name: `${payload.targetAppName} mission`,
      objective: payload.businessObjective,
      mode: payload.mode,
      status: enabledScenarios.length > 0 ? "ready" : "draft"
    },
    scenarios: enabledScenarios.map((scenario) => ({
      id: `scenario_${scenario.family}`,
      name: seededScenarioLabel(scenario.family),
      goal: seededScenarioGoal(scenario.family),
      tags: [scenario.family],
      targetPageId: scenario.pagePath
    })),
    oracles: enabledScenarios.map((scenario, index) => ({
      id: `oracle_${scenario.family}_${index}`,
      name: `${seededScenarioLabel(scenario.family)} oracle`
    })),
    counts: {
      pages: payload.keyPages.filter(Boolean).length,
      selectorHints: payload.selectorHints.filter(Boolean).length,
      scenarios: enabledScenarios.length,
      oracles: enabledScenarios.length
    }
  };
}

function seededScenarioLabel(family: TestOfficerOnboardingDraft["scenarioRequests"][number]["family"]) {
  if (family === "auth-login") {
    return "Login flow";
  }
  if (family === "form-submission") {
    return "Form submission";
  }
  if (family === "list-state-change") {
    return "List/state change";
  }
  return "Golden path";
}

function seededScenarioGoal(family: TestOfficerOnboardingDraft["scenarioRequests"][number]["family"]) {
  if (family === "auth-login") {
    return "Verify a valid account can authenticate.";
  }
  if (family === "form-submission") {
    return "Verify the main business form can be completed and submitted.";
  }
  if (family === "list-state-change") {
    return "Verify a visible state transition occurs in a complex list or dashboard.";
  }
  return "Verify the primary workflow remains reachable.";
}

function buildSeededRunResponse(payload: TestOfficerRunRequest): TestOfficerRunResponse {
  const manifest = getDemoTestOfficerManifest();
  return {
    runId: manifest.run.id,
    status: manifest.run.status,
    reviewStatus: manifest.run.reviewStatus,
    executor: payload.executor ?? "memory",
    headless: payload.headless ?? true,
    trace: payload.trace ?? false,
    recordVideo: payload.recordVideo ?? false,
    manifest: {
      ...manifest,
      project: {
        ...manifest.project,
        name: payload.projectName
      },
      targetApp: {
        ...manifest.targetApp,
        name: payload.targetAppName,
        baseUrl: payload.baseUrl
      },
      mission: {
        ...manifest.mission,
        name: `${payload.targetAppName} mission`,
        objective: payload.businessObjective,
        mode: payload.mode
      }
    },
    gate: {
      passed: manifest.run.reviewStatus === "pass",
      exitCode: manifest.run.reviewStatus === "pass" ? 0 : 2,
      reasons: manifest.run.reviewStatus === "pass" ? [] : ["seeded-demo-regression"],
      diagnostics: {
        newFindings: manifest.findings.map((finding) => finding.title),
        newArtifactSignals: (manifest.artifacts ?? [])
          .map((artifact) => typeof artifact.metadata.firstError === "string" ? `console:${artifact.metadata.firstError}` : undefined)
          .filter((signal): signal is string => Boolean(signal)),
        regression: {
          statusChanged: manifest.run.status !== "passed",
          reviewChanged: manifest.run.reviewStatus !== "pass",
          failedStepDelta: manifest.steps.filter((step) => step.status === "failed" || step.status === "blocked").length,
          findingDelta: manifest.findings.length,
          artifactSignalDelta: (manifest.artifacts ?? []).filter((artifact) => typeof artifact.metadata.firstError === "string").length
        }
      }
    }
  };
}

function buildSeededCredentialSummaries(): TestOfficerCredentialSummary[] {
  return [
    {
      id: "openai-default",
      label: "Default LLM judge key",
      kind: "api-key",
      username: null,
      metadata: { provider: "openai", scope: "judge" },
      createdAt: "2026-07-03T10:00:00.000Z",
      updatedAt: "2026-07-03T10:00:00.000Z",
      secretPreview: "****demo",
      secretLength: 18
    }
  ];
}

function buildSeededCredentialSummary(payload: TestOfficerCredentialUpsertRequest): TestOfficerCredentialSummary {
  const now = new Date().toISOString();
  return {
    id: payload.id,
    label: payload.label,
    kind: payload.kind,
    username: payload.username ?? null,
    metadata: payload.metadata ?? {},
    createdAt: now,
    updatedAt: now,
    secretPreview: payload.secret.length >= 4 ? `****${payload.secret.slice(-4)}` : "****",
    secretLength: payload.secret.length
  };
}

function buildSeededAuditRuns(): TestOfficerAuditRun[] {
  const history = getDemoTestOfficerHistory();
  return history.runs.slice(0, 10).map((run) => ({
    runId: run.runId,
    projectId: "project_seeded-demo",
    missionId: run.missionId,
    missionName: run.missionName,
    targetAppId: run.targetAppId,
    targetAppName: run.targetAppName,
    status: run.status,
    reviewStatus: run.reviewStatus,
    startedAt: run.startedAt,
    finishedAt: run.finishedAt,
    bundleUri: run.manifestPath,
    createdAt: run.startedAt,
    updatedAt: run.finishedAt
  }));
}

function buildSeededAuditRunDetail(runId: string): TestOfficerAuditRunDetail {
  const manifest = getDemoTestOfficerManifest();
  const failureAttributions = manifest.failureAttributions?.length
    ? manifest.failureAttributions.map((attribution) => ({
        id: attribution.id,
        findingId: attribution.findingId,
        scenarioId: attribution.scenarioId,
        stepId: attribution.stepId ?? null,
        rank: attribution.rank,
        category: attribution.category,
        confidence: attribution.confidence,
        likelyCause: attribution.likelyCause,
        recommendation: attribution.recommendation,
        signals: attribution.signals
      }))
    : manifest.findings.map((finding, index) => ({
        id: `seeded-attribution:${finding.id}`,
        findingId: finding.id,
        scenarioId: finding.scenarioId,
        stepId: null,
        rank: index + 1,
        category: finding.category,
        confidence: 0.7,
        likelyCause: finding.summary,
        recommendation: finding.recommendation ?? null,
        signals: {
          evidenceIds: finding.evidenceIds,
          artifactIds: [],
          sourceContextIds: [],
          changedFiles: [],
          consoleErrorArtifacts: [],
          networkErrorArtifacts: [],
          domSnapshotArtifacts: []
        }
      }));
  return {
    runId,
    sourceContexts: (manifest.sourceContexts ?? []).map((context) => ({
      id: context.adapter.id,
      kind: context.adapter.kind,
      readState: context.readState,
      sourceRef: context.adapter.sourceRef,
      failureReason: context.failureReason ?? null,
      permissions: context.adapter.permissions,
      usageScopes: context.adapter.usageScopes
    })),
    failureAttributions,
    artifacts: manifest.artifacts.map((artifact) => ({
      id: artifact.id,
      evidenceId: artifact.evidenceId,
      kind: artifact.kind,
      status: artifact.status,
      artifactUri: artifact.path,
      mediaType: artifact.mediaType,
      sizeBytes: artifact.sizeBytes,
      metadata: artifact.metadata ?? {}
    })),
    gateResults: [
      {
        id: `${runId}:gate`,
        passed: manifest.run.reviewStatus === "pass",
        exitCode: manifest.run.reviewStatus === "pass" ? 0 : 2,
        reasons: manifest.run.reviewStatus === "pass" ? [] : ["seeded-demo-regression"],
        diagnostics: {
          newFindings: manifest.findings.map((finding) => finding.title),
          newArtifactSignals: manifest.artifacts
            .map((artifact) => typeof artifact.metadata.firstError === "string" ? `console:${artifact.metadata.firstError}` : undefined)
            .filter((signal): signal is string => Boolean(signal))
        },
        generatedAt: manifest.run.finishedAt ?? manifest.run.updatedAt
      }
    ],
    runtimeLifecycle: (manifest.run.metadata?.runtimeLifecycle ?? [])
      .filter((phase): phase is NonNullable<typeof manifest.run.metadata>["runtimeLifecycle"][number] =>
        Boolean(phase)
      )
      .map((phase, index) => ({
        id: `${runId}:runtime:${index}:${phase.phase}`,
        phase: phase.phase,
        status: phase.status,
        summary: phase.summary ?? null
      }))
  };
}
