from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field

JsonScalar = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list[JsonScalar] | dict[str, JsonScalar | list[JsonScalar]] | list[dict[str, JsonScalar]]
JsonFlatValue = JsonScalar | list[JsonScalar]


class RunBundleJsonObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    def __getitem__(self, key: str) -> JsonValue:
        value = self.model_dump().get(key)
        if key not in self.model_dump():
            raise KeyError(key)
        return value

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self.model_dump().get(key, default)


class RunBundleAuditSignalSet(RunBundleJsonObject):
    changedFiles: list[str] = Field(default_factory=list)
    consoleErrorArtifacts: list[str] = Field(default_factory=list)
    consoleErrorSummaries: list[str] = Field(default_factory=list)
    networkErrorArtifacts: list[str] = Field(default_factory=list)
    networkErrorSummaries: list[str] = Field(default_factory=list)
    domSnapshotArtifacts: list[str] = Field(default_factory=list)
    retrySignals: dict[str, JsonValue] | None = None
    runtimeSignals: list[dict[str, JsonValue]] = Field(default_factory=list)


class RunBundleAuditArtifactMetadata(RunBundleJsonObject):
    firstError: str | None = None
    firstFailure: str | None = None
    inlinePreview: str | None = None
    provider: str | None = None


class RunBundleAuditGateDiagnostics(RunBundleJsonObject):
    newArtifactSignals: list[str] = Field(default_factory=list)
    newFindings: list[str] = Field(default_factory=list)


class RunBundleSourceContextMetadata(RunBundleJsonObject):
    byteLength: int | None = None
    truncated: bool | None = None
    trust: dict[str, JsonValue] | None = None
    permissionExplanations: list[str] = Field(default_factory=list)
    cache: str | None = None
    retry: str | None = None
    pagination: str | None = None
    rateLimit: str | None = None
    version: str | None = None


class RunBundleManifestArtifactMetadata(RunBundleJsonObject):
    relativePath: str | None = None
    artifactUrl: str | None = None
    previewMode: str | None = None
    inlinePreview: str | None = None
    encryptedAtRest: bool | None = None
    encryptionAlgorithm: str | None = None
    encryptionKeyRef: str | None = None
    encryptionIv: str | None = None
    encryptionAuthTag: str | None = None
    plaintextSha256: str | None = None
    plaintextSizeBytes: int | None = None


class RunBundleManifestEvidenceMetadata(RunBundleJsonObject):
    provider: str | None = None
    captureMode: str | None = None
    artifactUrl: str | None = None


class RunBundleManifestJudgeMetadata(RunBundleJsonObject):
    source: str | None = None
    llmStatus: str | None = None
    policyVersion: str | None = None


class RunBundleHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    runId: str = Field(min_length=1)
    missionId: str | None = None
    missionName: str | None = None
    targetAppId: str | None = None
    targetAppName: str | None = None
    status: str | None = None
    reviewStatus: str | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    manifestPath: str | None = None
    findingCount: int | None = None
    failedStepCount: int | None = None
    artifactCount: int | None = None


class RunBundleHistoryIndex(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    generatedAt: str = ""
    runs: list[RunBundleHistoryEntry] = Field(default_factory=list)


class RunBundleAuditStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    databasePath: str
    schemaVersion: str = "unknown"
    schemaMigrationCount: int = 0
    schemaAppliedAt: str | None = None
    exists: bool
    runs: int
    evidence: int
    artifacts: int
    findings: int
    judgeResults: int
    gateResults: int = 0
    sourceContexts: int = 0
    failureAttributions: int = 0
    runtimeLifecycle: int = 0
    events: int
    journalMode: str


class RunBundleAuditRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str = Field(min_length=1)
    projectId: str = Field(min_length=1)
    missionId: str = Field(min_length=1)
    missionName: str = Field(min_length=1)
    targetAppId: str = Field(min_length=1)
    targetAppName: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reviewStatus: str = Field(min_length=1)
    startedAt: str | None = None
    finishedAt: str | None = None
    bundleUri: str = Field(min_length=1)
    createdAt: str = Field(min_length=1)
    updatedAt: str = Field(min_length=1)


class RunBundleAuditSourceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    readState: str = Field(min_length=1)
    sourceRef: str = Field(min_length=1)
    failureReason: str | None = None
    permissions: list[str] = Field(default_factory=list)
    usageScopes: list[str] = Field(default_factory=list)


class RunBundleAuditFailureAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    findingId: str = Field(min_length=1)
    scenarioId: str = Field(min_length=1)
    stepId: str | None = None
    rank: int
    category: str = Field(min_length=1)
    confidence: float
    likelyCause: str | None = None
    recommendation: str | None = None
    signals: RunBundleAuditSignalSet = Field(default_factory=RunBundleAuditSignalSet)


class RunBundleAuditArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    evidenceId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    artifactUri: str = Field(min_length=1)
    mediaType: str = Field(min_length=1)
    sizeBytes: int
    metadata: RunBundleAuditArtifactMetadata = Field(default_factory=RunBundleAuditArtifactMetadata)


class RunBundleAuditGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    passed: bool
    exitCode: int
    reasons: list[str] = Field(default_factory=list)
    diagnostics: RunBundleAuditGateDiagnostics = Field(default_factory=RunBundleAuditGateDiagnostics)
    generatedAt: str = Field(min_length=1)


class RunBundleAuditRuntimePhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    status: str = Field(min_length=1)
    summary: str | None = None


class RunBundleAuditRunDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str = Field(min_length=1)
    sourceContexts: list[RunBundleAuditSourceContext] = Field(default_factory=list)
    failureAttributions: list[RunBundleAuditFailureAttribution] = Field(default_factory=list)
    artifacts: list[RunBundleAuditArtifact] = Field(default_factory=list)
    gateResults: list[RunBundleAuditGateResult] = Field(default_factory=list)
    runtimeLifecycle: list[RunBundleAuditRuntimePhase] = Field(default_factory=list)


class RunBundleRegistryManifestEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    recordCount: int


class RunBundleRegistryManifestCounts(BaseModel):
    model_config = ConfigDict(extra="allow")

    onboardingProtocols: int = 0
    missionPackages: int = 0
    selectorMaps: int = 0
    fixtures: int = 0
    scenarios: int = 0
    oracles: int = 0
    artifacts: int = 0
    evidence: int = 0
    judgeReports: int = 0
    sourceContexts: int = 0
    failureAttributions: int = 0
    retentionPlans: int = 0


class RunBundleRegistryManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    runId: str = Field(min_length=1)
    missionId: str | None = None
    generatedAt: str = ""
    entries: list[RunBundleRegistryManifestEntry] = Field(default_factory=list)
    counts: RunBundleRegistryManifestCounts = Field(default_factory=RunBundleRegistryManifestCounts)


class RunBundleComparisonSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    statusChanged: bool
    reviewChanged: bool
    findingDelta: int
    failedStepDelta: int
    artifactDelta: int
    artifactSignalDelta: int = 0
    failureAttributionDelta: int = 0
    confidenceDelta: float = 0
    riskScoreDelta: int = 0
    riskTrend: str = "stable"


class RunBundleComparisonJudgeDecisionChange(BaseModel):
    model_config = ConfigDict(extra="allow")

    baselineResult: str | None = None
    currentResult: str | None = None
    baselineDecision: str | None = None
    currentDecision: str | None = None
    baselineConfidence: float | None = None
    currentConfidence: float | None = None
    confidenceDelta: float = 0
    decisionChanged: bool = False
    flakyChanged: bool = False
    blockedChanged: bool = False


class RunBundleComparisonStepChange(BaseModel):
    model_config = ConfigDict(extra="allow")

    stepTitle: str = Field(min_length=1)
    baselineStatus: str = Field(min_length=1)
    currentStatus: str = Field(min_length=1)
    changed: bool


class RunBundleComparisonFindingChanges(BaseModel):
    model_config = ConfigDict(extra="allow")

    added: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class RunBundleComparisonSignalChanges(BaseModel):
    model_config = ConfigDict(extra="allow")

    added: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class RunBundleComparisonFailureAttributionChanges(BaseModel):
    model_config = ConfigDict(extra="allow")

    added: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    topCurrent: list[str] = Field(default_factory=list)


class RunBundleComparisonReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    baselineRunId: str = Field(min_length=1)
    currentRunId: str = Field(min_length=1)
    missionId: str = Field(min_length=1)
    summary: RunBundleComparisonSummary
    judgeDecisionChange: RunBundleComparisonJudgeDecisionChange = Field(default_factory=RunBundleComparisonJudgeDecisionChange)
    stepChanges: list[RunBundleComparisonStepChange] = Field(default_factory=list)
    findingChanges: RunBundleComparisonFindingChanges
    failureAttributionChanges: RunBundleComparisonFailureAttributionChanges = Field(
        default_factory=RunBundleComparisonFailureAttributionChanges
    )
    artifactSignalChanges: RunBundleComparisonSignalChanges = Field(default_factory=RunBundleComparisonSignalChanges)


class RunBundleRegistryResourceRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)


class RunBundleRegistrySourceAdapter(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str | None = None
    permissions: list[str] = Field(default_factory=list)
    usageScopes: list[str] = Field(default_factory=list)
    sourceRef: str | None = None


class RunBundleRegistrySourceContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str | None = None
    adapter: RunBundleRegistrySourceAdapter
    readState: str = Field(min_length=1)
    readAt: str | None = None
    payload: dict[str, JsonFlatValue] = Field(default_factory=dict)
    metadata: RunBundleSourceContextMetadata = Field(default_factory=RunBundleSourceContextMetadata)


class RunBundleRegistryFailureAttribution(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    findingId: str = Field(min_length=1)
    rank: int
    scenarioId: str | None = None
    stepId: str | None = None
    category: str | None = None
    confidence: float | None = None
    likelyCause: str | None = None
    recommendation: str | None = None
    signals: RunBundleAuditSignalSet = Field(default_factory=RunBundleAuditSignalSet)


class RunBundleRetentionCleanupPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    retainRunsDays: int
    retainArtifactsDays: int
    retainReportsDays: int
    retainTraceDays: int
    retainVideoDays: int
    dryRun: bool


class RunBundleRetentionCleanupCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str = Field(min_length=1)
    action: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expiresAt: str | None = None
    protected: bool


class RunBundleRetentionCleanupPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    runId: str = Field(min_length=1)
    generatedAt: str = Field(min_length=1)
    policy: RunBundleRetentionCleanupPolicy
    candidates: list[RunBundleRetentionCleanupCandidate] = Field(default_factory=list)


class RunBundleRetentionJobRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidateId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: str = Field(min_length=1)
    path: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    archivedPath: str | None = None
    originalDeleted: bool = False
    sizeBytes: int | None = None


class RunBundleRetentionJobResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    runId: str = Field(min_length=1)
    generatedAt: str = Field(min_length=1)
    dryRun: bool
    archiveRoot: str | None = None
    reportPath: str | None = None
    summary: dict[str, int] = Field(default_factory=dict)
    records: list[RunBundleRetentionJobRecord] = Field(default_factory=list)


class RunBundleArtifactIntegrityRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifactId: str = Field(min_length=1)
    path: str = Field(min_length=1)
    status: str = Field(min_length=1)
    expectedSha256: str | None = None
    actualSha256: str | None = None
    expectedSizeBytes: int | None = None
    actualSizeBytes: int | None = None
    reason: str | None = None


class RunBundleArtifactIntegrityReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    runId: str = Field(min_length=1)
    generatedAt: str = Field(min_length=1)
    reportPath: str | None = None
    passed: bool
    summary: dict[str, int] = Field(default_factory=dict)
    artifacts: list[RunBundleArtifactIntegrityRecord] = Field(default_factory=list)


class RunBundleDownloadManifestEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str = Field(min_length=1)
    path: str = Field(min_length=1)
    relativePath: str = Field(min_length=1)
    sizeBytes: int | None = None
    included: bool = True
    largeArtifact: bool = False
    largeArtifactStrategy: str | None = None
    reason: str | None = None
    artifactId: str | None = None
    artifactKind: str | None = None


class RunBundleDownloadManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    runId: str = Field(min_length=1)
    generatedAt: str = Field(min_length=1)
    bundlePath: str = Field(min_length=1)
    entryCount: int
    includedCount: int = 0
    referencedOnlyCount: int = 0
    largeArtifactStrategy: str | None = None
    largeArtifactThresholdBytes: int | None = None
    sizeBytes: int
    entries: list[RunBundleDownloadManifestEntry] = Field(default_factory=list)


class RunBundleManifestProject(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    status: str = Field(min_length=1)


class RunBundleManifestTargetApp(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    status: str = Field(min_length=1)


class RunBundleManifestMission(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    status: str = Field(min_length=1)


class RunBundleManifestScenario(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    targetPageId: str = Field(min_length=1)


class RunBundleManifestOracle(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class RunBundleManifestExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    executor: str | None = None
    headless: bool | None = None
    trace: bool | None = None
    recordVideo: bool | None = None


class RunBundleManifestRunMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    executionConfig: RunBundleManifestExecutionConfig | None = None


class RunBundleManifestRegistryResourceUrls(BaseModel):
    model_config = ConfigDict(extra="allow")

    onboardingProtocol: str | None = None
    missionPackage: str | None = None
    selectorMaps: str | None = None
    fixtures: str | None = None
    scenarios: str | None = None
    oracles: str | None = None
    artifacts: str | None = None
    evidence: str | None = None
    judgeReport: str | None = None
    sourceContexts: str | None = None
    failureAttributions: str | None = None
    retentionCleanupPlan: str | None = None


class RunBundleManifestRegistry(BaseModel):
    model_config = ConfigDict(extra="allow")

    rootDir: str = Field(min_length=1)
    resourceManifestPath: str = Field(min_length=1)
    onboardingProtocolPath: str | None = None
    missionPackagePath: str | None = None
    selectorMapsPath: str | None = None
    fixturesPath: str | None = None
    scenariosPath: str = Field(min_length=1)
    oraclesPath: str = Field(min_length=1)
    artifactsPath: str = Field(min_length=1)
    evidencePath: str | None = None
    judgeReportPath: str | None = None
    sourceContextsPath: str | None = None
    failureAttributionsPath: str | None = None
    retentionCleanupPlanPath: str | None = None
    resourceManifestUrl: str | None = None
    resourceUrls: RunBundleManifestRegistryResourceUrls | None = None


class RunBundleManifestReportUrls(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    json_report: str | None = Field(default=None, alias="json", serialization_alias="json")
    junit: str | None = None
    markdown: str | None = None
    html: str | None = None
    comparison: str | None = None
    gate: str | None = None
    prAnnotation: str | None = None
    githubAnnotations: str | None = None
    ciArtifactManifest: str | None = None
    retentionJob: str | None = None
    integrity: str | None = None
    downloadManifest: str | None = None


class RunBundleManifestArtifactAccess(BaseModel):
    model_config = ConfigDict(extra="allow")

    tokenRequired: bool
    header: str = Field(min_length=1)
    runTokenHeader: str | None = None
    runToken: str | None = None
    runTokenScope: str | None = None
    devLoopbackOnly: bool | None = None
    signedUrlTtlSeconds: int | None = None
    runTokenTtlSeconds: int | None = None


class RunBundleManifestTokenPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    agentToken: str = Field(min_length=1)
    artifactToken: str = Field(min_length=1)
    runScopedTokens: bool
    signedUrlTtlSeconds: int


class RunBundleManifestReportAccessPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    html: str = Field(min_length=1)
    json_report: str = Field(alias="json", serialization_alias="json", min_length=1)
    junit: str = Field(min_length=1)
    sensitiveReportsRequireRunScope: bool


class RunBundleManifestCredentialPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    encryptedCredentialStore: bool
    secretRefsOnlyInManifests: bool
    credentialPreviewOnly: bool


class RunBundleManifestRedactionPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    redactArtifacts: bool
    redactReports: bool
    redactSourceContexts: bool
    redactScreenshots: bool


class RunBundleManifestAccessPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile: str = Field(min_length=1)
    tokenPolicy: RunBundleManifestTokenPolicy
    reportAccess: RunBundleManifestReportAccessPolicy
    credentialPolicy: RunBundleManifestCredentialPolicy
    redaction: RunBundleManifestRedactionPolicy


class RunBundleManifestBundle(BaseModel):
    model_config = ConfigDict(extra="allow")

    rootDir: str = Field(min_length=1)
    manifestPath: str = Field(min_length=1)
    artifactsDir: str = Field(min_length=1)
    evidenceDir: str = Field(min_length=1)
    reportsDir: str = Field(min_length=1)
    accessPolicy: RunBundleManifestAccessPolicy | None = None
    registry: RunBundleManifestRegistry | None = None
    manifestUrl: str | None = None
    reportUrls: RunBundleManifestReportUrls | None = None
    artifactAccess: RunBundleManifestArtifactAccess | None = None


class RunBundleManifestRun(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reviewStatus: str = Field(min_length=1)
    startedAt: str | None = None
    finishedAt: str | None = None
    metadata: RunBundleManifestRunMetadata | None = None
    bundle: RunBundleManifestBundle


class RunBundleManifestPlanEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    scenarioId: str = Field(min_length=1)
    stepId: str | None = None
    title: str = Field(min_length=1)
    sequence: int
    intent: str = Field(min_length=1)
    action: str = Field(min_length=1)
    sourceMode: str = Field(min_length=1)
    status: str = Field(min_length=1)
    selectorRef: str | None = None
    inputRef: str | None = None
    expectedOutcome: str | None = None
    evidenceRequirements: list[str] | None = None
    fixtureRefs: list[str] | None = None
    selectorMapId: str | None = None
    rationale: str | None = None
    plannedAt: str = Field(min_length=1)
    updatedAt: str = Field(min_length=1)


class RunBundleManifestStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    scenarioId: str = Field(min_length=1)
    title: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    action: str = Field(min_length=1)
    status: str = Field(min_length=1)
    sequence: int
    selectorRef: str | None = None
    expectedOutcome: str | None = None
    evidenceRequirements: list[str] | None = None
    startedAt: str | None = None
    finishedAt: str | None = None


class RunBundleManifestEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    runId: str | None = None
    stepId: str | None = None
    scenarioId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    artifactIds: list[str] = Field(default_factory=list)
    capturedAt: str = Field(min_length=1)
    metadata: RunBundleManifestEvidenceMetadata | None = None


class RunBundleManifestArtifact(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    evidenceId: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    path: str = Field(min_length=1)
    mediaType: str = Field(min_length=1)
    sizeBytes: int
    metadata: RunBundleManifestArtifactMetadata | None = None


class RunBundleManifestFinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    scenarioId: str = Field(min_length=1)
    category: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    status: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    recommendation: str | None = None
    evidenceIds: list[str] = Field(default_factory=list)


class RunBundleManifestOracleCheckResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    checkId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    requiredEvidence: list[str] = Field(default_factory=list)
    result: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidenceIds: list[str] = Field(default_factory=list)


class RunBundleManifestOracleEvaluation(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    runId: str = Field(min_length=1)
    scenarioId: str = Field(min_length=1)
    oracleId: str = Field(min_length=1)
    result: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidenceIds: list[str] = Field(default_factory=list)
    checkResults: list[RunBundleManifestOracleCheckResult] = Field(default_factory=list)


class RunBundleManifestJudgeMachineSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision: str = Field(min_length=1)
    confidence: float
    flaky: bool
    blocked: bool


class RunBundleManifestJudgeReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    runId: str | None = None
    oracleIds: list[str] = Field(default_factory=list)
    findingIds: list[str] = Field(default_factory=list)
    status: str | None = None
    result: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    metadata: RunBundleManifestJudgeMetadata | None = None
    machineSummary: RunBundleManifestJudgeMachineSummary


class RunBundleManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: RunBundleManifestProject
    targetApp: RunBundleManifestTargetApp
    mission: RunBundleManifestMission
    scenarios: list[RunBundleManifestScenario] = Field(default_factory=list)
    oracles: list[RunBundleManifestOracle] = Field(default_factory=list)
    run: RunBundleManifestRun
    plan: list[RunBundleManifestPlanEntry] = Field(default_factory=list)
    steps: list[RunBundleManifestStep] = Field(default_factory=list)
    evidence: list[RunBundleManifestEvidence] = Field(default_factory=list)
    artifacts: list[RunBundleManifestArtifact] = Field(default_factory=list)
    findings: list[RunBundleManifestFinding] = Field(default_factory=list)
    oracleEvaluations: list[RunBundleManifestOracleEvaluation] = Field(default_factory=list)
    judgeReport: RunBundleManifestJudgeReport | None = None
    sourceContexts: list[RunBundleRegistrySourceContext] = Field(default_factory=list)
    failureAttributions: list[RunBundleRegistryFailureAttribution] = Field(default_factory=list)
    retentionCleanupPlan: RunBundleRetentionCleanupPlan | None = None


class RunBundleOnboardingSelector(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    description: str | None = None
    preferredStrategies: list[str] | None = None
    queries: list[str] = Field(default_factory=list)


class RunBundleOnboardingKeyPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    path: str = Field(min_length=1)
    selectors: list[RunBundleOnboardingSelector] | None = None
    tags: list[str] | None = None


class RunBundleOnboardingSelectorHint(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    pagePath: str | None = None
    pageId: str | None = None
    description: str | None = None
    preferredStrategies: list[str] | None = None
    queries: list[str] = Field(default_factory=list)
    tags: list[str] | None = None


class RunBundleOnboardingAuth(BaseModel):
    model_config = ConfigDict(extra="allow")

    strategy: str = Field(min_length=1)
    accountRef: str | None = None
    loginPagePath: str | None = None
    notes: str | None = None


class RunBundleOnboardingProject(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str | None = None
    name: str | None = None
    description: str | None = None


class RunBundleOnboardingTargetApp(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    environments: list[str] | None = None
    defaultMode: str | None = None


class RunBundleOnboardingScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    family: str = Field(min_length=1)
    id: str | None = None
    name: str | None = None
    goal: str | None = None
    pagePath: str | None = None
    required: bool | None = None
    fixtureRefs: list[str] | None = None
    selectorHintIds: list[str] | None = None
    evidenceRequirements: list[str] | None = None
    failureClasses: list[str] | None = None


class RunBundleOnboardingProtocol(BaseModel):
    model_config = ConfigDict(extra="allow")

    baseUrl: str = Field(min_length=1)
    accountRef: str | None = None
    auth: RunBundleOnboardingAuth | None = None
    project: RunBundleOnboardingProject | None = None
    targetApp: RunBundleOnboardingTargetApp | None = None
    keyPages: list[str | RunBundleOnboardingKeyPage] = Field(default_factory=list)
    businessObjective: str = Field(min_length=1)
    selectorHints: list[str | RunBundleOnboardingSelectorHint] = Field(default_factory=list)
    scenarioRequests: list[RunBundleOnboardingScenarioRequest] = Field(default_factory=list)


class RunBundleMissionPackageTargetSelector(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    preferredStrategies: list[str] | None = None
    queries: list[str] = Field(default_factory=list)


class RunBundleMissionPackageTargetPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    selectors: list[RunBundleMissionPackageTargetSelector] | None = None


class RunBundleMissionPackageTargetAuth(BaseModel):
    model_config = ConfigDict(extra="allow")

    strategy: str = Field(min_length=1)
    credentialRef: str | None = None


class RunBundleMissionPackageTargetApp(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    status: str = Field(min_length=1)
    auth: RunBundleMissionPackageTargetAuth | None = None
    environments: list[str] | None = None
    pages: list[RunBundleMissionPackageTargetPage] | None = None


class RunBundleMissionPackageProject(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status: str = Field(min_length=1)
    description: str | None = None


class RunBundleMissionPackageMission(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    status: str = Field(min_length=1)
    accountRef: str | None = None
    selectorHintRefs: list[str] | None = None


class RunBundleMissionPackageScenario(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    tags: list[str] | None = None
    targetPageId: str | None = None
    fixtureRefs: list[str] | None = None
    evidenceRequirements: list[str] | None = None
    failureClasses: list[str] | None = None


class RunBundleMissionPackageOracleCheck(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    requiredEvidence: list[str] = Field(default_factory=list)


class RunBundleMissionPackageOracle(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    scenarioId: str | None = None
    checks: list[RunBundleMissionPackageOracleCheck] | None = None
    passPolicy: str | None = None


class RunBundleMissionPackageCounts(BaseModel):
    model_config = ConfigDict(extra="allow")

    pages: int
    selectorHints: int
    scenarios: int
    oracles: int


class RunBundleMissionPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: RunBundleMissionPackageProject
    targetApp: RunBundleMissionPackageTargetApp
    mission: RunBundleMissionPackageMission
    scenarios: list[RunBundleMissionPackageScenario] = Field(default_factory=list)
    oracles: list[RunBundleMissionPackageOracle] = Field(default_factory=list)
    counts: RunBundleMissionPackageCounts
