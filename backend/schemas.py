from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceMeta(BaseModel):
    mode: str
    provider: str
    as_of: str
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0


class UserProfileRecord(BaseModel):
    preference: str = "balanced"
    riskAnswers: dict[str, Any] = Field(default_factory=dict)
    onboardingCompleted: bool = False
    updatedAt: str | None = None


class PublicUserRecord(BaseModel):
    id: int
    email: str
    role: str = "user"
    createdAt: str
    onboardingCompleted: bool
    preference: str


class QualityGate(BaseModel):
    status: Literal["PASS", "WARN", "HOLD", "BLOCK"] | str
    reasons: list[str] = Field(default_factory=list)
    gatingReasons: list[str] = Field(default_factory=list)
    expiredEvidenceCount: int = 0
    missingTypes: list[str] = Field(default_factory=list)
    syntheticRatio: float = 0.0
    modelConfidence: float = 0.0
    summary: str = ""


class AnalysisRunCreate(BaseModel):
    symbol: str
    preference: str
    risk_score: float
    summary: str
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    model_version: str | None = None
    evidence_ids: list[int] = Field(default_factory=list)
    reasoning_steps: list[dict[str, Any]] = Field(default_factory=list)
    judge_payload: dict[str, Any] = Field(default_factory=dict)
    risk_conclusion: dict[str, Any] = Field(default_factory=dict)
    report_version: str | None = None
    source_meta: SourceMeta | None = None
    data_status: str = "live-first-cache-fallback"


class AnalysisRunRecord(BaseModel):
    runId: str
    symbol: str
    preference: str
    startedAt: str
    finishedAt: str
    dataStatus: str
    riskScore: float
    summary: str
    inputSnapshotHash: str | None = None
    inputSnapshot: dict[str, Any] = Field(default_factory=dict)
    modelVersion: str | None = None
    evidenceIds: list[int] = Field(default_factory=list)
    reasoningSteps: list[dict[str, Any]] = Field(default_factory=list)
    judge: dict[str, Any] = Field(default_factory=dict)
    riskConclusion: dict[str, Any] = Field(default_factory=dict)
    reportVersion: str
    sourceMeta: dict[str, Any] = Field(default_factory=dict)


class AnalysisRunInputSnapshot(BaseModel):
    holding: dict[str, Any]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    analogies: list[dict[str, Any]] = Field(default_factory=list)
    documentAnalysis: dict[str, Any] = Field(default_factory=dict)
    mlRiskSummary: dict[str, Any] = Field(default_factory=dict)
    qualityGate: dict[str, Any] = Field(default_factory=dict)


class RunSourceMeta(SourceMeta):
    pass


class ResearchRunSnapshot(BaseModel):
    inputSnapshotHash: str
    inputSnapshot: AnalysisRunInputSnapshot


class ResearchRun(AnalysisRunRecord):
    sourceMeta: RunSourceMeta | dict[str, Any] = Field(default_factory=dict)


class RiskConclusion(BaseModel):
    riskLabel: str
    riskLevel: str
    riskScore: float
    gateStatus: str


class AnalysisPipelineRunContext(BaseModel):
    summary: str
    inputSnapshot: AnalysisRunInputSnapshot
    modelVersion: str
    evidenceIds: list[int] = Field(default_factory=list)
    reasoningSteps: list[dict[str, Any]] = Field(default_factory=list)
    judgePayload: dict[str, Any] = Field(default_factory=dict)
    riskConclusion: RiskConclusion
    sourceMeta: dict[str, Any]


class RecentRunRecord(BaseModel):
    runId: str
    symbol: str
    preference: str
    startedAt: str
    riskScore: float
    summary: str
    reportVersion: str | None = None
    qualityGateStatus: str | None = None
    sourceMeta: dict[str, Any] = Field(default_factory=dict)


class ReportSnapshotRecord(BaseModel):
    run_id: str
    symbol: str
    preference: str
    report_version: str
    markdown: str
    created_at: str


class ReportSettingsRecord(BaseModel):
    frequency: str
    updatedAt: str
    description: str


class ToolInvocationRecord(BaseModel):
    id: int
    runId: str
    toolId: str
    name: str
    category: str
    description: str
    freshnessRule: str
    outputContract: str
    symbol: str
    input: dict[str, Any] = Field(default_factory=dict)
    outputSummary: str
    sourceName: str
    observedAt: str
    status: str
    failureReason: str | None = None
    evidenceId: int | None = None


class DocumentBlockSummary(BaseModel):
    type: str
    label: str
    count: int
    status: str


class DocumentMetricRecord(BaseModel):
    metric_name: str
    metric_value: str
    period: str
    source_block: str


class DocumentBlockPreview(BaseModel):
    block_type: str
    label: str
    locator: str
    content_preview: str


class DocumentAnalysisRecord(BaseModel):
    documentId: str
    filename: str
    uploadedAt: str
    sourceType: str
    sourceMeta: dict[str, Any]
    summary: str
    blocks: list[DocumentBlockSummary] = Field(default_factory=list)
    metrics: list[DocumentMetricRecord] = Field(default_factory=list)
    chartSummary: str
    blockPreviews: list[DocumentBlockPreview] = Field(default_factory=list)


class RefreshPayload(BaseModel):
    ok: bool
    refreshedAt: str
    count: int
    items: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    refreshId: str | None = None
    summary: str | None = None


class EvidenceRecord(BaseModel):
    id: int
    claim: str
    sourceType: str
    sourceName: str
    sourceUrl: str | None = None
    observedAt: str
    validUntil: str
    confidence: float
    isModelInferred: bool
    isExpired: bool
    supersededBy: int | None = None
    archivedAt: str | None = None
    sourceMeta: dict[str, Any]


class ExperienceHistoryRecord(BaseModel):
    id: int
    symbol: str
    archived_claim: str
    source_type: str
    observed_at: str
    archived_at: str
    reason: str


class HoldingSnapshot(BaseModel):
    symbol: str
    name: str
    market: str
    sector: str
    shares: float
    costValue: float
    marketValue: float
    weight: float
    dayChange: float
    dataSource: str | None = None
    dataStatus: str | None = None
    observedAt: str | None = None
    sourceMeta: dict[str, Any] | None = None


class PortfolioMetrics(BaseModel):
    marketValue: float
    cost: float
    todayPnl: float
    totalReturn: float
    topWeight: float


class PortfolioPayload(BaseModel):
    holdings: list[HoldingSnapshot]
    portfolioCurve: list[float]
    portfolioCurveSource: str
    sectorExposure: list[dict[str, Any]]
    metrics: PortfolioMetrics
    riskRadar: list[dict[str, Any]]
    preference: dict[str, str]
    events: list[dict[str, Any]]
    cacheStatus: dict[str, Any]
    sourceMeta: dict[str, Any]
    onboardingRequired: bool
