import type {
  TestOfficerFixtureRegistryResource,
  TestOfficerMissionPackageResource,
  TestOfficerOnboardingDraft,
  TestOfficerOnboardingProtocolResource,
  TestOfficerOnboardingPreview,
  TestOfficerOracleRegistryResource,
  TestOfficerScenarioFamily,
  TestOfficerComparisonReport,
  TestOfficerHistoryIndex,
  TestOfficerManifest,
  TestOfficerRegistryManifest,
  TestOfficerScenarioRegistryResource,
  TestOfficerSelectorMapResource
} from "../../api/types";

export function buildTestOfficerSummary(
  manifest: TestOfficerManifest,
  history?: TestOfficerHistoryIndex,
  comparison?: TestOfficerComparisonReport,
  registryManifest?: TestOfficerRegistryManifest,
  onboardingProtocol?: TestOfficerOnboardingProtocolResource,
  missionPackage?: TestOfficerMissionPackageResource
) {
  return {
    stepCount: manifest.steps.length,
    failingSteps: manifest.steps.filter((step) => step.status === "failed" || step.status === "blocked").length,
    findingCount: manifest.findings.length,
    registrySummary: manifest.run.bundle.registry
      ? {
          onboarding: Boolean(manifest.run.bundle.registry.onboardingProtocolPath),
          missionPackage: Boolean(manifest.run.bundle.registry.missionPackagePath),
          selectors: Boolean(manifest.run.bundle.registry.selectorMapsPath),
          fixtures: Boolean(manifest.run.bundle.registry.fixturesPath),
          scenarios: manifest.scenarios.length,
          oracles: manifest.oracles.length,
          artifacts: manifest.artifacts.length,
          sourceContexts: manifest.sourceContexts?.length ?? 0,
          failureAttributions: manifest.failureAttributions?.length ?? 0,
          retentionCandidates: manifest.retentionCleanupPlan?.candidates.length ?? 0,
          onboardingSummary: onboardingProtocol
            ? {
                pageCount: onboardingProtocol.keyPages.length,
                selectorHintCount: onboardingProtocol.selectorHints.length,
                scenarioRequestCount: onboardingProtocol.scenarioRequests.length,
                accountRef:
                  onboardingProtocol.auth?.accountRef ??
                  onboardingProtocol.accountRef ??
                  undefined,
                authStrategy: onboardingProtocol.auth?.strategy ?? "none",
                pagePaths: onboardingProtocol.keyPages.map((page) =>
                  typeof page === "string" ? page : page.path
                ),
                scenarioFamilies: onboardingProtocol.scenarioRequests.map((request) => request.family)
              }
            : undefined,
          missionPackageSummary: missionPackage
            ? {
                pageCount: missionPackage.counts.pages,
                selectorHintCount: missionPackage.counts.selectorHints,
                scenarioCount: missionPackage.counts.scenarios,
                oracleCount: missionPackage.counts.oracles,
                authStrategy: missionPackage.targetApp.auth?.strategy ?? "none",
                accountRef:
                  missionPackage.mission.accountRef ??
                  missionPackage.targetApp.auth?.credentialRef ??
                  undefined,
                scenarioNames: missionPackage.scenarios.map((scenario) => scenario.name)
              }
            : undefined,
          entries: registryManifest?.entries ?? []
        }
      : undefined,
    runtimeSummary: buildRuntimeLifecycleSummary(manifest),
    sourceContextSummary: buildSourceContextSummary(manifest),
    failureAttributionSummary: buildFailureAttributionSummary(manifest),
    retentionSummary: buildRetentionSummary(manifest),
    recentRuns:
      history?.runs.filter((run) => run.missionId === manifest.mission.id).slice(0, 5) ?? [],
    comparisonDelta: comparison
      ? {
          findings: comparison.summary.findingDelta,
          failedSteps: comparison.summary.failedStepDelta,
          artifactSignals: comparison.artifactSignalChanges.added.length - comparison.artifactSignalChanges.resolved.length,
          artifactSignalDelta:
            comparison.summary.artifactSignalDelta ??
            comparison.artifactSignalChanges.added.length - comparison.artifactSignalChanges.resolved.length,
          failureAttributionDelta: comparison.summary.failureAttributionDelta ?? 0,
          riskTrend: comparison.summary.riskTrend ?? "stable",
          riskScoreDelta: comparison.summary.riskScoreDelta ?? 0,
          confidenceDelta: comparison.summary.confidenceDelta ?? 0,
          judgeDecisionChanged: comparison.judgeDecisionChange?.decisionChanged ?? false,
          failureAttributionTopCurrent: comparison.failureAttributionChanges?.topCurrent ?? []
        }
      : undefined
  };
}

export function buildRuntimeLifecycleSummary(manifest: TestOfficerManifest) {
  const phases = manifest.run.metadata?.runtimeLifecycle ?? [];
  const failedPhases = phases.filter((phase) => phase.status === "failed");
  const runningPhases = phases.filter((phase) => phase.status === "running");
  const skippedPhases = phases.filter((phase) => phase.status === "skipped");
  const healthPhase = phases.find((phase) => phase.phase === "health-check");

  return {
    available: phases.length > 0,
    total: phases.length,
    status:
      failedPhases.length > 0
        ? "failed"
        : runningPhases.length > 0
          ? "running"
          : phases.length > 0 && skippedPhases.length === phases.length
            ? "skipped"
            : "passed",
    health:
      healthPhase
        ? `${healthPhase.status}${healthPhase.attempts ? ` · ${healthPhase.attempts} attempts` : ""}`
        : "not recorded",
    phases: phases.map((phase) => ({
      phase: phase.phase,
      status: phase.status,
      summary: phase.summary,
      attempts: phase.attempts,
      error: phase.error,
      tone: toneForRunStatus(phase.status)
    }))
  };
}

export function buildSourceContextSummary(manifest: TestOfficerManifest) {
  const contexts = manifest.sourceContexts ?? [];
  const byState = countBy(contexts, (context) => context.readState);
  const byKind = countBy(contexts, (context) => context.adapter.kind);
  const permissions = Array.from(new Set(contexts.flatMap((context) => context.adapter.permissions))).sort();
  const usageScopes = Array.from(new Set(contexts.flatMap((context) => context.adapter.usageScopes))).sort();
  const entries = contexts.map((context) => ({
    id: context.adapter.id,
    label: context.adapter.label,
    kind: context.adapter.kind,
    readState: context.readState,
    failureReason: context.failureReason,
    sourceRef: context.adapter.sourceRef,
    usageScopes: context.adapter.usageScopes,
    permissions: context.adapter.permissions,
    byteLength: context.metadata.byteLength,
    truncated: context.metadata.truncated,
    trust: context.metadata.trust,
    permissionExplanations: context.metadata.permissionExplanations ?? [],
    cache: context.metadata.cache,
    retry: context.metadata.retry,
    pagination: context.metadata.pagination,
    rateLimit: context.metadata.rateLimit,
    version: context.metadata.version,
    tone: toneForRunStatus(context.readState === "ready" ? "passed" : context.readState)
  }));
  const boundary = buildSourceTrustBoundary(entries);
  const permissionCards = buildSourcePermissionCards(entries);

  return {
    available: contexts.length > 0,
    total: contexts.length,
    ready: byState.get("ready") ?? 0,
    failed: (byState.get("failed") ?? 0) + (byState.get("blocked") ?? 0),
    byKind: Array.from(byKind.entries()).map(([kind, count]) => ({ kind, count })),
    permissions,
    usageScopes,
    boundary,
    permissionCards,
    entries
  };
}

function buildSourceTrustBoundary(
  entries: Array<{
    id: string;
    readState: string;
    permissions: string[];
    usageScopes: string[];
    trust?: { level: string; reasons: string[] };
    failureReason?: string;
  }>
) {
  const credentialed = entries.filter((entry) => entry.permissions.includes("credential-read"));
  const failedOrBlocked = entries.filter((entry) => entry.readState === "failed" || entry.readState === "blocked");
  const lowTrust = entries.filter((entry) =>
    !entry.trust || entry.trust.level === "low-confidence" || entry.trust.level === "unverified"
  );
  const judgeConsumers = entries.filter((entry) => entry.usageScopes.includes("judge"));
  const status =
    entries.length === 0
      ? "missing"
      : entries.some((entry) => entry.readState === "blocked")
        ? "blocked"
        : failedOrBlocked.length > 0 || lowTrust.length > 0
          ? "degraded"
          : credentialed.length > 0
            ? "sensitive"
            : "trusted";
  const warnings = [
    entries.length === 0 ? "No connector source context is attached to this run." : null,
    credentialed.length > 0 ? `${credentialed.length} source(s) required credential access.` : null,
    failedOrBlocked.length > 0 ? `${failedOrBlocked.length} source(s) failed or were blocked before planning/judging.` : null,
    lowTrust.length > 0 ? `${lowTrust.length} source(s) are unverified or low-confidence.` : null,
    judgeConsumers.length > 0 ? `${judgeConsumers.length} source(s) were available to judge decisions.` : null
  ].filter((warning): warning is string => Boolean(warning));

  return {
    status,
    tone: status === "trusted" ? "good" : status === "blocked" || status === "degraded" ? "bad" : "warn",
    summary:
      status === "trusted"
        ? "All connector inputs are ready and trusted or verified."
        : status === "sensitive"
          ? "Connector inputs are ready, but at least one source used credentials."
          : status === "blocked"
            ? "At least one connector input was blocked by the trust boundary."
            : status === "degraded"
              ? "Connector context is partial, failed, or low-confidence."
              : "No connector context was attached.",
    credentialedSources: credentialed.length,
    failedOrBlockedSources: failedOrBlocked.length,
    lowTrustSources: lowTrust.length,
    judgeConsumerSources: judgeConsumers.length,
    warnings
  };
}

function buildSourcePermissionCards(
  entries: Array<{
    id: string;
    label: string;
    permissions: string[];
    permissionExplanations: Array<{ permission: string; reason: string }>;
  }>
) {
  const permissions = Array.from(new Set(entries.flatMap((entry) => entry.permissions))).sort();
  return permissions.map((permission) => {
    const matchingSources = entries.filter((entry) => entry.permissions.includes(permission));
    const reasons = Array.from(new Set(
      matchingSources.flatMap((entry) =>
        entry.permissionExplanations
          .filter((explanation) => explanation.permission === permission)
          .map((explanation) => explanation.reason)
      )
    ));
    return {
      permission,
      count: matchingSources.length,
      sourceLabels: matchingSources.map((entry) => entry.label || entry.id),
      reasons: reasons.length > 0 ? reasons : [fallbackPermissionExplanation(permission)]
    };
  });
}

export function buildFailureAttributionSummary(manifest: TestOfficerManifest) {
  const attributions = [...(manifest.failureAttributions ?? [])].sort((left, right) => left.rank - right.rank);

  return {
    available: attributions.length > 0,
    total: attributions.length,
    topCause: attributions[0]?.likelyCause,
    entries: attributions.map((attribution) => ({
      id: attribution.id,
      rank: attribution.rank,
      findingId: attribution.findingId,
      category: attribution.category,
      confidence: attribution.confidence,
      likelyCause: attribution.likelyCause,
      recommendation: attribution.recommendation,
      signalSummary: [
        attribution.signals.changedFiles.length
          ? `${attribution.signals.changedFiles.length} changed files`
          : null,
        attribution.signals.consoleErrorArtifacts.length
          ? `console: ${attribution.signals.consoleErrorSummaries?.[0] ?? `${attribution.signals.consoleErrorArtifacts.length} artifacts`}`
          : null,
        attribution.signals.networkErrorArtifacts.length
          ? `network: ${attribution.signals.networkErrorSummaries?.[0] ?? `${attribution.signals.networkErrorArtifacts.length} artifacts`}`
          : null,
        attribution.signals.domSnapshotArtifacts.length
          ? `${attribution.signals.domSnapshotArtifacts.length} DOM snapshots`
          : null,
        attribution.signals.retrySignals?.retried
          ? `retried ${attribution.signals.retrySignals.attemptCount ?? "?"}/${attribution.signals.retrySignals.maxAttempts ?? "?"}`
          : null,
        attribution.signals.runtimeSignals?.some((signal) => signal.status === "failed")
          ? "runtime failure signal"
          : null
      ].filter((value): value is string => Boolean(value)),
      changedFiles: attribution.signals.changedFiles.slice(0, 4),
      consoleErrorSummaries: attribution.signals.consoleErrorSummaries ?? [],
      networkErrorSummaries: attribution.signals.networkErrorSummaries ?? [],
      retryTrigger: attribution.signals.retrySignals?.lastRetryTrigger,
      runtimeSignals: attribution.signals.runtimeSignals ?? []
    }))
  };
}

export function buildRetentionSummary(manifest: TestOfficerManifest) {
  const plan = manifest.retentionCleanupPlan;
  const candidates = plan?.candidates ?? [];
  const byAction = countBy(candidates, (candidate) => candidate.action);

  return {
    available: Boolean(plan),
    dryRun: plan?.policy.dryRun ?? true,
    total: candidates.length,
    protected: candidates.filter((candidate) => candidate.protected).length,
    byAction: Array.from(byAction.entries()).map(([action, count]) => ({ action, count })),
    traceVideoCount: candidates.filter((candidate) =>
      candidate.kind === "playwright-trace" || candidate.kind === "video"
    ).length
  };
}

export function buildStepInspection(
  manifest: TestOfficerManifest,
  selectedStepId?: string | null,
  resources?: {
    selectorMaps?: TestOfficerSelectorMapResource[];
    fixtures?: TestOfficerFixtureRegistryResource[];
    scenarios?: TestOfficerScenarioRegistryResource[];
    oracles?: TestOfficerOracleRegistryResource[];
  }
) {
  const scenarioById = new Map(manifest.scenarios.map((scenario) => [scenario.id, scenario]));
  const registryScenarioById = new Map((resources?.scenarios ?? []).map((scenario) => [scenario.id, scenario]));
  const step =
    manifest.steps.find((entry) => entry.id === (selectedStepId ?? manifest.steps[0]?.id)) ??
    manifest.steps[0];

  if (!step) {
    return undefined;
  }

  const scenario = scenarioById.get(step.scenarioId);
  const scenarioContract = registryScenarioById.get(step.scenarioId);
  const planRecord =
    manifest.plan.find((entry) => entry.stepId === step.id) ??
    manifest.plan.find((entry) => entry.scenarioId === step.scenarioId && entry.sequence === step.sequence);
  const evidence = manifest.evidence.filter((entry) => entry.stepId === step.id);
  const evidenceIds = new Set(evidence.map((entry) => entry.id));
  const artifactIds = new Set(evidence.flatMap((entry) => entry.artifactIds));
  const artifacts = manifest.artifacts.filter(
    (artifact) => artifactIds.has(artifact.id) || evidenceIds.has(artifact.evidenceId)
  );
  const findings = manifest.findings.filter((finding) =>
    finding.evidenceIds.some((evidenceId) => evidenceIds.has(evidenceId))
  );
  const oracleEvaluations = manifest.oracleEvaluations.filter((evaluation) =>
    evaluation.scenarioId === step.scenarioId || evaluation.evidenceIds.some((evidenceId) => evidenceIds.has(evidenceId))
  );
  const selectorRef = step.selectorRef ?? planRecord?.selectorRef;
  const selectorContract = findSelectorContract(resources?.selectorMaps ?? [], selectorRef);
  const fixtureContracts = findFixtureContracts(
    resources?.fixtures ?? [],
    planRecord?.fixtureRefs ?? scenarioContract?.fixtureRefs ?? []
  );
  const oracleContracts = (resources?.oracles ?? []).filter(
    (oracle) =>
      oracle.scenarioId === step.scenarioId ||
      oracleEvaluations.some((evaluation) => evaluation.oracleId === oracle.id)
  );

  return {
    step,
    planRecord,
    scenario,
    scenarioContract,
    selectorContract,
    fixtureContracts,
    oracleContracts,
    evidence,
    artifacts,
    findings,
    oracleEvaluations,
    durationLabel: formatDuration(step.startedAt, step.finishedAt),
    reportLinks: buildReportLinks(manifest)
  };
}

export function buildRunTimeline(
  manifest: TestOfficerManifest,
  selection?: {
    stepId?: string | null;
    nodeKey?: string | null;
    checkId?: string | null;
  }
) {
  const selectedId = selection?.stepId ?? manifest.steps[0]?.id ?? null;
  const selectedNodeKey = selection?.nodeKey ?? null;
  const selectedCheckId = selection?.checkId ?? null;
  const evidenceByStepId = new Map<string, TestOfficerManifest["evidence"]>();
  const findingsByScenarioId = new Map<string, TestOfficerManifest["findings"]>();
  const oracleEvaluationsByScenarioId = new Map<string, TestOfficerManifest["oracleEvaluations"]>();

  for (const evidence of manifest.evidence) {
    if (!evidence.stepId) {
      continue;
    }
    evidenceByStepId.set(evidence.stepId, [...(evidenceByStepId.get(evidence.stepId) ?? []), evidence]);
  }

  for (const finding of manifest.findings) {
    findingsByScenarioId.set(finding.scenarioId, [...(findingsByScenarioId.get(finding.scenarioId) ?? []), finding]);
  }

  for (const evaluation of manifest.oracleEvaluations) {
    oracleEvaluationsByScenarioId.set(
      evaluation.scenarioId,
      [...(oracleEvaluationsByScenarioId.get(evaluation.scenarioId) ?? []), evaluation]
    );
  }

  const filteredEvidenceIds = new Set<string>();
  if (selectedNodeKey?.startsWith("oracle:") && selectedCheckId) {
    const evaluationId = selectedNodeKey.replace(/^oracle:/, "");
    const evaluation = manifest.oracleEvaluations.find((entry) => entry.id === evaluationId);
    const check = evaluation?.checkResults.find((entry) => entry.checkId === selectedCheckId);
    for (const evidenceId of check?.evidenceIds ?? []) {
      filteredEvidenceIds.add(evidenceId);
    }
  }

  const planningItems = manifest.plan.map((record) => ({
    id: record.id,
    nodeKey: `planning:${record.id}`,
    phase: "planning" as const,
    title: record.title,
    status: mapPlanStatus(record.status),
    detail: record.rationale ?? record.intent,
    meta: [record.action, record.sourceMode, record.fixtureRefs?.length ? `${record.fixtureRefs.length} fixtures` : null]
      .filter(Boolean)
      .join(" · "),
    relatedStepId: record.stepId,
    selected: selectedNodeKey ? selectedNodeKey === `planning:${record.id}` : record.stepId === selectedId
  }));

  const executionItems = manifest.steps.map((step) => ({
    id: step.id,
    nodeKey: `execution:${step.id}`,
    phase: "execution" as const,
    title: step.title,
    status: step.status,
    detail: step.expectedOutcome ?? step.intent,
    meta: [step.action, step.selectorRef ?? null].filter(Boolean).join(" · "),
    relatedStepId: step.id,
    selected: selectedNodeKey ? selectedNodeKey === `execution:${step.id}` : step.id === selectedId,
    evidenceCount: (evidenceByStepId.get(step.id) ?? []).length,
    emphasis:
      filteredEvidenceIds.size > 0
        ? (evidenceByStepId.get(step.id) ?? []).some((evidence) => filteredEvidenceIds.has(evidence.id))
          ? "highlighted"
          : "dimmed"
        : undefined
  }));

  const evidenceItems = manifest.steps.flatMap((step) =>
    (evidenceByStepId.get(step.id) ?? []).map((evidence) => ({
      id: evidence.id,
      nodeKey: `evidence:${evidence.id}`,
      phase: "evidence" as const,
      title: evidence.kind,
      status: evidence.status === "collected" ? "passed" : "pending",
      detail: evidence.summary,
      meta: [`${evidence.artifactIds.length} artifacts`, step.title].join(" · "),
      relatedStepId: step.id,
      selected: selectedNodeKey ? selectedNodeKey === `evidence:${evidence.id}` : step.id === selectedId,
      emphasis:
        filteredEvidenceIds.size > 0
          ? filteredEvidenceIds.has(evidence.id)
            ? "highlighted"
            : "dimmed"
          : undefined
    }))
  );

  const verdictItems = manifest.scenarios.flatMap((scenario) => {
    const evaluations = oracleEvaluationsByScenarioId.get(scenario.id) ?? [];
    const findings = findingsByScenarioId.get(scenario.id) ?? [];
    return [
      ...evaluations.map((evaluation) => ({
        id: evaluation.id,
        nodeKey: `oracle:${evaluation.id}`,
        phase: "oracle" as const,
        title: evaluation.oracleId,
        status: normalizeVerdictStatus(evaluation.result),
        detail: evaluation.summary,
        meta: `${evaluation.checkResults.length} checks · ${scenario.name}`,
        relatedStepId: manifest.steps.find((step) => step.scenarioId === scenario.id)?.id,
        selected: selectedNodeKey
          ? selectedNodeKey === `oracle:${evaluation.id}`
          : manifest.steps.some((step) => step.scenarioId === scenario.id && step.id === selectedId),
        emphasis:
          selectedNodeKey?.startsWith("oracle:") && selectedCheckId
            ? selectedNodeKey === `oracle:${evaluation.id}` ? "highlighted" : "dimmed"
            : undefined
      })),
      ...findings.map((finding) => ({
        id: finding.id,
        nodeKey: `finding:${finding.id}`,
        phase: "finding" as const,
        title: finding.title,
        status: finding.status === "resolved" ? "passed" : "failed",
        detail: finding.summary,
        meta: `${finding.category} · ${finding.severity}`,
        relatedStepId: manifest.steps.find((step) => step.scenarioId === scenario.id)?.id,
        selected: selectedNodeKey
          ? selectedNodeKey === `finding:${finding.id}`
          : manifest.steps.some((step) => step.scenarioId === scenario.id && step.id === selectedId),
        emphasis:
          filteredEvidenceIds.size > 0
            ? finding.evidenceIds?.some?.((id: string) => filteredEvidenceIds.has(id))
              ? "highlighted"
              : "dimmed"
            : undefined
      }))
    ];
  });

  return {
    sections: [
      { id: "planning", label: "Planning", items: planningItems },
      { id: "execution", label: "Execution", items: executionItems },
      { id: "evidence", label: "Evidence", items: evidenceItems },
      { id: "verdict", label: "Oracle & Judge", items: verdictItems }
    ].filter((section) => section.items.length > 0)
  };
}

export function buildTimelineSelectionDetail(
  manifest: TestOfficerManifest,
  timeline: ReturnType<typeof buildRunTimeline> | undefined,
  selectedNodeKey: string | null,
  inspection: ReturnType<typeof buildStepInspection>,
  selectedCheckId?: string | null
) {
  if (!selectedNodeKey) {
    return undefined;
  }

  const selectedItem = timeline?.sections
    .flatMap((section) => section.items)
    .find((item) => item.selected);

  if (!selectedItem) {
    return undefined;
  }

  if (selectedItem.phase === "planning") {
    return {
      title: selectedItem.title,
      phase: "Planning",
      status: selectedItem.status,
      summary: inspection?.planRecord?.rationale ?? inspection?.planRecord?.intent ?? selectedItem.detail,
      details: [
        { label: "Action", value: inspection?.planRecord?.action ?? "n/a" },
        { label: "Source Mode", value: inspection?.planRecord?.sourceMode ?? "n/a" },
        { label: "Fixture Refs", value: inspection?.planRecord?.fixtureRefs?.join(" · ") ?? "n/a", mono: true },
        { label: "Assertions", value: formatAssertionContracts(inspection?.planRecord?.assertions) },
        { label: "Failure Criteria", value: formatFailureCriteria(inspection?.planRecord?.failureCriteria) },
        { label: "Retry Policy", value: formatRetryPolicy(inspection?.planRecord?.retryPolicy), mono: true }
      ],
      artifacts: [],
      checkResults: [],
      linkedEvidence: []
    };
  }

  if (selectedItem.phase === "execution") {
    return {
      title: selectedItem.title,
      phase: "Execution",
      status: selectedItem.status,
      summary: inspection?.step.expectedOutcome ?? inspection?.step.intent ?? selectedItem.detail,
      details: [
        { label: "Action", value: inspection?.step.action ?? "n/a" },
        { label: "Selector", value: inspection?.step.selectorRef ?? "n/a", mono: true },
        { label: "Evidence", value: inspection?.step.evidenceRequirements?.join(" · ") ?? "n/a" },
        { label: "Assertions", value: formatAssertionContracts(inspection?.step.assertions) },
        { label: "Failure Criteria", value: formatFailureCriteria(inspection?.step.failureCriteria) },
        { label: "Retry Policy", value: formatRetryPolicy(inspection?.step.retryPolicy), mono: true }
      ],
      artifacts: [],
      checkResults: [],
      linkedEvidence: []
    };
  }

  if (selectedItem.phase === "evidence") {
    const evidence = manifest.evidence.find((entry) => `evidence:${entry.id}` === selectedNodeKey)
      ?? inspection?.evidence.find((entry) => `evidence:${entry.id}` === selectedItem.nodeKey);
    const artifacts = manifest.artifacts.filter((artifact) => evidence?.artifactIds.includes(artifact.id));
    return {
      title: evidence?.kind ?? selectedItem.title,
      phase: "Evidence",
      status: selectedItem.status,
      summary: evidence?.summary ?? selectedItem.detail,
      details: [
        { label: "Evidence ID", value: evidence?.id ?? "n/a", mono: true },
        { label: "Artifacts", value: artifacts.map((artifact) => artifact.kind).join(" · ") || "n/a" },
        { label: "Captured", value: evidence?.capturedAt ?? "n/a", mono: true }
      ],
      artifacts,
      checkResults: [],
      linkedEvidence: evidence ? [evidence] : []
    };
  }

  if (selectedItem.phase === "oracle") {
    const evaluation = manifest.oracleEvaluations.find((entry) => `oracle:${entry.id}` === selectedNodeKey)
      ?? inspection?.oracleEvaluations.find((entry) => `oracle:${entry.id}` === selectedItem.nodeKey);
    const contract = inspection?.oracleContracts.find((entry) => entry.id === evaluation?.oracleId);
    const activeCheckResults = selectedCheckId
      ? (evaluation?.checkResults ?? []).filter((check) => check.checkId === selectedCheckId)
      : (evaluation?.checkResults ?? []);
    const activeEvidenceIds = activeCheckResults.flatMap((check) => check.evidenceIds);
    return {
      title: contract?.name ?? evaluation?.oracleId ?? selectedItem.title,
      phase: "Oracle",
      status: selectedItem.status,
      summary: evaluation?.summary ?? selectedItem.detail,
      details: [
        { label: "Policy", value: contract?.passPolicy ?? "n/a" },
        { label: "Checks", value: contract?.checks.map((check) => check.name).join(" · ") || "n/a" },
        { label: "Result", value: evaluation?.result ?? "n/a" },
        { label: "Focused Check", value: selectedCheckId ?? "all" }
      ],
      artifacts: [],
      checkResults: activeCheckResults,
      linkedEvidence: manifest.evidence.filter((entry) =>
        (selectedCheckId ? activeEvidenceIds : evaluation?.evidenceIds ?? []).includes(entry.id)
      )
    };
  }

  const finding = manifest.findings.find((entry) => `finding:${entry.id}` === selectedNodeKey)
    ?? inspection?.findings.find((entry) => `finding:${entry.id}` === selectedItem.nodeKey);
  return {
    title: finding?.title ?? selectedItem.title,
    phase: "Finding",
    status: selectedItem.status,
    summary: finding?.summary ?? selectedItem.detail,
    details: [
      { label: "Category", value: finding?.category ?? "n/a" },
      { label: "Severity", value: finding?.severity ?? "n/a" },
      { label: "Evidence IDs", value: finding?.evidenceIds.join(" · ") ?? "n/a", mono: true }
    ],
    artifacts: manifest.artifacts.filter((artifact) =>
      manifest.evidence.some((evidence) =>
        finding?.evidenceIds.includes(evidence.id) && evidence.artifactIds.includes(artifact.id)
      )
    ),
    checkResults: [],
    linkedEvidence: manifest.evidence.filter((entry) => finding?.evidenceIds.includes(entry.id))
  };
}

export function prioritizeArtifacts<T extends { id: string }>(
  artifacts: T[],
  selectedArtifactId?: string | null
) {
  if (!selectedArtifactId) {
    return artifacts;
  }

  return [...artifacts].sort((left, right) => {
    if (left.id === selectedArtifactId) {
      return -1;
    }
    if (right.id === selectedArtifactId) {
      return 1;
    }
    return 0;
  });
}

export function buildTimelineDebugContext(input: {
  selectedNodeKey?: string | null;
  selectedCheckId?: string | null;
  selectedArtifactId?: string | null;
}) {
  const tokens: Array<{
    id: string;
    label: string;
    value: string;
  }> = [];

  if (input.selectedNodeKey) {
    const [phase, rawId] = input.selectedNodeKey.split(":");
    tokens.push({
      id: "node",
      label: "node",
      value: `${phase} · ${rawId}`
    });
  }

  if (input.selectedCheckId) {
    tokens.push({
      id: "check",
      label: "check",
      value: input.selectedCheckId
    });
  }

  if (input.selectedArtifactId) {
    tokens.push({
      id: "artifact",
      label: "artifact",
      value: input.selectedArtifactId
    });
  }

  return {
    active: tokens.length > 0,
    tokens
  };
}

export function clearTimelineDebugSelection(
  selection: {
    selectedNodeKey?: string | null;
    selectedCheckId?: string | null;
    selectedArtifactId?: string | null;
  },
  tokenId: "node" | "check" | "artifact" | "all"
) {
  if (tokenId === "all") {
    return {
      selectedNodeKey: null,
      selectedCheckId: null,
      selectedArtifactId: null
    };
  }

  if (tokenId === "node") {
    return {
      ...selection,
      selectedNodeKey: null,
      selectedCheckId: null
    };
  }

  if (tokenId === "check") {
    return {
      ...selection,
      selectedCheckId: null
    };
  }

  return {
    ...selection,
    selectedArtifactId: null
  };
}

export function resolveArtifactPresentation(
  artifact: TestOfficerManifest["artifacts"][number]
) {
  const previewMode = artifact.metadata?.previewMode ?? "download";
  const artifactUrl = artifact.metadata?.artifactUrl;
  const inlinePreview = artifact.metadata?.inlinePreview;

  if (previewMode === "image") {
    return {
      previewMode,
      imageSrc: artifactUrl ?? inlinePreview,
      textPreview: undefined,
      downloadUrl: artifactUrl
    };
  }

  if (previewMode === "text" || previewMode === "json" || previewMode === "html") {
    return {
      previewMode,
      imageSrc: undefined,
      textPreview: inlinePreview,
      downloadUrl: artifactUrl
    };
  }

  return {
    previewMode,
    imageSrc: undefined,
    textPreview: undefined,
    downloadUrl: artifactUrl
  };
}

export function toneForRunStatus(value: string) {
  if (value === "pass" || value === "passed") {
    return "good";
  }
  if (value === "fail" || value === "failed") {
    return "bad";
  }
  if (value === "blocked" || value === "flaky") {
    return "warn";
  }
  return "neutral";
}

export function createDefaultOnboardingDraft(
  manifest?: TestOfficerManifest
): TestOfficerOnboardingDraft {
  const scenarioPageByFamily = new Map<TestOfficerScenarioFamily, string>();

  if (manifest) {
    for (const scenario of manifest.scenarios) {
      const family = inferScenarioFamilyFromScenario(scenario);
      if (!scenarioPageByFamily.has(family)) {
        scenarioPageByFamily.set(family, derivePagePathFromScenario(manifest, scenario));
      }
    }
  }

  const targetAppName = manifest?.targetApp.name ?? "New target app";
  const baseUrl = manifest?.targetApp.baseUrl ?? "https://app.example.test";
  const objective =
    manifest?.mission.objective ??
    "Verify a real user can authenticate, complete the target workflow, and observe a stable business state change.";

  return {
    projectName: manifest?.project.name ?? "New QA Project",
    targetAppName,
    baseUrl,
    accountRef: "",
    authStrategy: manifest?.targetApp.auth?.strategy ?? "session",
    loginPagePath:
      typeof manifest?.targetApp.metadata?.loginPagePath === "string"
        ? manifest.targetApp.metadata.loginPagePath
        : undefined,
    environments: manifest?.targetApp.environments ?? ["default"],
    runtime: manifest?.targetApp.runtime ?? undefined,
    workspaceRoot: "",
    prUrl: "",
    requirementDocs: [],
    bugTickets: [],
    apiDocs: [],
    gitDiffs: [],
    githubIssues: [],
    jiraIssues: [],
    openApiUrls: [],
    requirementText: "",
    businessObjective: objective,
    mode: isKnownMode(manifest?.mission.mode) ? manifest!.mission.mode : "plan-assisted",
    keyPages: uniqueNonEmpty([
      scenarioPageByFamily.get("auth-login") ?? "/login",
      scenarioPageByFamily.get("golden-path") ?? "/tasks",
      scenarioPageByFamily.get("form-submission") ?? "/orders/create-form",
      scenarioPageByFamily.get("list-state-change") ?? "/orders"
    ]),
    selectorHints: [
      "data-testid=login-submit",
      "data-testid=order-submit",
      "data-testid=ship-order-ord-1001",
      "data-testid=task-filter-completed"
    ],
    scenarioRequests: [
      {
        family: "auth-login",
        pagePath: scenarioPageByFamily.get("auth-login") ?? "/login",
        enabled: true
      },
      {
        family: "golden-path",
        pagePath: scenarioPageByFamily.get("golden-path") ?? "/tasks",
        enabled: true
      },
      {
        family: "form-submission",
        pagePath: scenarioPageByFamily.get("form-submission") ?? "/orders/create-form",
        enabled: true
      },
      {
        family: "list-state-change",
        pagePath: scenarioPageByFamily.get("list-state-change") ?? "/orders",
        enabled: true
      }
    ]
  };
}

export function sanitizeOnboardingDraftForRequest(
  draft: TestOfficerOnboardingDraft
): TestOfficerOnboardingDraft {
  const runtime = draft.runtime
    ? {
        ...draft.runtime,
        start: draft.runtime.start?.command?.trim()
          ? {
              ...draft.runtime.start,
              command: draft.runtime.start.command.trim(),
              args: draft.runtime.start.args ?? []
            }
          : undefined,
        healthCheck: draft.runtime.healthCheck?.url?.trim()
          ? {
              ...draft.runtime.healthCheck,
              url: draft.runtime.healthCheck.url.trim(),
              expectedStatus: draft.runtime.healthCheck.expectedStatus?.length
                ? draft.runtime.healthCheck.expectedStatus
                : [200]
            }
          : undefined,
        cleanup: draft.runtime.cleanup?.command?.trim()
          ? {
              ...draft.runtime.cleanup,
              command: draft.runtime.cleanup.command.trim(),
              args: draft.runtime.cleanup.args ?? []
            }
          : undefined,
        routes: draft.runtime.routes ?? [],
        testAccounts: draft.runtime.testAccounts ?? [],
        env: draft.runtime.env ?? []
      }
    : undefined;
  const hasRuntime =
    Boolean(runtime?.start) ||
    Boolean(runtime?.healthCheck) ||
    Boolean(runtime?.cleanup) ||
    Boolean(runtime?.routes?.length) ||
    Boolean(runtime?.testAccounts?.length) ||
    Boolean(runtime?.env?.length);

  return {
    ...draft,
    accountRef: draft.accountRef.trim(),
    loginPagePath: draft.loginPagePath?.trim() || undefined,
    authNotes: draft.authNotes?.trim() || undefined,
    environments: (draft.environments ?? []).map((environment) => environment.trim()).filter(Boolean),
    workspaceRoot: draft.workspaceRoot?.trim() || undefined,
    prUrl: draft.prUrl?.trim() || undefined,
    requirementDocs: (draft.requirementDocs ?? []).map((entry) => entry.trim()).filter(Boolean),
    bugTickets: (draft.bugTickets ?? []).map((entry) => entry.trim()).filter(Boolean),
    apiDocs: (draft.apiDocs ?? []).map((entry) => entry.trim()).filter(Boolean),
    gitDiffs: (draft.gitDiffs ?? []).map((entry) => entry.trim()).filter(Boolean),
    githubIssues: (draft.githubIssues ?? []).map((entry) => entry.trim()).filter(Boolean),
    jiraIssues: (draft.jiraIssues ?? []).map((entry) => entry.trim()).filter(Boolean),
    openApiUrls: (draft.openApiUrls ?? []).map((entry) => entry.trim()).filter(Boolean),
    requirementText: draft.requirementText?.trim() || undefined,
    keyPages: draft.keyPages.map((page) => page.trim()).filter(Boolean),
    selectorHints: draft.selectorHints.map((hint) => hint.trim()).filter(Boolean),
    runtime: hasRuntime ? runtime : undefined
  };
}

export function buildOnboardingPreview(
  draft: TestOfficerOnboardingDraft
): TestOfficerOnboardingPreview {
  const keyPages = uniqueNonEmpty(draft.keyPages);
  const selectorHints = uniqueNonEmpty(draft.selectorHints);
  const enabledScenarios = draft.scenarioRequests.filter((scenario) => scenario.enabled);
  const requiredMissing: string[] = [];

  if (!draft.projectName.trim()) {
    requiredMissing.push("project name");
  }
  if (!draft.targetAppName.trim()) {
    requiredMissing.push("target app name");
  }
  if (!draft.baseUrl.trim()) {
    requiredMissing.push("base URL");
  }
  if (!draft.businessObjective.trim()) {
    requiredMissing.push("business objective");
  }
  if (keyPages.length === 0) {
    requiredMissing.push("key pages");
  }
  if (enabledScenarios.length === 0) {
    requiredMissing.push("enabled scenarios");
  }

  const scenarios = draft.scenarioRequests.map((scenario) => ({
    family: scenario.family,
    pagePath: scenario.pagePath.trim(),
    enabled: scenario.enabled,
    label: labelForScenarioFamily(scenario.family),
    goal: goalForScenarioFamily(scenario.family)
  }));

  return {
    missionName: `${draft.targetAppName.trim() || "Target"} mission`,
    readiness: requiredMissing.length === 0 ? "ready" : "partial",
    requiredMissing,
    selectorCoverage: enabledScenarios.length === 0
      ? 0
      : Math.min(100, Math.round((selectorHints.length / enabledScenarios.length) * 100)),
    enabledScenarioCount: enabledScenarios.length,
    pageCount: keyPages.length,
    scenarios
  };
}

export type TestOfficerSummary = ReturnType<typeof buildTestOfficerSummary>;
export type TestOfficerStepInspection = NonNullable<ReturnType<typeof buildStepInspection>>;
export type TestOfficerRunTimeline = ReturnType<typeof buildRunTimeline>;
export type TestOfficerTimelineSelectionDetail = ReturnType<typeof buildTimelineSelectionDetail>;
export type TestOfficerTimelineDebugContext = ReturnType<typeof buildTimelineDebugContext>;

function formatDuration(startedAt?: string, finishedAt?: string) {
  if (!startedAt || !finishedAt) {
    return "n/a";
  }

  const durationMs = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(durationMs) || durationMs < 0) {
    return "n/a";
  }

  if (durationMs < 1000) {
    return `${durationMs} ms`;
  }

  return `${(durationMs / 1000).toFixed(1)} s`;
}

function buildReportLinks(manifest: TestOfficerManifest) {
  const reportUrls = manifest.run.bundle.reportUrls;
  if (!reportUrls) {
    return [];
  }

  return [
    { label: "json", href: reportUrls.json },
    { label: "junit", href: reportUrls.junit },
    { label: "markdown", href: reportUrls.markdown },
    { label: "html", href: reportUrls.html },
    { label: "comparison", href: reportUrls.comparison },
    { label: "gate", href: reportUrls.gate },
    { label: "pr annotation", href: reportUrls.prAnnotation },
    { label: "github annotations", href: reportUrls.githubAnnotations },
    { label: "ci artifacts", href: reportUrls.ciArtifactManifest },
    { label: "retention job", href: reportUrls.retentionJob },
    { label: "integrity", href: reportUrls.integrity },
    { label: "download manifest", href: reportUrls.downloadManifest }
  ].filter((entry): entry is { label: string; href: string } => Boolean(entry.href));
}

function countBy<T>(items: T[], selectKey: (item: T) => string) {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = selectKey(item);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

function formatAssertionContracts(
  assertions: TestOfficerManifest["plan"][number]["assertions"] | undefined
) {
  if (!assertions?.length) {
    return "n/a";
  }
  return assertions
    .map((assertion) => `${assertion.kind}:${assertion.target} => ${assertion.expected}`)
    .join(" · ");
}

function formatFailureCriteria(
  criteria: TestOfficerManifest["plan"][number]["failureCriteria"] | undefined
) {
  if (!criteria?.length) {
    return "n/a";
  }
  return criteria
    .map((criterion) => `${criterion.category}/${criterion.severity}: ${criterion.condition}`)
    .join(" · ");
}

function formatRetryPolicy(
  retryPolicy: TestOfficerManifest["plan"][number]["retryPolicy"] | undefined
) {
  if (!retryPolicy) {
    return "n/a";
  }
  return `${retryPolicy.maxAttempts} attempts · ${retryPolicy.retryOn.join(", ") || "no retry"} · ${retryPolicy.backoffMs}ms`;
}

function inferScenarioFamilyFromScenario(
  scenario: TestOfficerManifest["scenarios"][number]
): TestOfficerScenarioFamily {
  const tags = scenario.tags.join(" ").toLowerCase();
  const identity = `${scenario.id} ${scenario.name} ${scenario.goal} ${tags}`.toLowerCase();

  if (identity.includes("login") || identity.includes("auth")) {
    return "auth-login";
  }
  if (identity.includes("form") || identity.includes("submit")) {
    return "form-submission";
  }
  if (identity.includes("list") || identity.includes("state")) {
    return "list-state-change";
  }
  return "golden-path";
}

function derivePagePathFromScenario(
  manifest: TestOfficerManifest,
  scenario: TestOfficerManifest["scenarios"][number]
) {
  const identity = `${scenario.id} ${scenario.name} ${scenario.goal}`.toLowerCase();
  if (identity.includes("login") || identity.includes("auth")) {
    return "/login";
  }
  if (identity.includes("form") || identity.includes("submit")) {
    return "/orders/create-form";
  }
  if (identity.includes("list") || identity.includes("state")) {
    return "/orders";
  }
  return manifest.targetApp.baseUrl.includes("/tasks") ? "/tasks" : "/tasks";
}

function labelForScenarioFamily(family: TestOfficerScenarioFamily) {
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

function goalForScenarioFamily(family: TestOfficerScenarioFamily) {
  if (family === "auth-login") {
    return "Verify a valid account can authenticate and reach the protected workspace.";
  }
  if (family === "form-submission") {
    return "Verify a representative business form can be completed and submitted.";
  }
  if (family === "list-state-change") {
    return "Verify a complex list or business object reflects a visible state change.";
  }
  return "Verify the primary user path stays reachable and stable.";
}

function uniqueNonEmpty(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function fallbackPermissionExplanation(permission: string) {
  if (permission === "workspace-read") {
    return "Reads local workspace files inside the configured project boundary.";
  }
  if (permission === "network-read") {
    return "Fetches remote source context through a connector URL safety boundary.";
  }
  if (permission === "credential-read") {
    return "Uses an explicit connector credential or token for private source context.";
  }
  return "Uses a connector permission declared by the source context adapter.";
}

function isKnownMode(value: string | undefined): value is TestOfficerOnboardingDraft["mode"] {
  return value === "scripted" || value === "plan-assisted" || value === "ai-exploratory";
}

function mapPlanStatus(status: string) {
  if (status === "completed") {
    return "passed";
  }
  if (status === "failed" || status === "blocked") {
    return status;
  }
  if (status === "running") {
    return "running";
  }
  return "pending";
}

function normalizeVerdictStatus(status: string) {
  if (status === "pass") {
    return "passed";
  }
  if (status === "fail") {
    return "failed";
  }
  return status;
}

function findSelectorContract(
  selectorMaps: TestOfficerSelectorMapResource[],
  selectorRef?: string
) {
  if (!selectorRef) {
    return undefined;
  }

  for (const selectorMap of selectorMaps) {
    const entry = selectorMap.entries.find((candidate) => candidate.id === selectorRef);
    if (entry) {
      return {
        mapId: selectorMap.id,
        ...entry
      };
    }
  }

  return undefined;
}

function findFixtureContracts(
  fixtures: TestOfficerFixtureRegistryResource[],
  fixtureRefs: string[]
) {
  return fixtureRefs.map((fixtureRef) =>
    fixtures.find((fixture) =>
      fixture.id === fixtureRef ||
      fixture.manifestRef === fixtureRef ||
      fixtureRef.endsWith(fixture.id)
    )
  ).filter((fixture): fixture is TestOfficerFixtureRegistryResource => Boolean(fixture));
}
