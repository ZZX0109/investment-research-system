export type WorkbenchMode = "demo" | "sandbox" | "real";
export type DataMode = "demo" | "sandbox" | "real";
export type SourceType = "real" | "synthetic" | "backfilled" | "manual_override";
export type JudgeVerdict = "pass" | "warn" | "hold" | "block";

export interface AgentBudget {
  max_llm_calls: number;
  max_tool_calls: number;
  max_input_tokens: number;
  max_output_tokens: number;
  max_evidence: number;
  max_evidence_rounds: number;
  max_repair_count: number;
  llm_calls_used: number;
  tool_calls_used: number;
  input_tokens_used: number;
  output_tokens_used: number;
  repair_count: number;
}

export interface AgentRun {
  id: string;
  owner_user_id: string;
  asset_id: string;
  research_run_id?: string | null;
  report_id?: string | null;
  provider_profile_id?: string | null;
  task_type: "single_asset_risk_research";
  task_text: string;
  user_preference: "conservative" | "growth" | "short_term" | "fund";
  as_of: string;
  state: "created" | "running" | "repairing" | "completed" | "abstained" | "failed" | "cancelled";
  current_node?: string | null;
  correlation_id: string;
  verdict?: JudgeVerdict | null;
  abstain_reason?: string | null;
  budget: AgentBudget;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface Provenance {
  data_mode: DataMode;
  source_type: SourceType;
  source_name: string;
  observed_at: string;
  confidence: number;
}

export interface SourceLayerMetadata {
  mode: string;
  provider: string;
  as_of?: string | null;
  overrides: string[];
  synthetic_ratio: number;
}

export interface VersionInfo {
  schema_version: string;
  entity_version: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  auth_subject: string;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface Asset {
  id: string;
  ticker: string;
  name: string;
  asset_type: string;
  currency: string;
  exchange?: string | null;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface Position {
  id: string;
  user_id: string;
  asset_id: string;
  quantity: number;
  cost_basis: number;
  opened_at: string;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface Watchlist {
  id: string;
  user_id: string;
  name: string;
  asset_ids: string[];
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface PricePoint {
  id: string;
  asset_id: string;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface PriceSeries {
  id: string;
  asset_id: string;
  interval: string;
  series_role?: "asset" | "benchmark" | "sector" | "style";
  reference_symbol?: string | null;
  points: PricePoint[];
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface Evidence {
  id: string;
  asset_id: string;
  evidence_type: string;
  title: string;
  summary: string;
  source_url?: string | null;
  collected_at: string;
  published_at?: string | null;
  payload_ref?: string | null;
  event_type?: string | null;
  direction?: string | null;
  intensity?: string | null;
  source_tier?: string | null;
  surprise_bucket?: string | null;
  guidance_bucket?: string | null;
  filing_type?: string | null;
  raw_hash?: string | null;
  normalized_hash?: string | null;
  data_version?: string | null;
  related_ids: string[];
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface AnalysisRun {
  id: string;
  asset_id: string;
  triggered_by: string;
  input_snapshot_ref: string;
  input_snapshot_hash?: string | null;
  model_version?: string | null;
  reasoning_steps?: string[];
  data_mode?: string | null;
  provider?: string | null;
  as_of?: string | null;
  overrides?: string[];
  synthetic_ratio?: number;
  report_version?: string | null;
  evidence_ids: string[];
  prediction_ids: string[];
  risk_conclusion_ids: string[];
  recommendation_ids: string[];
  report_ids: string[];
  judge_score_ids: string[];
  refresh_run_id?: string | null;
  feature_contract_version?: string | null;
  feature_vector_hash?: string | null;
  document_ids?: string[];
  historical_scenario_ids?: string[];
  portfolio_snapshot_id?: string | null;
  audit_id?: string | null;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface RefreshRun {
  id: string;
  asset_id: string;
  refresh_mode: "online" | "cache" | "auto";
  state: "running" | "succeeded" | "degraded" | "failed";
  started_at: string;
  completed_at?: string | null;
  provider_attempts: Array<Record<string, unknown>>;
  cache_hit: boolean;
  price_count: number;
  evidence_count: number;
  failure_reasons: string[];
  data_version?: string | null;
}

export interface RefreshAnalysisResult {
  job_id?: string | null;
  refresh_run: RefreshRun;
  analysis_bundle?: AnalysisBundle | null;
}

export interface IngestionJob {
  id: string;
  idempotency_key: string;
  job_type: string;
  state: "queued" | "running" | "retrying" | "succeeded" | "degraded" | "failed" | "cancelled";
  symbols: string[];
  attempts: number;
  max_attempts: number;
  coverage_ratio: number;
  quality_status?: "passed" | "degraded" | "failed" | null;
  quality_issues: string[];
  latest_source_time?: string | null;
  error_message?: string | null;
}

export interface DataStatus {
  as_of: string;
  latest_source_time?: string | null;
  fetched_at?: string | null;
  latency_seconds?: number | null;
  coverage_ratio: number;
  quality_status: "passed" | "degraded" | "failed";
  cache_state: "fresh" | "stale_usable" | "expired" | "unavailable";
  degraded_symbols: string[];
  provider_chain: string[];
  reasons: string[];
}

export interface DirectionDistribution {
  horizon_days: 1 | 5;
  up: number;
  down: number;
  flat: number;
}

export interface ResearchForecastBundle {
  id: string;
  analysis_run_id: string;
  asset_id: string;
  market_snapshot_id?: string | null;
  market_snapshot_hash?: string | null;
  decision_context: "close_confirmed" | "pre_open";
  decision_time?: string | null;
  feature_built_at?: string | null;
  as_of: string;
  direction_1d?: DirectionDistribution | null;
  direction_5d?: DirectionDistribution | null;
  return_20d?: { horizon_days: 20; p10: number; p50: number; p90: number } | null;
  drawdown_20d?: { horizon_days: 20; threshold: number; threshold_probability: number; p10?: number | null; p50?: number | null; p90?: number | null } | null;
  evidence_coverage: number;
  feature_coverage: number;
  data_status: DataStatus;
  tasks: Array<{ task: string; status: string; model_name?: string | null; model_version?: string | null; gating_reasons: string[] }>;
  gating_reasons: string[];
  abstained: boolean;
}

export interface HistoricalScenario {
  id: string;
  asset_id: string;
  analysis_run_id?: string | null;
  as_of: string;
  candidate_date: string;
  similarity: number;
  regime: string;
  return_1w?: number | null;
  return_1m?: number | null;
  return_3m?: number | null;
  max_drawdown_3m?: number | null;
  feature_snapshot: Record<string, number>;
}

export interface PortfolioRiskSnapshot {
  id: string;
  as_of: string;
  total_market_value: number;
  concentration_hhi: number;
  volatility_20d?: number | null;
  max_drawdown?: number | null;
  market_exposure: Record<string, number>;
  industry_exposure: Record<string, number>;
  position_risk_contributions: Record<string, number>;
  correlation_matrix: Record<string, Record<string, number>>;
  stress_scenarios: Record<string, number>;
  warnings: string[];
}

export interface ResearchAudit {
  id: string;
  analysis_run_id: string;
  verdict: JudgeVerdict;
  score: number;
  checks: Array<{ name: string; passed: boolean; reason: string; severity: string }>;
  contrary_evidence_ids: string[];
  evidence_budget: number;
  rounds_used: number;
  token_estimate: number;
  summary: string;
}

export interface ResearchCard {
  bundle: AnalysisBundle;
  historical_analogies: HistoricalScenario[];
  portfolio_risk?: PortfolioRiskSnapshot | null;
  audit?: ResearchAudit | null;
  observation_conditions: string[];
  contrary_view: string;
}

export interface ReportSchedule {
  id: string;
  asset_id?: string | null;
  frequency: "manual" | "daily" | "weekly" | "monthly" | "event_triggered";
  enabled: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  timezone: string;
}

export interface DocumentArtifact {
  id: string;
  asset_id?: string | null;
  filename: string;
  content_type: string;
  source_url?: string | null;
  sha256: string;
  page_count: number;
  parse_status: "pending" | "parsed" | "needs_visual_review" | "failed";
  text_summary?: string | null;
  tables: Array<Record<string, unknown>>;
  figures: Array<Record<string, unknown>>;
  failure_reasons: string[];
}

export interface DeploymentStatus {
  manifest: Record<string, unknown>;
  feature_contract: Record<string, unknown>;
  trusted_risk_gate?: Record<string, unknown>;
  public_experiment?: Record<string, unknown>;
}

export interface MarketObservation {
  asset_id: string;
  market_status: string;
  provider: string;
  provider_status: string;
  latest_price?: number | null;
  latest_price_at?: string | null;
  last_close?: number | null;
  stale: boolean;
  quote_delay_seconds?: number | null;
  last_success_at?: string | null;
  consecutive_failures: number;
  degraded_reasons: string[];
  outcomes: Array<{ run_id: string; predicted_risk?: number | null; prediction_price?: number | null; latest_price?: number | null; cumulative_return?: number | null; realized_max_drawdown?: number | null; observed_trading_days: number; remaining_trading_days: number; outcome: string; judge_verdict?: string | null; evaluation_due_at: string; milestones?: Record<string, { horizon_days: number; realized_return: number; realized_max_drawdown: number }>; error_category?: string; abstained?: boolean }>;
}

export interface DirectionalForecastResponse {
  status: "research_only" | "unavailable" | "approved";
  forecast?: { direction: "up" | "down" | "flat"; confidence: number; model_version?: string | null } | null;
  gating_reasons: string[];
}

export interface ModelPrediction {
  id: string;
  asset_id: string;
  analysis_run_id: string;
  model_name: string;
  model_version: string;
  horizon: string;
  signal: string;
  confidence: number;
  rationale: string;
  risk_probability?: number | null;
  model_status?: string;
  feature_coverage?: number;
  missing_features?: string[];
  deployment_approved?: boolean;
  manifest_version?: string | null;
  target_name?: string | null;
  inference_warnings?: string[];
  diagnostic?: ModelDiagnostic | null;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface ModelDiagnostic {
  feature_coverage: number;
  missing_features: string[];
  out_of_range_features: string[];
  drift_score: number;
  provider_missing_rate: number;
  warnings: string[];
}

export interface RiskConclusion {
  id: string;
  asset_id: string;
  analysis_run_id: string;
  risk_level: string;
  summary: string;
  evidence_ids: string[];
  stale_after?: string | null;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface InvestmentRecommendation {
  id: string;
  asset_id: string;
  analysis_run_id: string;
  action: string;
  conviction: number;
  reasoning: string;
  guardrails: string[];
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface JudgeScore {
  id: string;
  analysis_run_id: string;
  score: number;
  verdict: JudgeVerdict;
  gating_reasons: string[];
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface ResearchReport {
  id: string;
  asset_id: string;
  analysis_run_id: string;
  title: string;
  thesis: string;
  evidence_ids: string[];
  report_version: string;
  body_markdown?: string | null;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface AuditRecord {
  id: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  details: Record<string, string>;
  status: string;
  version: VersionInfo;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
}

export interface AnalysisSnapshot {
  asset_id: string;
  asset_snapshot?: Asset | null;
  captured_at: string;
  mode: string;
  provider: string;
  as_of?: string | null;
  overrides: string[];
  synthetic_ratio: number;
  data_modes: string[];
  source_types: string[];
  intake_strategy: string;
  price_provider_name: string;
  price_provider_version: string;
  price_provider_status: string;
  evidence_provider_name: string;
  evidence_provider_version: string;
  evidence_provider_status: string;
  fallback_reasons: string[];
  latest_close?: number | null;
  latest_price_timestamp?: string | null;
  price_freshness_status: string;
  evidence_freshness_status: string;
  refresh_recommendation: string;
  stale_reasons: string[];
  evidence_citation_ids: string[];
  evidence_ids: string[];
  price_series_snapshot?: PriceSeries[];
  evidence_snapshot?: Evidence[];
  synthetic_share: number;
  real_share: number;
  source_meta: SourceLayerMetadata;
}

export interface AnalysisBundle {
  asset: Asset;
  run: AnalysisRun;
  snapshot: AnalysisSnapshot;
  source_meta: SourceLayerMetadata;
  evidence: Evidence[];
  predictions: ModelPrediction[];
  risk_conclusions: RiskConclusion[];
  recommendations: InvestmentRecommendation[];
  judge_scores: JudgeScore[];
  reports: ResearchReport[];
}

export interface GeneratedReportResponse {
  report: ResearchReport;
  bundle: AnalysisBundle;
}

export interface RunComparisonSummary {
  current_run_id: string;
  baseline_run_id: string;
  current_report_version: string;
  baseline_report_version: string;
  current_model_version: string;
  baseline_model_version: string;
  judge_score_delta: number;
  confidence_delta: number;
  latest_close_delta: number | null;
  added_gates: string[];
  removed_gates: string[];
  added_fallbacks: string[];
  removed_fallbacks: string[];
  thesis_changed: boolean;
  current_source_meta: SourceLayerMetadata;
  baseline_source_meta: SourceLayerMetadata;
}

export interface RunReplaySummary {
  run_id: string;
  asset_id: string;
  asset_ticker: string;
  asset_name: string;
  created_at: string;
  captured_at: string;
  report_version: string;
  report_title: string;
  judge_verdict: string;
  recommendation_action: string;
  mode: string;
  provider: string;
  as_of: string | null;
  overrides: string[];
  synthetic_ratio: number;
  data_mode: string;
  source_type: string;
  source_name: string;
  observed_at: string;
  confidence: number;
  synthetic_share: number;
  evidence_count: number;
  report_count: number;
  gate_count: number;
  fallback_count: number;
  source_meta: SourceLayerMetadata;
}

export interface RunDossierSummary {
  run_id: string;
  asset_ticker: string;
  report_title: string;
  report_version: string;
  report_thesis: string;
  report_body_markdown: string | null;
  judge_verdict: string;
  judge_score: number;
  gate_count: number;
  gating_reasons: string[];
  fallback_count: number;
  fallback_reasons: string[];
  recommendation_action: string;
  recommendation_reasoning: string;
  recommendation_guardrails: string[];
  mode: string;
  provider: string;
  as_of: string | null;
  overrides: string[];
  synthetic_ratio: number;
  confidence: number;
  model_name: string;
  model_version: string;
  model_status: string;
  risk_probability: number | null;
  feature_coverage: number;
  missing_features: string[];
  deployment_approved: boolean;
  inference_warnings: string[];
  model_diagnostic?: ModelDiagnostic | null;
  synthetic_share: number;
  risk_level: string;
  risk_summary: string;
  risk_stale_after: string | null;
  price_freshness_status: string;
  evidence_freshness_status: string;
  refresh_recommendation: string;
  stale_reasons: string[];
  evidence_citation_ids: string[];
  source_meta: SourceLayerMetadata;
}

export interface RunScopeSummary {
  run_id: string;
  asset_id: string;
  mode: string;
  provider: string;
  as_of: string | null;
  overrides: string[];
  synthetic_ratio: number;
  evidence_ids: string[];
  report_ids: string[];
  evidence_count: number;
  report_count: number;
  source_meta: SourceLayerMetadata;
}

export interface RunLineageDetailSummary {
  run_id: string;
  asset_id: string;
  input_snapshot_ref: string;
  intake_strategy: string;
  captured_at: string;
  mode: string;
  provider: string;
  as_of: string | null;
  overrides: string[];
  synthetic_ratio: number;
  data_modes: string[];
  source_types: string[];
  latest_close: number | null;
  price_provider_name: string;
  price_provider_version: string;
  price_provider_status: string;
  evidence_provider_name: string;
  evidence_provider_version: string;
  evidence_provider_status: string;
  judge_verdict: string;
  judge_score: number;
  recommendation_action: string;
  recommendation_reasoning: string;
  model_confidence: number;
  model_name: string;
  model_version: string;
  model_status: string;
  risk_probability: number | null;
  feature_coverage: number;
  missing_features: string[];
  deployment_approved: boolean;
  inference_warnings: string[];
  model_diagnostic?: ModelDiagnostic | null;
  report_version: string;
  report_title: string | null;
  fallback_reasons: string[];
  price_freshness_status: string;
  evidence_freshness_status: string;
  refresh_recommendation: string;
  stale_reasons: string[];
  evidence_citation_ids: string[];
  source_meta: SourceLayerMetadata;
}

export interface RunLineageEntry {
  run_id: string;
  created_at: string;
  input_snapshot_ref: string;
  mode: string;
  provider: string;
  as_of?: string | null;
  overrides: string[];
  evidence_count: number;
  synthetic_share: number;
  real_share: number;
  evidence_items: Array<{
    id: string;
    title: string;
    summary: string;
    source_type: string;
    data_mode: string;
  }>;
  report_id?: string | null;
  report_title?: string | null;
  report_version?: string | null;
  report_thesis?: string | null;
  report_generated_at?: string | null;
  judge_verdict?: string | null;
  judge_score?: number | null;
  recommendation_action?: string | null;
  recommendation_reasoning?: string | null;
  model_version?: string | null;
  price_provider_status: string;
  evidence_provider_status: string;
  fallback_reasons: string[];
  gating_reasons: string[];
  audit_actions: string[];
}

export interface RunLineageTimeline {
  asset_id: string;
  entries: RunLineageEntry[];
}

export interface DomainCatalog {
  entities: string[];
  data_modes: string[];
  data_source_types: string[];
  mode_policies: Array<{
    data_mode: string;
    allowed_source_types: string[];
    description: string;
    judge_gate_reason?: string | null;
  }>;
  analysis_provider_config: {
    market_data_provider: string;
    evidence_provider: string;
  };
  analysis_providers: Array<{
    provider_name: string;
    provider_version: string;
    kind: string;
  }>;
  principles: string[];
}

export interface AuthResponse {
  user: User;
  access_expires_at: string;
  refresh_expires_at: string;
}

export interface TestOfficerManifest {
  project: {
    id: string;
    name: string;
    description?: string;
    status: string;
  };
  targetApp: {
    id: string;
    name: string;
    baseUrl: string;
    status: string;
    metadata?: Record<string, unknown>;
    auth?: {
      strategy: "none" | "basic" | "session" | "oauth" | "custom";
      credentialRef?: string;
    };
    environments?: string[];
    runtime?: TestOfficerRuntimeConfig;
  };
  mission: {
    id: string;
    name: string;
    objective: string;
    mode: string;
    status: string;
  };
  scenarios: Array<{
    id: string;
    name: string;
    goal: string;
    tags: string[];
    targetPageId: string;
  }>;
  oracles: Array<{
    id: string;
    name: string;
  }>;
  run: {
    id: string;
    mode: string;
    status: string;
    reviewStatus: string;
    startedAt?: string;
    finishedAt?: string;
    metadata?: {
      executionConfig?: {
        executor?: string;
        headless?: boolean;
        trace?: boolean;
        recordVideo?: boolean;
      };
      runtimeLifecycle?: Array<{
        phase: string;
        status: string;
        startedAt: string;
        finishedAt?: string;
        summary: string;
        exitCode?: number | null;
        error?: string;
        attempts?: number;
      }>;
      [key: string]: unknown;
    };
    bundle: {
      rootDir: string;
      manifestPath: string;
      artifactsDir: string;
      evidenceDir: string;
      reportsDir: string;
      registry?: {
        rootDir: string;
        resourceManifestPath: string;
        onboardingProtocolPath?: string;
        missionPackagePath?: string;
        selectorMapsPath?: string;
        fixturesPath?: string;
        scenariosPath: string;
        oraclesPath: string;
        artifactsPath: string;
        evidencePath: string;
        judgeReportPath?: string;
        sourceContextsPath?: string;
        failureAttributionsPath?: string;
        retentionCleanupPlanPath?: string;
        resourceManifestUrl?: string;
        resourceUrls?: {
          onboardingProtocol?: string;
          missionPackage?: string;
          selectorMaps?: string;
          fixtures?: string;
          scenarios?: string;
          oracles?: string;
          artifacts?: string;
          evidence?: string;
          judgeReport?: string;
          sourceContexts?: string;
          failureAttributions?: string;
          retentionCleanupPlan?: string;
        };
      };
      manifestUrl?: string;
      reportUrls?: {
        json?: string;
        junit?: string;
        markdown?: string;
        html?: string;
        comparison?: string;
        gate?: string;
        prAnnotation?: string;
        githubAnnotations?: string;
        ciArtifactManifest?: string;
        retentionJob?: string;
        integrity?: string;
        downloadManifest?: string;
      };
      artifactAccess?: {
        tokenRequired: boolean;
        header: string;
        runTokenHeader?: string;
        runToken?: string | null;
        runTokenScope?: string;
        devLoopbackOnly?: boolean;
        signedUrlTtlSeconds?: number;
        runTokenTtlSeconds?: number;
      };
    };
  };
  plan: Array<{
    id: string;
    scenarioId: string;
    stepId?: string;
    title: string;
    sequence: number;
    intent: string;
    action: string;
    selectorRef?: string;
    inputRef?: string;
    expectedOutcome?: string;
    evidenceRequirements?: string[];
    assertions?: Array<{
      id: string;
      kind: string;
      target: string;
      expected: string;
      requiredEvidence?: string[];
    }>;
    failureCriteria?: Array<{
      id: string;
      category: string;
      condition: string;
      severity: string;
    }>;
    retryPolicy?: {
      maxAttempts: number;
      retryOn: string[];
      backoffMs: number;
    };
    fixtureRefs?: string[];
    selectorMapId?: string;
    sourceMode: string;
    status: string;
    rationale?: string;
    plannedAt: string;
    updatedAt: string;
  }>;
  steps: Array<{
    id: string;
    scenarioId: string;
    title: string;
    intent: string;
    action: string;
    status: string;
    sequence: number;
    selectorRef?: string;
    expectedOutcome?: string;
    evidenceRequirements?: string[];
    assertions?: Array<{
      id: string;
      kind: string;
      target: string;
      expected: string;
      requiredEvidence?: string[];
    }>;
    failureCriteria?: Array<{
      id: string;
      category: string;
      condition: string;
      severity: string;
    }>;
    retryPolicy?: {
      maxAttempts: number;
      retryOn: string[];
      backoffMs: number;
    };
    startedAt?: string;
    finishedAt?: string;
  }>;
  evidence: Array<{
    id: string;
    stepId?: string;
    scenarioId: string;
    kind: string;
    status: string;
    summary: string;
    artifactIds: string[];
    capturedAt: string;
    metadata?: {
      relativePath?: string;
      [key: string]: unknown;
    };
  }>;
  artifacts: Array<{
    id: string;
    evidenceId: string;
    kind: string;
    status: string;
    path: string;
    mediaType: string;
    sizeBytes: number;
    metadata?: {
      relativePath?: string;
      previewMode?: string;
      inlinePreview?: string;
      artifactUrl?: string;
      [key: string]: string | number | boolean | undefined;
    };
  }>;
  findings: Array<{
    id: string;
    scenarioId: string;
    category: string;
    severity: string;
    status: string;
    title: string;
    summary: string;
    recommendation?: string;
    evidenceIds: string[];
  }>;
  oracleEvaluations: Array<{
    id: string;
    runId: string;
    scenarioId: string;
    oracleId: string;
    result: string;
    summary: string;
    evidenceIds: string[];
    checkResults: Array<{
      checkId: string;
      name: string;
      kind: string;
      requiredEvidence: string[];
      result: string;
      summary: string;
      evidenceIds: string[];
    }>;
  }>;
  judgeReport?: {
    id: string;
    result: string;
    narrative: string;
    metadata?: {
      source?: string;
      executionMode?: string;
      llmStatus?: string;
      policyVersion?: string;
      [key: string]: string | number | boolean | null | undefined;
    };
    machineSummary: {
      decision: string;
      confidence: number;
      flaky: boolean;
      blocked: boolean;
    };
  };
  sourceContexts?: Array<{
    schemaVersion: "1.0";
    adapter: {
      id: string;
      kind: "git-diff" | "github-pr" | "github-issue" | "jira-issue" | "requirement-doc" | "bug-ticket" | "api-doc";
      label: string;
      permissions: Array<"workspace-read" | "network-read" | "credential-read">;
      usageScopes: Array<"planning" | "oracle" | "judge" | "failure-analysis" | "reporting">;
      sourceRef: string;
      maxBytes?: number;
    };
    readState: "unread" | "reading" | "ready" | "failed" | "blocked";
    readAt: string;
    failureReason?: string;
    payload?: unknown;
    metadata: {
      byteLength: number;
      truncated: boolean;
      contentType?: string;
      retry?: {
        attempts: number;
        maxAttempts: number;
        retryable: boolean;
        lastStatus?: number;
      };
      pagination?: {
        pagesRead: number;
        itemCount?: number;
        hasNextPage: boolean;
        nextPageUrl?: string;
      };
      rateLimit?: {
        limit?: number;
        remaining?: number;
        resetAt?: string;
        retryAfterSeconds?: number;
      };
      cache?: {
        status: "hit" | "miss" | "stale" | "bypass" | "write-failed";
        key?: string;
        path?: string;
        expiresAt?: string;
      };
      version?: {
        sha256?: string;
        etag?: string;
        lastModified?: string;
        documentVersion?: string;
      };
      trust?: {
        level: "trusted" | "verified" | "unverified" | "low-confidence";
        reasons: string[];
      };
      permissionExplanations?: Array<{
        permission: "workspace-read" | "network-read" | "credential-read";
        reason: string;
      }>;
    };
  }>;
  failureAttributions?: Array<{
    id: string;
    schemaVersion: "1.0";
    runId: string;
    findingId: string;
    scenarioId: string;
    stepId?: string;
    rank: number;
    category: string;
    confidence: number;
    likelyCause: string;
    recommendation: string;
    signals: {
      evidenceIds: string[];
      artifactIds: string[];
      sourceContextIds: string[];
      changedFiles: string[];
      consoleErrorArtifacts: string[];
      consoleErrorSummaries?: string[];
      networkErrorArtifacts: string[];
      networkErrorSummaries?: string[];
      domSnapshotArtifacts: string[];
      retrySignals?: {
        attemptCount?: number;
        maxAttempts?: number;
        retried?: boolean;
        lastRetryTrigger?: string;
      };
      runtimeSignals?: Array<{
        phase: string;
        status: string;
        summary?: string;
      }>;
    };
    createdAt: string;
  }>;
  retentionCleanupPlan?: {
    schemaVersion: "1.0";
    runId: string;
    generatedAt: string;
    policy: {
      retainRunsDays: number;
      retainArtifactsDays: number;
      retainReportsDays: number;
      retainTraceDays: number;
      retainVideoDays: number;
      dryRun: boolean;
    };
    candidates: Array<{
      id: string;
      kind: "artifact" | "evidence" | "report" | "registry" | "playwright-trace" | "video" | "source-context";
      path: string;
      action: "retain" | "delete-after-retention" | "archive-after-retention";
      reason: string;
      expiresAt?: string;
      sizeBytes?: number;
      artifactId?: string;
      evidenceId?: string;
      protected: boolean;
    }>;
  };
}

export interface TestOfficerHistoryEntry {
  runId: string;
  missionId: string;
  missionName: string;
  targetAppId: string;
  targetAppName: string;
  status: string;
  reviewStatus: string;
  startedAt?: string;
  finishedAt?: string;
  manifestPath: string;
  findingCount: number;
  failedStepCount: number;
  artifactCount: number;
}

export interface TestOfficerHistoryIndex {
  schemaVersion: "1.0";
  generatedAt: string;
  runs: TestOfficerHistoryEntry[];
}

export interface TestOfficerComparisonReport {
  schemaVersion: "1.0";
  baselineRunId: string;
  currentRunId: string;
  missionId: string;
  summary: {
    statusChanged: boolean;
    reviewChanged: boolean;
    findingDelta: number;
    failedStepDelta: number;
    artifactDelta: number;
    artifactSignalDelta?: number;
    failureAttributionDelta?: number;
    confidenceDelta?: number;
    riskScoreDelta?: number;
    riskTrend?: "improved" | "regressed" | "stable";
  };
  judgeDecisionChange?: {
    baselineResult?: string;
    currentResult?: string;
    baselineDecision?: string;
    currentDecision?: string;
    baselineConfidence?: number;
    currentConfidence?: number;
    confidenceDelta: number;
    decisionChanged: boolean;
    flakyChanged: boolean;
    blockedChanged: boolean;
  };
  stepChanges: Array<{
    stepTitle: string;
    baselineStatus: string;
    currentStatus: string;
    changed: boolean;
  }>;
  findingChanges: {
    added: string[];
    resolved: string[];
    unchanged: string[];
  };
  failureAttributionChanges?: {
    added: string[];
    resolved: string[];
    unchanged: string[];
    topCurrent: string[];
  };
  artifactSignalChanges: {
    added: string[];
    resolved: string[];
    unchanged: string[];
  };
}

export interface TestOfficerRegistryManifestEntry {
  kind:
    | "onboarding-protocol"
    | "mission-package"
    | "selector-map-registry"
    | "fixture-registry"
    | "scenario-registry"
    | "oracle-registry"
    | "artifact-index"
    | "evidence-index"
    | "judge-report"
    | "source-context-registry"
    | "failure-attribution-registry"
    | "retention-cleanup-plan";
  path: string;
  recordCount: number;
}

export interface TestOfficerRegistryManifest {
  schemaVersion: "1.0";
  runId: string;
  missionId: string;
  generatedAt: string;
  entries: TestOfficerRegistryManifestEntry[];
  counts: {
    onboardingProtocols: number;
    missionPackages: number;
    selectorMaps: number;
    fixtures: number;
    scenarios: number;
    oracles: number;
    artifacts: number;
    evidence: number;
    judgeReports: number;
    sourceContexts?: number;
    failureAttributions?: number;
    retentionPlans?: number;
  };
}

export interface TestOfficerOnboardingKeyPage {
  id?: string;
  name?: string;
  path: string;
  selectors?: Array<{
    id: string;
    description?: string;
    preferredStrategies?: string[];
    queries: string[];
  }>;
  tags?: string[];
}

export interface TestOfficerOnboardingSelectorHint {
  id?: string;
  pagePath?: string;
  pageId?: string;
  description?: string;
  preferredStrategies?: string[];
  queries: string[];
  tags?: string[];
}

export interface TestOfficerOnboardingProtocolResource {
  baseUrl: string;
  accountRef?: string | null;
  auth?: {
    strategy: string;
    accountRef?: string;
    loginPagePath?: string;
    notes?: string;
  };
  project?: {
    slug?: string;
    name?: string;
    description?: string;
  };
  targetApp?: {
    name?: string;
    environments?: string[];
    defaultMode?: string;
  };
  keyPages: Array<string | TestOfficerOnboardingKeyPage>;
  businessObjective: string;
  selectorHints: Array<string | TestOfficerOnboardingSelectorHint>;
  scenarioRequests: Array<{
    family: TestOfficerScenarioFamily;
    id?: string;
    name?: string;
    goal?: string;
    pagePath?: string;
    required?: boolean;
    fixtureRefs?: string[];
    selectorHintIds?: string[];
    evidenceRequirements?: string[];
    failureClasses?: string[];
  }>;
}

export interface TestOfficerEvidenceRegistryResource {
  id: string;
  runId: string;
  stepId?: string;
  scenarioId: string;
  kind: string;
  status: string;
  summary: string;
  artifactIds: string[];
  capturedAt: string;
  metadata?: {
    relativePath?: string;
    [key: string]: unknown;
  };
}

export interface TestOfficerJudgeReportResource {
  id: string;
  runId: string;
  oracleIds: string[];
  findingIds?: string[];
  status: string;
  result: string;
  narrative: string;
  metadata?: {
    source?: string;
    executionMode?: string;
    llmStatus?: string;
    policyVersion?: string;
    [key: string]: unknown;
  };
  machineSummary: {
    decision: string;
    confidence: number;
    flaky: boolean;
    blocked: boolean;
  };
}

export interface TestOfficerMissionPackageResource {
  project: {
    id: string;
    name: string;
    status: string;
    description?: string;
  };
  targetApp: {
    id: string;
    name: string;
    baseUrl: string;
    status: string;
    auth?: {
      strategy: string;
      credentialRef?: string;
    };
    environments?: string[];
    pages?: Array<{
      id: string;
      name: string;
      path: string;
      selectors?: Array<{
        id: string;
        preferredStrategies?: string[];
        queries: string[];
      }>;
    }>;
  };
  mission: {
    id: string;
    name: string;
    objective: string;
    mode: string;
    status: string;
    accountRef?: string;
    selectorHintRefs?: string[];
  };
  scenarios: Array<{
    id: string;
    name: string;
    goal: string;
    tags?: string[];
    targetPageId?: string;
    fixtureRefs?: string[];
    evidenceRequirements?: string[];
    failureClasses?: string[];
  }>;
  oracles: Array<{
    id: string;
    name: string;
    scenarioId?: string;
    checks?: Array<{
      id: string;
      name: string;
      kind: string;
      requiredEvidence: string[];
    }>;
    passPolicy?: string;
  }>;
  counts: {
    pages: number;
    selectorHints: number;
    scenarios: number;
    oracles: number;
  };
}

export interface TestOfficerSelectorMapResource {
  id: string;
  appId: string;
  entries: Array<{
    id: string;
    description?: string;
    preferredStrategies: string[];
    queries: string[];
  }>;
}

export interface TestOfficerFixtureRegistryResource {
  id: string;
  scenarioId?: string;
  kind: string;
  manifestRef: string;
}

export interface TestOfficerScenarioRegistryResource {
  id: string;
  type: string;
  schemaVersion: string;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
  projectId: string;
  targetAppId: string;
  status: string;
  name: string;
  goal: string;
  tags: string[];
  targetPageId: string;
  fixtureRefs: string[];
  selectorMapId: string;
  steps: Array<{
    id: string;
    title: string;
    intent: string;
    action: string;
    selectorRef?: string;
    inputRef?: string;
    expectedOutcome?: string;
    evidenceRequirements: string[];
  }>;
  expectedFindings: string[];
  failureClasses: string[];
  evidenceRequirements: string[];
}

export interface TestOfficerOracleRegistryResource {
  id: string;
  type: string;
  schemaVersion: string;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
  scenarioId: string;
  status: string;
  name: string;
  checks: Array<{
    id: string;
    name: string;
    kind: string;
    description: string;
    requiredEvidence: string[];
  }>;
  passPolicy: string;
}

export type TestOfficerScenarioFamily =
  | "auth-login"
  | "golden-path"
  | "form-submission"
  | "list-state-change";

export interface TestOfficerOnboardingScenarioRequest {
  family: TestOfficerScenarioFamily;
  pagePath: string;
  enabled: boolean;
}

export interface TestOfficerRuntimeEnvVar {
  name: string;
  value?: string | null;
  secretRef?: string | null;
  required?: boolean;
  scope?: "launch" | "test" | "cleanup";
}

export interface TestOfficerRuntimeCommand {
  command: string;
  args?: string[];
  cwd?: string | null;
  env?: TestOfficerRuntimeEnvVar[];
  timeoutMs?: number | null;
}

export interface TestOfficerRuntimeHealthCheck {
  url: string;
  expectedStatus?: number[];
  timeoutMs?: number;
  intervalMs?: number;
  retries?: number;
}

export interface TestOfficerRuntimeRoute {
  id: string;
  path: string;
  purpose?: "login" | "home" | "workflow" | "admin" | "api" | "health" | "custom";
  authenticated?: boolean;
}

export interface TestOfficerRuntimeAccount {
  id: string;
  role: string;
  credentialRef: string;
  username?: string | null;
}

export interface TestOfficerRuntimeConfig {
  start?: TestOfficerRuntimeCommand | null;
  healthCheck?: TestOfficerRuntimeHealthCheck | null;
  routes?: TestOfficerRuntimeRoute[];
  testAccounts?: TestOfficerRuntimeAccount[];
  env?: TestOfficerRuntimeEnvVar[];
  cleanup?: TestOfficerRuntimeCommand | null;
}

export interface TestOfficerOnboardingDraft {
  projectName: string;
  targetAppName: string;
  baseUrl: string;
  accountRef: string;
  authStrategy?: "none" | "basic" | "session" | "oauth" | "custom";
  loginPagePath?: string | null;
  authNotes?: string | null;
  environments?: string[];
  runtime?: TestOfficerRuntimeConfig | null;
  workspaceRoot?: string | null;
  prUrl?: string | null;
  requirementDocs?: string[];
  bugTickets?: string[];
  apiDocs?: string[];
  gitDiffs?: string[];
  githubIssues?: string[];
  jiraIssues?: string[];
  openApiUrls?: string[];
  requirementText?: string | null;
  businessObjective: string;
  mode: "scripted" | "plan-assisted" | "ai-exploratory";
  keyPages: string[];
  selectorHints: string[];
  scenarioRequests: TestOfficerOnboardingScenarioRequest[];
}

export interface TestOfficerOnboardingPreview {
  missionName: string;
  readiness: "ready" | "partial";
  requiredMissing: string[];
  selectorCoverage: number;
  enabledScenarioCount: number;
  pageCount: number;
  scenarios: Array<{
    family: TestOfficerScenarioFamily;
    pagePath: string;
    enabled: boolean;
    label: string;
    goal: string;
  }>;
}

export interface TestOfficerMissionPreview {
  project: {
    id: string;
    name: string;
    status: string;
    description?: string;
  };
  targetApp: {
    id: string;
    name: string;
    baseUrl: string;
    status: string;
  };
  mission: {
    id: string;
    name: string;
    objective: string;
    mode: string;
    status: string;
  };
  scenarios: Array<{
    id: string;
    name: string;
    goal: string;
    tags?: string[];
    targetPageId?: string;
  }>;
  oracles: Array<{
    id: string;
    name: string;
  }>;
  counts: {
    pages: number;
    selectorHints: number;
    scenarios: number;
    oracles: number;
  };
}

export interface TestOfficerRunRequest extends TestOfficerOnboardingDraft {
  executor?: "memory" | "playwright";
  headless?: boolean;
  trace?: boolean;
  recordVideo?: boolean;
}

export interface TestOfficerRunResponse {
  runId: string;
  status: string;
  reviewStatus: string;
  executor: "memory" | "playwright";
  headless: boolean;
  trace: boolean;
  recordVideo: boolean;
  manifest: TestOfficerManifest;
  gate?: {
    passed: boolean;
    exitCode: number;
    reasons: string[];
    diagnostics?: {
      newFindings?: string[];
      newArtifactSignals?: string[];
      regression?: {
        statusChanged: boolean;
        reviewChanged: boolean;
        failedStepDelta: number;
        findingDelta: number;
        artifactSignalDelta: number;
      };
      policy?: {
        failOnNewFindings: boolean;
        failOnRegression: boolean;
        allowFlaky: boolean;
        allowBlocked: boolean;
      };
      flakyQuarantine?: {
        enabled: boolean;
        label: string;
        reason?: string;
      };
    };
  };
}

export type TestOfficerCredentialKind = "api-key" | "test-account" | "connector-token" | "custom";

export interface TestOfficerCredentialSummary {
  id: string;
  label: string;
  kind: TestOfficerCredentialKind;
  username?: string | null;
  metadata: Record<string, string>;
  createdAt: string;
  updatedAt: string;
  secretPreview: string;
  secretLength: number;
}

export interface TestOfficerCredentialUpsertRequest {
  id: string;
  label: string;
  kind: TestOfficerCredentialKind;
  secret: string;
  username?: string | null;
  metadata?: Record<string, string>;
}

export interface TestOfficerAuditRun {
  runId: string;
  projectId: string;
  missionId: string;
  missionName: string;
  targetAppId: string;
  targetAppName: string;
  status: string;
  reviewStatus: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  bundleUri: string;
  createdAt: string;
  updatedAt: string;
}

export interface TestOfficerAuditRunDetail {
  runId: string;
  sourceContexts: Array<{
    id: string;
    kind: string;
    readState: string;
    sourceRef: string;
    failureReason?: string | null;
    permissions: string[];
    usageScopes: string[];
  }>;
  failureAttributions: Array<{
    id: string;
    findingId: string;
    scenarioId: string;
    stepId?: string | null;
    rank: number;
    category: string;
    confidence: number;
    likelyCause?: string | null;
    recommendation?: string | null;
    signals?: Record<string, unknown>;
  }>;
  artifacts: Array<{
    id: string;
    evidenceId: string;
    kind: string;
    status: string;
    artifactUri: string;
    mediaType: string;
    sizeBytes: number;
    metadata: Record<string, unknown>;
  }>;
  gateResults: Array<{
    id: string;
    passed: boolean;
    exitCode: number;
    reasons: string[];
    diagnostics: Record<string, unknown>;
    generatedAt: string;
  }>;
  runtimeLifecycle: Array<{
    id: string;
    phase: string;
    status: string;
    summary?: string | null;
  }>;
}
