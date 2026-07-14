import type {
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
  TestOfficerSelectorMapResource
} from "../types";

import { now } from "./shared";

export function getDemoTestOfficerManifest(): TestOfficerManifest {
  return {
    project: {
      id: "project_hack-ai-test-officer",
      name: "Hack AI Test Officer",
      description: "AI testing platform contract and run bundle demo.",
      status: "active"
    },
    targetApp: {
      id: "targetapp_todo-demo",
      name: "Todo Demo",
      baseUrl: "https://example.test/todos",
      status: "reachable"
    },
    mission: {
      id: "mission_task-filter-completed",
      name: "Golden completed-filter mission",
      objective: "Validate the completed-task filtering flow for regression and demo use.",
      mode: "scripted",
      status: "ready"
    },
    scenarios: [
      {
        id: "scenario_task-filter-completed",
        name: "Completed task filter works",
        goal: "Verify completed tasks can be filtered and displayed correctly.",
        tags: ["golden", "list-state"],
        targetPageId: "tasks"
      }
    ],
    oracles: [
      {
        id: "oracle_task-filter-completed",
        name: "Completed filter oracle"
      }
    ],
    run: {
      id: "run_mission-task-filter-completed-2026-07-03-10-00-00",
      mode: "scripted",
      status: "failed",
      reviewStatus: "fail",
      startedAt: now,
      finishedAt: "2026-07-03T10:00:41.000Z",
      bundle: {
        rootDir: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00",
        manifestPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/manifest.json",
        artifactsDir: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/artifacts",
        evidenceDir: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/evidence",
        reportsDir: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports",
        registry: {
          rootDir: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry",
          resourceManifestPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/resources.json",
          onboardingProtocolPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/onboarding.json",
          missionPackagePath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/mission-package.json",
          selectorMapsPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/selector-maps.json",
          fixturesPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/fixtures.json",
          scenariosPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/scenarios.json",
          oraclesPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/oracles.json",
          artifactsPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/artifacts.json",
          evidencePath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/evidence.json",
          judgeReportPath: "/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/judge-report.json",
          resourceManifestUrl: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry",
          resourceUrls: {
            onboardingProtocol: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/onboarding",
            missionPackage: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/mission-package",
            selectorMaps: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/selector-maps",
            fixtures: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/fixtures",
            scenarios: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/scenarios",
            oracles: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/oracles",
            artifacts: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/artifacts",
            evidence: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/evidence",
            judgeReport: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/registry/judge-report"
          }
        },
        reportUrls: {
          json: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/run-report.json",
          junit: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/junit.xml",
          markdown: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/report.md",
          html: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/report.html",
          comparison: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/comparison.json",
          gate: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/gate.json",
          prAnnotation: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/pr-annotation.md",
          githubAnnotations: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/pr-annotations.json",
          ciArtifactManifest: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/artifact-upload-manifest.json",
          retentionJob: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/retention-job.json",
          integrity: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/integrity-report.json",
          downloadManifest: "/api/v1/test-officer/runs/run_mission-task-filter-completed-2026-07-03-10-00-00/reports/download-manifest.json"
        }
      }
    },
    plan: [
      {
        id: "plan_step-open-home",
        scenarioId: "scenario_task-filter-completed",
        stepId: "step_open-home",
        title: "Open task list",
        sequence: 0,
        intent: "Load the target page before switching filter state.",
        action: "navigate",
        expectedOutcome: "Task list is visible",
        evidenceRequirements: ["screenshot", "dom-snapshot"],
        fixtureRefs: ["fixture://tasks/completed-seed"],
        selectorMapId: "selectors.todo-demo",
        sourceMode: "scripted",
        status: "completed",
        rationale: "Open the seeded task page before validating the completed-filter state transition.",
        plannedAt: now,
        updatedAt: "2026-07-03T10:00:08.000Z"
      },
      {
        id: "plan_step-switch-filter",
        scenarioId: "scenario_task-filter-completed",
        stepId: "step_switch-filter",
        title: "Switch to completed filter",
        sequence: 1,
        intent: "Select the completed filter tab and confirm the list changes.",
        action: "click",
        selectorRef: "task-filter-completed-tab",
        expectedOutcome: "Completed tasks are visible",
        evidenceRequirements: ["screenshot", "dom-snapshot", "console-log", "network-log"],
        fixtureRefs: ["fixture://tasks/completed-seed"],
        selectorMapId: "selectors.todo-demo",
        sourceMode: "scripted",
        status: "failed",
        rationale: "This is the golden regression checkpoint for the completed-filter business state.",
        plannedAt: "2026-07-03T10:00:08.000Z",
        updatedAt: "2026-07-03T10:00:41.000Z"
      }
    ],
    steps: [
      {
        id: "step_open-home",
        scenarioId: "scenario_task-filter-completed",
        title: "Open task list",
        intent: "Load the target page before switching filter state.",
        action: "navigate",
        status: "passed",
        sequence: 0,
        expectedOutcome: "Task list is visible",
        evidenceRequirements: ["screenshot", "dom-snapshot"],
        startedAt: now,
        finishedAt: "2026-07-03T10:00:08.000Z"
      },
      {
        id: "step_switch-filter",
        scenarioId: "scenario_task-filter-completed",
        title: "Switch to completed filter",
        intent: "Select the completed filter tab and confirm the list changes.",
        action: "click",
        status: "failed",
        sequence: 1,
        selectorRef: "task-filter-completed-tab",
        expectedOutcome: "Completed tasks are visible",
        evidenceRequirements: ["screenshot", "dom-snapshot", "console-log", "network-log"],
        startedAt: "2026-07-03T10:00:08.000Z",
        finishedAt: "2026-07-03T10:00:41.000Z"
      }
    ],
    evidence: [
      {
        id: "evidence_completed-filter-failed",
        runId: "run_mission-task-filter-completed-2026-07-03-10-00-00",
        stepId: "step_switch-filter",
        scenarioId: "scenario_task-filter-completed",
        kind: "assertion-output",
        status: "indexed",
        summary: "Completed tab was clicked, but no completed rows appeared.",
        artifactIds: ["artifact_failed-screenshot", "artifact_failed-console"],
        capturedAt: "2026-07-03T10:00:41.000Z",
        metadata: {
          relativePath: "evidence/evidence_completed-filter-failed-8ab0f0a0d82733f1.json"
        }
      }
    ],
    artifacts: [
      {
        id: "artifact_failed-screenshot",
        evidenceId: "evidence_completed-filter-failed",
        kind: "screenshot",
        status: "published",
        path: "/runs/.../artifacts/completed-filter-failed.png",
        mediaType: "image/png",
        sizeBytes: 145212,
        metadata: {
          previewMode: "image",
          inlinePreview:
            "data:image/svg+xml;utf8," +
            encodeURIComponent(
              `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#f3e7de"/><rect x="36" y="32" width="568" height="296" rx="18" fill="#fffaf3" stroke="#c8a9a5"/><text x="70" y="110" font-family="Arial" font-size="30" fill="#8a3128">Completed tab clicked</text><text x="70" y="162" font-family="Arial" font-size="18" fill="#7b554f">List contents unchanged after expected state transition.</text></svg>`
            )
        }
      },
      {
        id: "artifact_failed-console",
        evidenceId: "evidence_completed-filter-failed",
        kind: "console-log",
        status: "published",
        path: "/runs/.../artifacts/completed-filter-failed.console.log",
        mediaType: "text/plain",
        sizeBytes: 421,
        metadata: {
          previewMode: "text",
          entryCount: 3,
          errorCount: 1,
          firstError: "[error] expected completed rows, found none",
          inlinePreview:
            "[info] completed-filter clicked\n[warn] list-state did not change within 5s\n[error] expected completed rows, found none"
        }
      }
    ],
    findings: [
      {
        id: "finding_completed-filter-regression",
        scenarioId: "scenario_task-filter-completed",
        category: "product-bug",
        severity: "high",
        status: "confirmed",
        title: "Completed filter does not update visible task list",
        summary: "The tab click succeeds, but the DOM never transitions into a completed-state list.",
        recommendation: "Check completed-filter reducer wiring and response mapping.",
        evidenceIds: ["evidence_completed-filter-failed"]
      }
    ],
    oracleEvaluations: [
      {
        id: "oracle-eval_task-filter-completed",
        runId: "run_mission-task-filter-completed-2026-07-03-10-00-00",
        scenarioId: "scenario_task-filter-completed",
        oracleId: "oracle_task-filter-completed",
        result: "fail",
        summary: "Completed filter oracle failed because the expected state change never appeared in the observed evidence.",
        evidenceIds: ["evidence_completed-filter-failed"],
        checkResults: [
          {
            checkId: "completed-list-visible",
            name: "Completed list visible",
            kind: "state",
            requiredEvidence: ["dom-snapshot", "screenshot"],
            result: "fail",
            summary: "Required evidence existed, but the completed-state UI expectation was contradicted by the step outcome.",
            evidenceIds: ["evidence_completed-filter-failed"]
          }
        ]
      }
    ],
    judgeReport: {
      id: "judge_task-filter-completed",
      runId: "run_mission-task-filter-completed-2026-07-03-10-00-00",
      oracleIds: ["oracle_task-filter-completed"],
      findingIds: ["finding_task-filter-completed"],
      status: "published",
      result: "fail",
      narrative:
        "The agent reached the target page and collected evidence, but the expected business state change never occurred.",
      metadata: {
        source: "deterministic_judge",
        executionMode: "scripted",
        llmStatus: "not_configured",
        policyVersion: "judge-policy-v1"
      },
      machineSummary: {
        decision: "fail",
        confidence: 0.89,
        flaky: false,
        blocked: false
      }
    }
  };
}

export function getDemoTestOfficerRegistryManifest(): TestOfficerRegistryManifest {
  return {
    schemaVersion: "1.0",
    runId: "run_mission-task-filter-completed-2026-07-03-10-00-00",
    missionId: "mission_task-filter-completed",
    generatedAt: "2026-07-03T10:00:41.000Z",
    entries: [
      {
        kind: "onboarding-protocol",
        path: "/runs/current/registry/onboarding.json",
        recordCount: 4
      },
      {
        kind: "mission-package",
        path: "/runs/current/registry/mission-package.json",
        recordCount: 4
      },
      {
        kind: "selector-map-registry",
        path: "/runs/current/registry/selector-maps.json",
        recordCount: 1
      },
      {
        kind: "fixture-registry",
        path: "/runs/current/registry/fixtures.json",
        recordCount: 1
      },
      {
        kind: "scenario-registry",
        path: "/runs/current/registry/scenarios.json",
        recordCount: 1
      },
      {
        kind: "oracle-registry",
        path: "/runs/current/registry/oracles.json",
        recordCount: 1
      },
      {
        kind: "artifact-index",
        path: "/runs/current/registry/artifacts.json",
        recordCount: 2
      },
      {
        kind: "evidence-index",
        path: "/runs/current/registry/evidence.json",
        recordCount: 1
      },
      {
        kind: "judge-report",
        path: "/runs/current/registry/judge-report.json",
        recordCount: 1
      }
    ],
  counts: {
    onboardingProtocols: 1,
    missionPackages: 1,
    selectorMaps: 1,
    fixtures: 1,
      scenarios: 1,
      oracles: 1,
      artifacts: 2,
      evidence: 1,
      judgeReports: 1
    }
  };
}

export function getDemoTestOfficerEvidenceIndex(): TestOfficerEvidenceRegistryResource[] {
  const manifest = getDemoTestOfficerManifest();
  return manifest.evidence.map((evidence) => ({
    id: evidence.id,
    runId: typeof (evidence as { runId?: string }).runId === "string"
      ? (evidence as { runId: string }).runId
      : manifest.run.id,
    stepId: evidence.stepId,
    scenarioId: evidence.scenarioId,
    kind: evidence.kind,
    status: evidence.status,
    summary: evidence.summary,
    artifactIds: evidence.artifactIds,
    capturedAt: evidence.capturedAt,
    metadata: evidence.metadata
  }));
}

export function getDemoTestOfficerJudgeReport(): TestOfficerJudgeReportResource | undefined {
  const manifest = getDemoTestOfficerManifest();
  return manifest.judgeReport ? { ...manifest.judgeReport } : undefined;
}

export function getDemoTestOfficerOnboardingProtocol(): TestOfficerOnboardingProtocolResource {
  return {
    baseUrl: "http://127.0.0.1:4173",
    accountRef: "demo://local-app/test-user",
    auth: {
      strategy: "session",
      accountRef: "demo://local-app/test-user",
      loginPagePath: "/login"
    },
    project: {
      slug: "todo-demo",
      name: "Todo Demo QA",
      description: "Validate the local demo app across login, list, and form workflows."
    },
    targetApp: {
      name: "Todo Demo",
      environments: ["local"],
      defaultMode: "plan-assisted"
    },
    keyPages: ["/login", "/orders", "/orders/create-form", "/tasks"],
    businessObjective:
      "Verify login, form submission, order state change, and completed-task filtering against the local demo app.",
    selectorHints: [
      "data-testid=login-submit",
      "data-testid=order-submit",
      "data-testid=ship-order-ord-1001",
      "data-testid=task-filter-completed"
    ],
    scenarioRequests: [
      { family: "auth-login", pagePath: "/login", required: true },
      { family: "form-submission", pagePath: "/orders/create-form", required: true },
      { family: "list-state-change", pagePath: "/orders", required: true },
      { family: "golden-path", pagePath: "/tasks", required: true }
    ]
  };
}

export function getDemoTestOfficerMissionPackage(): TestOfficerMissionPackageResource {
  return {
    project: {
      id: "project_todo-demo",
      name: "Todo Demo QA",
      status: "active",
      description: "Validate the local demo app across login, list, and form workflows."
    },
    targetApp: {
      id: "targetapp_todo-demo",
      name: "Todo Demo",
      baseUrl: "http://127.0.0.1:4173",
      status: "configured",
      auth: {
        strategy: "session",
        credentialRef: "demo://local-app/test-user"
      },
      environments: ["local"],
      pages: [
        { id: "login-page", name: "Login", path: "/login" },
        { id: "orders-page", name: "Orders", path: "/orders" },
        { id: "order-form-page", name: "Create order", path: "/orders/create-form" },
        { id: "tasks-page", name: "Tasks", path: "/tasks" }
      ]
    },
    mission: {
      id: "mission_task-filter-completed",
      name: "Todo Demo quality mission",
      objective:
        "Verify login, form submission, order state change, and completed-task filtering against the local demo app.",
      mode: "plan-assisted",
      status: "ready",
      accountRef: "demo://local-app/test-user",
      selectorHintRefs: [
        "selectors.todo-demo#auth-login-submit",
        "selectors.todo-demo#form-submit",
        "selectors.todo-demo#list-state-change-trigger",
        "selectors.todo-demo#golden-path-primary-action"
      ]
    },
    scenarios: [
      {
        id: "scenario_auth-login",
        name: "Login flow",
        goal: "Verify a valid account can authenticate.",
        tags: ["onboarding", "auth-login"],
        targetPageId: "login-page",
        fixtureRefs: ["fixture://onboarding/auth-login"],
        evidenceRequirements: ["screenshot", "dom-snapshot", "console-log"],
        failureClasses: ["product-bug", "selector-drift", "environment-issue"]
      },
      {
        id: "scenario_form-submission",
        name: "Form submission",
        goal: "Verify the main business form can be completed and submitted.",
        tags: ["onboarding", "form-submission"],
        targetPageId: "order-form-page",
        fixtureRefs: ["fixture://onboarding/form-submission"],
        evidenceRequirements: ["screenshot", "dom-snapshot", "network-log"],
        failureClasses: ["product-bug", "test-instability", "environment-issue"]
      },
      {
        id: "scenario_list-state-change",
        name: "List/state change",
        goal: "Verify a visible state transition occurs in a complex list or dashboard.",
        tags: ["onboarding", "list-state-change"],
        targetPageId: "orders-page",
        fixtureRefs: ["fixture://onboarding/list-state-change"],
        evidenceRequirements: ["screenshot", "dom-snapshot", "network-log"],
        failureClasses: ["product-bug", "selector-drift", "environment-issue"]
      },
      {
        id: "scenario_golden-path",
        name: "Golden path",
        goal: "Verify the primary workflow remains reachable.",
        tags: ["onboarding", "golden-path"],
        targetPageId: "tasks-page",
        fixtureRefs: ["fixture://onboarding/golden-path"],
        evidenceRequirements: ["screenshot", "dom-snapshot"],
        failureClasses: ["product-bug", "test-instability", "environment-issue"]
      }
    ],
    oracles: [
      { id: "oracle_auth-login", name: "Login flow oracle", scenarioId: "scenario_auth-login", passPolicy: "all-required" },
      { id: "oracle_form-submission", name: "Form submission oracle", scenarioId: "scenario_form-submission", passPolicy: "all-required" },
      { id: "oracle_list-state-change", name: "List/state change oracle", scenarioId: "scenario_list-state-change", passPolicy: "all-required" },
      { id: "oracle_golden-path", name: "Golden path oracle", scenarioId: "scenario_golden-path", passPolicy: "all-required" }
    ],
    counts: {
      pages: 4,
      selectorHints: 4,
      scenarios: 4,
      oracles: 4
    }
  };
}

export function getDemoTestOfficerSelectorMaps(): TestOfficerSelectorMapResource[] {
  return [
    {
      id: "selectors.todo-demo",
      appId: "targetapp_todo-demo",
      entries: [
        {
          id: "task-filter-completed-tab",
          description: "Completed task filter tab.",
          preferredStrategies: ["test-id", "role", "text"],
          queries: [
            "data-testid=task-filter-completed",
            "role=tab[name='Completed']",
            "text=Completed"
          ]
        },
        {
          id: "task-list",
          description: "Task list region used to observe post-filter state.",
          preferredStrategies: ["test-id"],
          queries: ["data-testid=task-list"]
        }
      ]
    }
  ];
}

export function getDemoTestOfficerFixtures(): TestOfficerFixtureRegistryResource[] {
  return [
    {
      id: "fixture_tasks-completed-seed",
      scenarioId: "scenario_task-filter-completed",
      kind: "seed-data",
      manifestRef: "fixture://tasks/completed-seed"
    }
  ];
}

export function getDemoTestOfficerScenarios(): TestOfficerScenarioRegistryResource[] {
  return [
    {
      id: "scenario_task-filter-completed",
      type: "scenario",
      schemaVersion: "1.0",
      createdAt: now,
      updatedAt: now,
      metadata: { source: "seeded-demo" },
      projectId: "project_todo-demo",
      targetAppId: "targetapp_todo-demo",
      status: "ready",
      name: "Completed task filter works",
      goal: "Verify that switching to the completed filter exposes completed tasks without regression.",
      tags: ["golden-path", "tasks"],
      targetPageId: "tasks-page",
      fixtureRefs: ["fixture://tasks/completed-seed"],
      selectorMapId: "selectors.todo-demo",
      steps: [
        {
          id: "open-completed-filter",
          title: "Open task list",
          intent: "Load the task list before switching filter state.",
          action: "navigate",
          expectedOutcome: "Task list is visible.",
          evidenceRequirements: ["screenshot", "dom-snapshot"]
        },
        {
          id: "switch-completed-filter",
          title: "Open completed filter",
          intent: "Switch the task view into completed mode.",
          action: "click",
          selectorRef: "task-filter-completed-tab",
          expectedOutcome: "Completed tasks become visible.",
          evidenceRequirements: ["screenshot", "dom-snapshot", "console-log"]
        }
      ],
      expectedFindings: [],
      failureClasses: ["product-bug", "selector-drift", "environment-issue"],
      evidenceRequirements: ["screenshot", "dom-snapshot", "console-log"]
    }
  ];
}

export function getDemoTestOfficerOracles(): TestOfficerOracleRegistryResource[] {
  return [
    {
      id: "oracle_task-filter-completed",
      type: "oracle",
      schemaVersion: "1.0",
      createdAt: now,
      updatedAt: now,
      metadata: { source: "seeded-demo" },
      scenarioId: "scenario_task-filter-completed",
      status: "ready",
      name: "Completed filter oracle",
      checks: [
        {
          id: "completed-list-visible",
          name: "Completed list visible",
          kind: "state",
          description: "Validate that the completed task state is visible after switching filters.",
          requiredEvidence: ["dom-snapshot", "screenshot"]
        },
        {
          id: "console-remains-clean",
          name: "Console remains clean",
          kind: "state",
          description: "Check that the transition does not produce a client-side console error.",
          requiredEvidence: ["console-log"]
        }
      ],
      passPolicy: "all-required"
    }
  ];
}

export function getDemoTestOfficerHistory(): TestOfficerHistoryIndex {
  return {
    schemaVersion: "1.0",
    generatedAt: "2026-07-03T10:42:00.000Z",
    runs: [
      {
        runId: "run_mission-task-filter-completed-2026-07-03-10-00-00",
        missionId: "mission_task-filter-completed",
        missionName: "Golden completed-filter mission",
        targetAppId: "targetapp_todo-demo",
        targetAppName: "Todo Demo",
        status: "failed",
        reviewStatus: "fail",
        startedAt: "2026-07-03T10:00:00.000Z",
        finishedAt: "2026-07-03T10:00:41.000Z",
        manifestPath: "/runs/current/manifest.json",
        findingCount: 1,
        failedStepCount: 1,
        artifactCount: 2
      },
      {
        runId: "run_mission-task-filter-completed-2026-07-02-17-15-00",
        missionId: "mission_task-filter-completed",
        missionName: "Golden completed-filter mission",
        targetAppId: "targetapp_todo-demo",
        targetAppName: "Todo Demo",
        status: "passed",
        reviewStatus: "pass",
        startedAt: "2026-07-02T17:15:00.000Z",
        finishedAt: "2026-07-02T17:15:21.000Z",
        manifestPath: "/runs/previous/manifest.json",
        findingCount: 0,
        failedStepCount: 0,
        artifactCount: 2
      }
    ]
  };
}

export function getDemoTestOfficerComparison(): TestOfficerComparisonReport {
  return {
    schemaVersion: "1.0",
    baselineRunId: "run_mission-task-filter-completed-2026-07-02-17-15-00",
    currentRunId: "run_mission-task-filter-completed-2026-07-03-10-00-00",
    missionId: "mission_task-filter-completed",
    summary: {
      statusChanged: true,
      reviewChanged: true,
      findingDelta: 1,
      failedStepDelta: 1,
      artifactDelta: 0
    },
    stepChanges: [
      {
        stepTitle: "Open task list",
        baselineStatus: "passed",
        currentStatus: "passed",
        changed: false
      },
      {
        stepTitle: "Switch to completed filter",
        baselineStatus: "passed",
        currentStatus: "failed",
        changed: true
      }
    ],
    findingChanges: {
      added: ["Completed filter does not update visible task list"],
      resolved: [],
      unchanged: []
    },
    artifactSignalChanges: {
      added: ["console:Uncaught TypeError: cannot read task filter"],
      resolved: [],
      unchanged: []
    }
  };
}
