export type PreferenceKey = "balanced" | "conservative" | "growth" | "trading" | "fund";

export interface SourceMeta {
  mode: "demo" | "sandbox" | "real" | string;
  provider: string;
  as_of: string;
  overrides: string[];
  synthetic_ratio: number;
}

export interface DataModePayload {
  mode: "demo" | "sandbox" | "real" | string;
  label: string;
  description: string;
  providerPolicy: string;
  allowedModes: string[];
  sourceMeta: SourceMeta;
}

export interface Holding {
  symbol: string;
  name: string;
  market: "us" | "cn";
  sector: string;
  shares: number;
  costValue: number;
  marketValue: number;
  weight: number;
  dayChange: number;
  dataSource?: string;
  dataStatus?: string;
  observedAt?: string;
  sourceMeta?: SourceMeta;
}

export interface EvidenceRecord {
  id: number;
  claim: string;
  sourceType: "market_data" | "financial_report" | "disclosure" | "news_event" | "historical_analogy" | "model_inference";
  sourceName: string;
  sourceUrl?: string | null;
  observedAt: string;
  validUntil: string;
  confidence: number;
  isModelInferred: boolean;
  isExpired: boolean;
  supersededBy?: number | null;
  archivedAt?: string | null;
  sourceMeta?: SourceMeta;
}

export interface ToolCallRecord {
  id: number;
  runId: string;
  toolId: string;
  name: string;
  category: string;
  description: string;
  freshnessRule: string;
  outputContract: string;
  symbol: string;
  input: Record<string, unknown>;
  outputSummary: string;
  sourceName: string;
  observedAt: string;
  status: "success" | "degraded" | "failed";
  failureReason?: string | null;
  evidenceId?: number | null;
}

export interface EvidenceGraph {
  summary: string;
  claims: Array<{
    id: string;
    title: string;
    claim: string;
    status: "supported" | "contested" | "unsupported" | "pending";
    supportingEvidenceIds: number[];
    rebuttingEvidenceIds: number[];
    derivedMetrics: string[];
    dependsOnExpiredEvidenceIds: number[];
    judgeNote: string;
  }>;
  edges: Array<{ from: string; to: string; relation: "supports" | "rebuts" | "derived"; label: string }>;
  expiredEvidenceIds: number[];
}

export interface ReportRevisionLoop {
  draftStatus: string;
  judgeVerdict: string;
  toolBackfillActions: string[];
  degradedClaims: string[];
  finalStatus: string;
  revisedSummary: string;
  blockedBy: string[];
}

export interface HistoricalAnalogy {
  asOfDate: string;
  pattern: string;
  similarity: number;
  return1w: number;
  return1m: number;
  return3m: number;
  maxDrawdown: number;
  dataSource?: string;
  note: string;
  sourceMeta?: SourceMeta;
}

export interface ExperienceRecord {
  id: number;
  symbol: string;
  archived_claim: string;
  source_type: string;
  observed_at: string;
  archived_at: string;
  reason: string;
}

export interface PortfolioPayload {
  holdings: Holding[];
  portfolioCurve: number[];
  portfolioCurveSource: string;
  sectorExposure: Array<{ name: string; value: number; color: string }>;
  metrics: {
    marketValue: number;
    cost: number;
    todayPnl: number;
    totalReturn: number;
    topWeight: number;
  };
  riskRadar: Array<{ label: string; value: number }>;
  preference: { label: string; description: string };
  events: Array<{ title: string; summary: string; tone: "good" | "warn" | "neutral" }>;
  cacheStatus: { label: string; asOf: string };
  sourceMeta?: SourceMeta;
  dataMode?: DataModePayload;
  onboardingRequired?: boolean;
}

export interface ResearchPayload {
  symbol: string;
  name: string;
  market: "us" | "cn";
  riskLabel: string;
  riskLevel: "low" | "medium" | "high";
  profile: { label: string; description: string };
  run?: {
    runId: string;
    riskScore: number;
    summary: string;
    startedAt: string;
    finishedAt: string;
    dataStatus: string;
    inputSnapshotHash?: string;
    modelVersion?: string;
    evidenceIds?: number[];
    reasoningSteps?: Array<{ role: string; kind: "Agent" | "Skill"; status: string; output: string }>;
    judge?: Record<string, unknown>;
    riskConclusion?: Record<string, unknown>;
    reportVersion?: string;
    reportPath?: string;
    sourceMeta?: SourceMeta;
  };
  sourceMeta?: SourceMeta;
  dataMode?: DataModePayload;
  documentBlocks: Array<{ title: string; text: string }>;
  agentWorkflow: Array<{ role: string; kind: "Agent" | "Skill"; status: string; output: string }>;
  toolCalls: ToolCallRecord[];
  documentAnalysis: {
    documentId: string;
    filename: string;
    uploadedAt: string;
    sourceType: string;
    sourceMeta?: SourceMeta;
    summary: string;
    blocks: Array<{ type: string; label: string; count: number; status: string }>;
    metrics: Array<{ metric_name: string; metric_value: string; period: string; source_block: string }>;
    chartSummary: string;
    blockPreviews: Array<{ block_type: string; label: string; locator: string; content_preview: string }>;
  };
  qualityGate?: {
    status: "WARN" | "HOLD" | "BLOCK" | string;
    reasons: string[];
    expiredEvidenceCount: number;
    missingTypes: string[];
    syntheticRatio: number;
    modelConfidence: number;
    summary: string;
  };
  evidenceAudit: {
    score: number;
    verdict: string;
    scope: string;
    dimensions: Array<{ key: string; label: string; passed: boolean; severity: string; detail: string }>;
    findings: Array<{ severity: string; title: string; detail: string }>;
    authoritySources: Array<{ name: string; url: string; authority: string; status: string }>;
    checks: Array<{ name: string; passed: boolean }>;
    judgeVersion?: string;
    v2Checks?: Record<string, boolean>;
  };
  evidenceGraph: EvidenceGraph;
  reportRevisionLoop: ReportRevisionLoop;
  mlRiskSummary?: {
    modelStatus: "valid" | "stale" | "missing";
    symbol?: string;
    market?: "us" | "cn";
    asOfDate?: string;
    modelId?: string;
    modelType?: string;
    trainedUntil?: string | null;
    calibrationStatus: "valid" | "stale" | "failed" | "missing";
    riskRegime?: "low" | "medium" | "high";
    drawdownP50_1m?: number;
    drawdownP90_1m?: number;
    drawdownP95_1m?: number;
    volatilityP50_1m?: number;
    volatilityP90_1m?: number;
    varBreachProbability?: number;
    varThreshold?: number;
    highRiskRegime?: boolean;
    confidence?: number;
    validUntil?: string;
    riskDistribution?: {
      horizon: string;
      scenarioCount: number;
      drawdownQuantiles: { p50: number; p90: number; p95: number };
      drawdownQuantiles1w?: { p50: number; p90: number; p95: number };
      drawdownQuantiles1m?: { p50: number; p90: number; p95: number };
      volatilityQuantiles: { p50: number; p90: number };
      varBreach: { threshold: number; breachCount: number; breachProbability: number };
      riskRegime: "low" | "medium" | "high";
      highRiskRegime: boolean;
      method: string;
      disclaimer: string;
    };
    featureStoreAudit?: {
      ok: boolean;
      status?: string;
      asOfDate?: string;
      checkedFieldCount: number;
      missingFieldCount?: number;
      futureLeakageCount: number;
      violations: string[];
    };
    validationMetrics?: Record<string, unknown>;
    similarScenarioCount?: number;
    similarScenarios: Array<{
      matchedSymbol: string;
      matchedAsOfDate: string;
      similarity: number;
      return1w: number;
      return1m: number;
      return3m: number;
      maxDrawdown1w?: number;
      maxDrawdown1m: number;
      maxDrawdown3m: number;
      volatility1m?: number;
      modelId: string;
    }>;
    summary: string;
    sourceMeta?: SourceMeta;
  };
  tokenCompressionReport?: {
    symbol: string;
    rawTokenEstimate: number;
    structuredTokenEstimate: number;
    tokenReductionPercent: number;
    rawBreakdown: Record<string, number>;
    structuredBreakdown: Record<string, number>;
    conclusionConsistency: number;
    consistencyChecks: Array<{ name: string; passed: boolean; detail: string }>;
    method: string;
    summary: string;
    sourceMeta?: SourceMeta;
  };
  conditionAlignment: {
    summary: string;
    matchedScenarioCount: number;
    factors: Array<{ factor: string; current: string; historical: string; matched: boolean }>;
  };
  preferenceWeights: Array<{ factor: string; weight: number }>;
  reportSettings: { frequency: string; updatedAt: string; description: string };
  reportVersions: {
    current?: unknown;
    delta: { hasPrevious: boolean; previousRunId?: string; riskScoreDelta: number; summary: string };
    recentRuns: Array<{ runId: string; startedAt: string; riskScore: number; summary: string; reportVersion?: string; qualityGateStatus?: string; reportPath?: string; sourceMeta?: SourceMeta }>;
  };
  debate: {
    bull: string[];
    bear: string[];
    judge: { stance: string; detail: string };
    invalidators: string[];
  };
  observationChecklist: Array<{ item: string; trigger: string; frequency: string; status: string }>;
  evidence: EvidenceRecord[];
  historicalAnalogies: HistoricalAnalogy[];
  priceSeries: Array<{ date: string; close: number; volume: number; sourceName?: string; sourceMeta?: SourceMeta }>;
  experienceHistory: ExperienceRecord[];
}

export type HoldingInput = {
  symbol: string;
  name: string;
  market: "us" | "cn";
  shares: string;
  costPrice: string;
  sector: string;
};

export interface UserProfile {
  id: number;
  email: string;
  role: "user" | "developer";
  createdAt: string;
  onboardingCompleted: boolean;
  preference: PreferenceKey;
}

export interface UserProfileState {
  preference: PreferenceKey;
  riskAnswers: Record<string, unknown>;
  onboardingCompleted: boolean;
  updatedAt?: string | null;
}

export interface ApiKeySummary {
  provider: string;
  maskedKey: string;
  updatedAt: string;
  enabled: boolean;
}

export interface AuthPayload {
  token: string;
  accessToken?: string;
  accessExpiresAt?: string;
  refreshExpiresAt?: string;
  user: UserProfile;
  profile: UserProfileState;
  apiKeys: ApiKeySummary[];
  dataMode?: DataModePayload;
  sourceMeta?: SourceMeta;
}

export interface RefreshReviewPayload {
  ok: boolean;
  refreshId: string;
  refreshedAt: string;
  count: number;
  summary: string;
  items: Array<{
    symbol: string;
    beforeScore: number;
    afterScore: number;
    riskScoreDelta: number;
    beforeClaimSummary: string;
    afterClaimSummary: string;
    evidenceChanges: {
      newEvidenceIds: number[];
      archivedCount: number;
      expiredEvidenceIds: number[];
      supersededMarketEvidence: number[];
      supersededHistoryEvidence?: number[];
      supersededNewsEvidence?: number[];
      supersededDisclosureEvidence?: number[];
      supersededFinancialEvidence?: number[];
    };
    conclusionChanges: string[];
    snapshotStatus: string;
  }>;
  dataMode?: DataModePayload;
  sourceMeta?: SourceMeta;
}
