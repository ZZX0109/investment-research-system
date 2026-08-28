import type {
  TestOfficerAuditRunDetail,
  TestOfficerComparisonReport,
  TestOfficerEvidenceRegistryResource,
  TestOfficerFixtureRegistryResource,
  TestOfficerHistoryIndex,
  TestOfficerJudgeReportResource,
  TestOfficerManifest,
  TestOfficerMissionPackageResource,
  TestOfficerOnboardingProtocolResource,
  TestOfficerOracleRegistryResource,
  TestOfficerRegistryManifest,
  TestOfficerScenarioRegistryResource,
  TestOfficerSelectorMapResource,
} from "./types";

const generatedAt = "2026-08-01T00:00:00.000Z";
const runId = "test-officer-seeded-run";
const missionId = "test-officer-seeded-mission";
const scenarioId = "test-officer-seeded-scenario";
const oracleId = "test-officer-seeded-oracle";

/**
 * The investment workbench has no Test Officer backend. These fixtures keep
 * the optional QA surfaces deterministic in demo mode without pretending that
 * a browser run happened against the research service.
 */
export function getDemoTestOfficerManifest(): TestOfficerManifest {
  return {
    project: { id: "test-officer-seeded-project", name: "Research workbench", status: "demo" },
    targetApp: { id: "test-officer-seeded-app", name: "Investment research workbench", baseUrl: "/", status: "demo" },
    mission: {
      id: missionId,
      name: "Seeded smoke mission",
      objective: "Verify the seeded workbench can be inspected.",
      mode: "scripted",
      status: "ready",
    },
    scenarios: [{ id: scenarioId, name: "Open workbench", goal: "Open the seeded workbench.", tags: ["seeded"], targetPageId: "home" }],
    oracles: [{ id: oracleId, name: "Workbench rendered" }],
    run: {
      id: runId,
      mode: "seeded-demo",
      status: "passed",
      reviewStatus: "pass",
      startedAt: generatedAt,
      finishedAt: generatedAt,
      bundle: {
        rootDir: "artifacts/test-officer/seeded",
        manifestPath: "artifacts/test-officer/seeded/manifest.json",
        artifactsDir: "artifacts/test-officer/seeded/artifacts",
        evidenceDir: "artifacts/test-officer/seeded/evidence",
        reportsDir: "artifacts/test-officer/seeded/reports",
      },
    },
    plan: [],
    steps: [],
    evidence: [],
    artifacts: [],
    findings: [],
    oracleEvaluations: [],
    judgeReport: {
      id: "test-officer-seeded-judge",
      result: "pass",
      narrative: "Seeded demo fixture only; no external browser execution was performed.",
      machineSummary: { decision: "pass", confidence: 1, flaky: false, blocked: false },
    },
  };
}

export function getDemoTestOfficerHistory(): TestOfficerHistoryIndex {
  return {
    schemaVersion: "1.0",
    generatedAt,
    runs: [{
      runId,
      missionId,
      missionName: "Seeded smoke mission",
      targetAppId: "test-officer-seeded-app",
      targetAppName: "Investment research workbench",
      status: "passed",
      reviewStatus: "pass",
      startedAt: generatedAt,
      finishedAt: generatedAt,
      manifestPath: "artifacts/test-officer/seeded/manifest.json",
      findingCount: 0,
      failedStepCount: 0,
      artifactCount: 0,
    }],
  };
}

export function getDemoTestOfficerComparison(): TestOfficerComparisonReport {
  return {
    schemaVersion: "1.0",
    baselineRunId: runId,
    currentRunId: runId,
    missionId,
    summary: {
      statusChanged: false,
      reviewChanged: false,
      findingDelta: 0,
      failedStepDelta: 0,
      artifactDelta: 0,
      artifactSignalDelta: 0,
    },
    stepChanges: [],
    findingChanges: { added: [], resolved: [], unchanged: [] },
    artifactSignalChanges: { added: [], resolved: [], unchanged: [] },
  };
}

export function getDemoTestOfficerRegistryManifest(): TestOfficerRegistryManifest {
  return {
    schemaVersion: "1.0",
    runId,
    missionId,
    generatedAt,
    entries: [],
    counts: { onboardingProtocols: 0, missionPackages: 0, selectorMaps: 0, fixtures: 0, scenarios: 0, oracles: 0, artifacts: 0, evidence: 0, judgeReports: 0 },
  };
}

export function getDemoTestOfficerOnboardingProtocol(): TestOfficerOnboardingProtocolResource {
  return { baseUrl: "/", keyPages: [], businessObjective: "Inspect the seeded workbench.", selectorHints: [], scenarioRequests: [] };
}

export function getDemoTestOfficerMissionPackage(): TestOfficerMissionPackageResource {
  const manifest = getDemoTestOfficerManifest();
  return {
    project: manifest.project,
    targetApp: { ...manifest.targetApp, pages: [] },
    mission: { ...manifest.mission },
    scenarios: manifest.scenarios,
    oracles: manifest.oracles,
    counts: { pages: 0, selectorHints: 0, scenarios: manifest.scenarios.length, oracles: manifest.oracles.length },
  };
}

export function getDemoTestOfficerSelectorMaps(): TestOfficerSelectorMapResource {
  return { id: "test-officer-seeded-selector-map", appId: "test-officer-seeded-app", entries: [] };
}

export function getDemoTestOfficerFixtures(): TestOfficerFixtureRegistryResource[] {
  return [];
}

export function getDemoTestOfficerScenarios(): TestOfficerScenarioRegistryResource[] {
  return [];
}

export function getDemoTestOfficerOracles(): TestOfficerOracleRegistryResource[] {
  return [];
}

export function getDemoTestOfficerEvidenceIndex(): TestOfficerEvidenceRegistryResource[] {
  return [];
}

export function getDemoTestOfficerJudgeReport(): TestOfficerJudgeReportResource {
  return {
    id: "test-officer-seeded-judge",
    runId,
    oracleIds: [oracleId],
    status: "complete",
    result: "pass",
    narrative: "Seeded demo fixture only; no external browser execution was performed.",
    machineSummary: { decision: "pass", confidence: 1, flaky: false, blocked: false },
  };
}

export function getDemoTestOfficerAuditRunDetail(): TestOfficerAuditRunDetail {
  return { runId, sourceContexts: [], failureAttributions: [], artifacts: [], gateResults: [], runtimeLifecycle: [] };
}
