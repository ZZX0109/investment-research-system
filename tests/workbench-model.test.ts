import { describe, expect, it } from "vitest";
import {
  getDemoAnalysisRuns,
  getDemoAuditRecords,
  getDemoBundle,
  getDemoCatalog,
  getDemoTestOfficerComparison,
  getDemoTestOfficerFixtures,
  getDemoTestOfficerHistory,
  getDemoTestOfficerManifest,
  getDemoTestOfficerMissionPackage,
  getDemoTestOfficerOnboardingProtocol,
  getDemoTestOfficerOracles,
  getDemoTestOfficerRegistryManifest,
  getDemoTestOfficerScenarios,
  getDemoTestOfficerSelectorMaps
} from "../workbench-ui/src/api/demoData";
import { createWorkbenchClient } from "../workbench-ui/src/api/client";
import {
  buildOnboardingPreview,
  clearTimelineDebugSelection,
  buildTimelineDebugContext,
  buildRunTimeline,
  buildTimelineSelectionDetail,
  buildStepInspection,
  createDefaultOnboardingDraft,
  prioritizeArtifacts,
  resolveArtifactPresentation,
  sanitizeOnboardingDraftForRequest,
  buildTestOfficerSummary,
  toneForRunStatus
} from "../workbench-ui/src/features/testOfficer/model";
import { buildRunComparisonSummary } from "../workbench-ui/src/api/runComparison";
import { buildRunLineageTimeline } from "../workbench-ui/src/api/runLineage";
import {
  buildRunDossierSummary,
  buildRunLineageDetailSummary,
  buildRunReplaySummary,
  buildRunScopeSummary
} from "../workbench-ui/src/api/runViews";
import { buildSelectedRunDossier } from "../workbench-ui/src/features/dossier/model";
import { buildSelectedRunContext } from "../workbench-ui/src/features/governance/runContextModel";
import {
  buildFocusedEvidenceList,
  filterEvidenceForSelectedRun,
  filterReportsForSelectedRun
} from "../workbench-ui/src/features/research/model";
import type { TestOfficerManifest } from "../workbench-ui/src/api/types";

describe("workbench model", () => {
  it("builds a test-officer summary from manifest, history, and comparison", () => {
    const manifest = getDemoTestOfficerManifest();
    const history = getDemoTestOfficerHistory();
    const comparison = getDemoTestOfficerComparison();
    const registry = getDemoTestOfficerRegistryManifest();
    const onboarding = getDemoTestOfficerOnboardingProtocol();
    const missionPackage = getDemoTestOfficerMissionPackage();
    const summary = buildTestOfficerSummary(
      manifest,
      history,
      comparison,
      registry,
      onboarding,
      missionPackage
    );

    expect(summary.stepCount).toBe(manifest.steps.length);
    expect(summary.failingSteps).toBe(1);
    expect(summary.findingCount).toBe(1);
    expect(summary.recentRuns).toHaveLength(2);
    expect(summary.comparisonDelta?.findings).toBe(1);
    expect(summary.comparisonDelta?.artifactSignals).toBe(1);
    expect(summary.comparisonDelta?.riskTrend).toBe("stable");
    expect(summary.comparisonDelta?.judgeDecisionChanged).toBe(false);
    expect(summary.comparisonDelta?.failureAttributionDelta).toBe(0);
    expect(summary.registrySummary?.entries).toHaveLength(9);
    expect(summary.registrySummary?.onboardingSummary?.pageCount).toBe(4);
    expect(summary.registrySummary?.missionPackageSummary?.scenarioCount).toBe(4);
    expect(summary.registrySummary?.missionPackageSummary?.scenarioNames).toContain("Form submission");
    expect(manifest.artifacts[0]?.metadata?.previewMode).toBe("image");
    expect(manifest.artifacts[0]?.metadata?.inlinePreview).toContain("data:image/svg+xml");
  });

  it("summarizes run bundle operating context for real-project workbench views", () => {
    const base = getDemoTestOfficerManifest();
    const manifest: TestOfficerManifest = {
      ...base,
      run: {
        ...base.run,
        metadata: {
          ...base.run.metadata,
          runtimeLifecycle: [
            {
              phase: "start",
              status: "passed",
              startedAt: "2026-07-06T00:00:00.000Z",
              finishedAt: "2026-07-06T00:00:01.000Z",
              summary: "Started configured target app"
            },
            {
              phase: "health-check",
              status: "failed",
              startedAt: "2026-07-06T00:00:01.000Z",
              finishedAt: "2026-07-06T00:00:11.000Z",
              summary: "Health check did not return 200",
              attempts: 3,
              error: "HTTP 503"
            }
          ]
        }
      },
      sourceContexts: [
        {
          schemaVersion: "1.0",
          adapter: {
            id: "git-diff:workspace",
            kind: "git-diff",
            label: "Workspace diff",
            permissions: ["workspace-read"],
            usageScopes: ["planning", "failure-analysis", "judge"],
            sourceRef: "workspace://diff"
          },
          readState: "ready",
          readAt: "2026-07-06T00:00:00.000Z",
          payload: { changedFiles: ["src/tasks/filter.ts"] },
          metadata: {
            byteLength: 1200,
            truncated: false,
            contentType: "text/x-diff",
            trust: {
              level: "trusted",
              reasons: ["Read from workspace root."]
            },
            permissionExplanations: [
              {
                permission: "workspace-read",
                reason: "Reads files inside the configured workspace root."
              }
            ],
            cache: {
              status: "bypass"
            }
          }
        },
        {
          schemaVersion: "1.0",
          adapter: {
            id: "github-pr:owner/repo#42",
            kind: "github-pr",
            label: "GitHub PR owner/repo#42",
            permissions: ["network-read", "credential-read"],
            usageScopes: ["planning", "failure-analysis", "reporting"],
            sourceRef: "https://github.com/owner/repo/pull/42"
          },
          readState: "failed",
          readAt: "2026-07-06T00:00:00.000Z",
          failureReason: "HTTP 403",
          metadata: {
            byteLength: 0,
            truncated: false,
            retry: {
              attempts: 2,
              maxAttempts: 2,
              retryable: false,
              lastStatus: 403
            },
            rateLimit: {
              remaining: 0
            },
            trust: {
              level: "low-confidence",
              reasons: ["Connector source was failed."]
            }
          }
        }
      ],
      failureAttributions: [
        {
          id: "failure-attribution_1",
          schemaVersion: "1.0",
          runId: base.run.id,
          findingId: base.findings[0]!.id,
          scenarioId: base.findings[0]!.scenarioId,
          stepId: "step_switch-filter",
          rank: 1,
          category: "product-bug",
          confidence: 0.82,
          likelyCause: "Completed filter regression is closest to the task filter diff.",
          recommendation: "Inspect filter predicate and retry after fixing completed task visibility.",
          signals: {
            evidenceIds: ["evidence_completed-filter-failed"],
            artifactIds: ["artifact_completed-filter-screenshot"],
            sourceContextIds: ["git-diff:workspace"],
            changedFiles: ["src/tasks/filter.ts"],
            consoleErrorArtifacts: ["artifact_completed-filter-console"],
            consoleErrorSummaries: ["Uncaught TypeError: cannot read completed filter"],
            networkErrorArtifacts: ["artifact_completed-filter-network"],
            networkErrorSummaries: ["GET /api/tasks?filter=completed 500"],
            domSnapshotArtifacts: ["artifact_completed-filter-dom"],
            retrySignals: {
              attemptCount: 2,
              maxAttempts: 2,
              retried: true,
              lastRetryTrigger: "selector-timeout"
            },
            runtimeSignals: [
              { phase: "health-check", status: "failed", summary: "Health check did not return 200" }
            ]
          },
          createdAt: "2026-07-06T00:00:12.000Z"
        }
      ],
      retentionCleanupPlan: {
        schemaVersion: "1.0",
        runId: base.run.id,
        generatedAt: "2026-07-06T00:00:12.000Z",
        policy: {
          retainRunsDays: 30,
          retainArtifactsDays: 14,
          retainReportsDays: 90,
          retainTraceDays: 7,
          retainVideoDays: 7,
          dryRun: true
        },
        candidates: [
          {
            id: "artifact_completed-filter-screenshot",
            kind: "artifact",
            path: "artifacts/screenshot.png",
            action: "delete-after-retention",
            reason: "artifact retention policy",
            protected: false
          },
          {
            id: "registry_manifest",
            kind: "registry",
            path: "registry/resource-manifest.json",
            action: "retain",
            reason: "registry is protected",
            protected: true
          }
        ]
      }
    };

    const summary = buildTestOfficerSummary(manifest);

    expect(summary.runtimeSummary.status).toBe("failed");
    expect(summary.runtimeSummary.health).toBe("failed · 3 attempts");
    expect(summary.sourceContextSummary.ready).toBe(1);
    expect(summary.sourceContextSummary.failed).toBe(1);
    expect(summary.sourceContextSummary.permissions).toContain("credential-read");
    expect(summary.sourceContextSummary.boundary).toMatchObject({
      status: "degraded",
      credentialedSources: 1,
      failedOrBlockedSources: 1,
      lowTrustSources: 1,
      judgeConsumerSources: 1
    });
    expect(summary.sourceContextSummary.boundary.warnings).toEqual(
      expect.arrayContaining([
        "1 source(s) required credential access.",
        "1 source(s) failed or were blocked before planning/judging.",
        "1 source(s) are unverified or low-confidence.",
        "1 source(s) were available to judge decisions."
      ])
    );
    expect(summary.sourceContextSummary.permissionCards).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          permission: "workspace-read",
          count: 1,
          reasons: ["Reads files inside the configured workspace root."]
        }),
        expect.objectContaining({
          permission: "credential-read",
          count: 1,
          reasons: ["Uses an explicit connector credential or token for private source context."]
        })
      ])
    );
    expect(summary.sourceContextSummary.entries[0]?.trust?.level).toBe("trusted");
    expect(summary.sourceContextSummary.entries[0]?.permissionExplanations[0]?.permission).toBe("workspace-read");
    expect(summary.sourceContextSummary.entries[1]?.retry?.lastStatus).toBe(403);
    expect(summary.sourceContextSummary.entries[1]?.rateLimit?.remaining).toBe(0);
    expect(summary.failureAttributionSummary.topCause).toContain("Completed filter regression");
    expect(summary.failureAttributionSummary.entries[0]?.signalSummary).toContain("1 changed files");
    expect(summary.failureAttributionSummary.entries[0]?.signalSummary).toEqual(
      expect.arrayContaining([
        expect.stringContaining("console: Uncaught TypeError"),
        expect.stringContaining("network: GET /api/tasks")
      ])
    );
    expect(summary.failureAttributionSummary.entries[0]?.signalSummary).toContain("retried 2/2");
    expect(summary.retentionSummary.total).toBe(2);
    expect(summary.retentionSummary.protected).toBe(1);
  });

  it("maps review outcomes into UI tones", () => {
    expect(toneForRunStatus("pass")).toBe("good");
    expect(toneForRunStatus("blocked")).toBe("warn");
    expect(toneForRunStatus("fail")).toBe("bad");
  });

  it("links a selected step to its scenario, evidence, artifacts, and findings", () => {
    const manifest = getDemoTestOfficerManifest();
    const inspection = buildStepInspection(manifest, "step_switch-filter", {
      selectorMaps: getDemoTestOfficerSelectorMaps(),
      fixtures: getDemoTestOfficerFixtures(),
      scenarios: getDemoTestOfficerScenarios(),
      oracles: getDemoTestOfficerOracles()
    });

    expect(inspection?.scenario?.name).toBe("Completed task filter works");
    expect(inspection?.scenarioContract?.failureClasses).toContain("selector-drift");
    expect(inspection?.selectorContract?.preferredStrategies[0]).toBe("test-id");
    expect(inspection?.fixtureContracts[0]?.manifestRef).toBe("fixture://tasks/completed-seed");
    expect(inspection?.oracleContracts[0]?.checks[0]?.name).toBe("Completed list visible");
    expect(inspection?.evidence).toHaveLength(1);
    expect(inspection?.artifacts).toHaveLength(2);
    expect(inspection?.findings[0]?.category).toBe("product-bug");
    expect(inspection?.planRecord?.status).toBe("failed");
    expect(inspection?.oracleEvaluations[0]?.result).toBe("fail");
    expect(inspection?.durationLabel).toBe("33.0 s");
    expect(inspection?.reportLinks.map((link) => link.label)).toContain("gate");
  });

  it("builds a layered run timeline for planning, execution, evidence, and verdict phases", () => {
    const manifest = getDemoTestOfficerManifest();
    const timeline = buildRunTimeline(manifest, { stepId: "step_switch-filter" });

    expect(timeline.sections.map((section) => section.id)).toEqual([
      "planning",
      "execution",
      "evidence",
      "verdict"
    ]);
    expect(timeline.sections[0]?.items[0]?.phase).toBe("planning");
    expect(timeline.sections[1]?.items.some((item) => item.relatedStepId === "step_switch-filter")).toBe(true);
    expect(timeline.sections[2]?.items[0]?.phase).toBe("evidence");
    expect(timeline.sections[3]?.items.some((item) => item.phase === "oracle")).toBe(true);
  });

  it("keeps explicit source-layer metadata on seeded run bundles and derived views", () => {
    const bundle = getDemoBundle();
    const replay = buildRunReplaySummary(bundle);
    const dossier = buildRunDossierSummary(bundle);

    expect(bundle.source_meta.mode).toBe("demo");
    expect(bundle.snapshot.source_meta.provider).toContain("demo-seed-market-provider");
    expect(replay.source_meta.synthetic_ratio).toBe(bundle.snapshot.synthetic_ratio);
    expect(dossier.source_meta.as_of).toBe(bundle.snapshot.as_of);
  });

  it("builds node-specific timeline detail for evidence and oracle selections", () => {
    const manifest = getDemoTestOfficerManifest();
    const inspection = buildStepInspection(manifest, "step_switch-filter", {
      selectorMaps: getDemoTestOfficerSelectorMaps(),
      fixtures: getDemoTestOfficerFixtures(),
      scenarios: getDemoTestOfficerScenarios(),
      oracles: getDemoTestOfficerOracles()
    });
    const evidenceTimeline = buildRunTimeline(manifest, {
      stepId: "step_switch-filter",
      nodeKey: "evidence:evidence_completed-filter-failed"
    });
    const oracleTimeline = buildRunTimeline(manifest, {
      stepId: "step_switch-filter",
      nodeKey: "oracle:oracle-eval_task-filter-completed"
    });
    const evidenceDetail = buildTimelineSelectionDetail(
      manifest,
      evidenceTimeline,
      "evidence:evidence_completed-filter-failed",
      inspection
    );
    const oracleDetail = buildTimelineSelectionDetail(
      manifest,
      oracleTimeline,
      "oracle:oracle-eval_task-filter-completed",
      inspection
    );
    const focusedOracleDetail = buildTimelineSelectionDetail(
      manifest,
      oracleTimeline,
      "oracle:oracle-eval_task-filter-completed",
      inspection,
      "completed-list-visible"
    );

    expect(evidenceDetail?.phase).toBe("Evidence");
    expect(evidenceDetail?.details[0]?.value).toBe("evidence_completed-filter-failed");
    expect(evidenceDetail?.artifacts).toHaveLength(2);
    expect(evidenceDetail?.linkedEvidence[0]?.id).toBe("evidence_completed-filter-failed");
    expect(oracleDetail?.phase).toBe("Oracle");
    expect(oracleDetail?.details[0]?.value).toBe("all-required");
    expect(oracleDetail?.checkResults[0]?.checkId).toBe("completed-list-visible");
    expect(oracleDetail?.linkedEvidence[0]?.id).toBe("evidence_completed-filter-failed");
    expect(focusedOracleDetail?.checkResults).toHaveLength(1);
    expect(focusedOracleDetail?.details[3]?.value).toBe("completed-list-visible");
  });

  it("exposes executable plan contracts in timeline detail", () => {
    const base = getDemoTestOfficerManifest();
    const manifest = {
      ...base,
      plan: base.plan.map((record) =>
        record.stepId === "step_switch-filter"
          ? {
              ...record,
              assertions: [
                {
                  id: "assert_completed-visible",
                  kind: "dom-text",
                  target: "[data-testid=completed-list]",
                  expected: "Completed"
                }
              ],
              failureCriteria: [
                {
                  id: "failure_completed-hidden",
                  category: "product-bug",
                  condition: "Completed list is not visible",
                  severity: "high"
                }
              ],
              retryPolicy: {
                maxAttempts: 2,
                retryOn: ["timeout", "selector-missing"],
                backoffMs: 250
              }
            }
          : record
      )
    };
    const inspection = buildStepInspection(manifest, "step_switch-filter");
    const timeline = buildRunTimeline(manifest, {
      stepId: "step_switch-filter",
      nodeKey: "planning:plan_step-switch-filter"
    });
    const detail = buildTimelineSelectionDetail(
      manifest,
      timeline,
      "planning:plan_step-switch-filter",
      inspection
    );

    expect(detail?.details.find((entry) => entry.label === "Assertions")?.value).toContain(
      "[data-testid=completed-list] => Completed"
    );
    expect(detail?.details.find((entry) => entry.label === "Failure Criteria")?.value).toContain(
      "product-bug/high"
    );
    expect(detail?.details.find((entry) => entry.label === "Retry Policy")?.value).toBe(
      "2 attempts · timeout, selector-missing · 250ms"
    );
  });

  it("prioritizes the focused artifact to the front of the preview list", () => {
    const manifest = getDemoTestOfficerManifest();
    const ordered = prioritizeArtifacts(manifest.artifacts, manifest.artifacts[1]?.id);

    expect(ordered[0]?.id).toBe(manifest.artifacts[1]?.id);
  });

  it("highlights timeline evidence related to the selected oracle check", () => {
    const manifest = getDemoTestOfficerManifest();
    const timeline = buildRunTimeline(manifest, {
      stepId: "step_switch-filter",
      nodeKey: "oracle:oracle-eval_task-filter-completed",
      checkId: "completed-list-visible"
    });
    const evidenceSection = timeline.sections.find((section) => section.id === "evidence");
    const verdictSection = timeline.sections.find((section) => section.id === "verdict");
    const executionSection = timeline.sections.find((section) => section.id === "execution");

    expect(evidenceSection?.items.find((item) => item.id === "evidence_completed-filter-failed")?.emphasis).toBe("highlighted");
    expect(verdictSection?.items.find((item) => item.id === "oracle-eval_task-filter-completed")?.emphasis).toBe("highlighted");
    expect(executionSection?.items.find((item) => item.relatedStepId === "step_switch-filter")?.emphasis).toBe("highlighted");
  });

  it("builds a visible debug context summary for node, check, and artifact focus", () => {
    const context = buildTimelineDebugContext({
      selectedNodeKey: "oracle:oracle-eval_task-filter-completed",
      selectedCheckId: "completed-list-visible",
      selectedArtifactId: "artifact_completed-filter-screenshot"
    });

    expect(context.active).toBe(true);
    expect(context.tokens.map((token) => token.id)).toEqual(["node", "check", "artifact"]);
    expect(context.tokens[1]?.value).toBe("completed-list-visible");
  });

  it("clears individual debug context tokens without dropping unrelated focus", () => {
    const selection = {
      selectedNodeKey: "oracle:oracle-eval_task-filter-completed",
      selectedCheckId: "completed-list-visible",
      selectedArtifactId: "artifact_completed-filter-screenshot"
    };

    expect(clearTimelineDebugSelection(selection, "artifact")).toEqual({
      selectedNodeKey: "oracle:oracle-eval_task-filter-completed",
      selectedCheckId: "completed-list-visible",
      selectedArtifactId: null
    });
    expect(clearTimelineDebugSelection(selection, "check")).toEqual({
      selectedNodeKey: "oracle:oracle-eval_task-filter-completed",
      selectedCheckId: null,
      selectedArtifactId: "artifact_completed-filter-screenshot"
    });
    expect(clearTimelineDebugSelection(selection, "node")).toEqual({
      selectedNodeKey: null,
      selectedCheckId: null,
      selectedArtifactId: "artifact_completed-filter-screenshot"
    });
  });

  it("uses inline previews for display while keeping token-gated artifact URLs for download", () => {
    const manifest = getDemoTestOfficerManifest();
    const demoPresentation = resolveArtifactPresentation(manifest.artifacts[0]!);
    const livePresentation = resolveArtifactPresentation({
      ...manifest.artifacts[0]!,
      metadata: {
        ...manifest.artifacts[0]!.metadata,
        artifactUrl: "/api/v1/test-officer/runs/run_live/artifacts/screenshot.png"
      }
    });

    expect(demoPresentation.imageSrc).toContain("data:image/svg+xml");
    expect(livePresentation.imageSrc).toBe("/api/v1/test-officer/runs/run_live/artifacts/screenshot.png");
    expect(livePresentation.downloadUrl).toBe("/api/v1/test-officer/runs/run_live/artifacts/screenshot.png");
  });

  it("builds a typed onboarding draft preview from the latest manifest", () => {
    const manifest = getDemoTestOfficerManifest();
    const draft = createDefaultOnboardingDraft(manifest);
    const preview = buildOnboardingPreview(draft);

    expect(draft.projectName).toBe(manifest.project.name);
    expect(draft.targetAppName).toBe(manifest.targetApp.name);
    expect(draft.authStrategy).toBe(manifest.targetApp.auth?.strategy ?? "session");
    expect(draft.environments).toEqual(manifest.targetApp.environments ?? ["default"]);
    if (manifest.targetApp.runtime) {
      expect(draft.runtime?.healthCheck?.url).toBe(manifest.targetApp.runtime.healthCheck?.url);
    }
    expect(draft.scenarioRequests).toHaveLength(4);
    expect(preview.readiness).toBe("ready");
    expect(preview.enabledScenarioCount).toBe(4);
    expect(preview.pageCount).toBeGreaterThan(0);
    expect(preview.scenarios.map((scenario) => scenario.family)).toContain("golden-path");
  });

  it("sanitizes workbench onboarding requests without dropping real-project runtime contracts", () => {
    const draft = createDefaultOnboardingDraft();
    const sanitized = sanitizeOnboardingDraftForRequest({
      ...draft,
      accountRef: " vault://accounts/admin ",
      environments: [" staging ", ""],
      keyPages: ["/login", ""],
      selectorHints: [" data-testid=login-submit ", ""],
      loginPagePath: " /login ",
      workspaceRoot: " /workspace/customer-portal ",
      prUrl: " https://github.com/acme/customer-portal/pull/42 ",
      requirementDocs: [" docs/requirements/login.md ", ""],
      bugTickets: [" docs/bugs/BUG-123.md "],
      apiDocs: [" docs/openapi.json "],
      gitDiffs: [" patches/pr-42.diff ", ""],
      githubIssues: [" https://github.com/acme/customer-portal/issues/43 "],
      jiraIssues: [" https://company.atlassian.net/browse/QA-123 "],
      openApiUrls: [" https://api.example.test/openapi.json "],
      requirementText: " Admins must be able to sign in. ",
      runtime: {
        start: {
          command: " pnpm ",
          args: ["preview"]
        },
        healthCheck: {
          url: " https://portal.example.test/healthz ",
          expectedStatus: []
        },
        cleanup: {
          command: "",
          args: ["run", "test:cleanup"]
        },
        routes: [
          { id: "login", path: "/login", purpose: "login", authenticated: false }
        ],
        testAccounts: [
          { id: "admin", role: "admin", credentialRef: "vault://accounts/admin" }
        ],
        env: [
          { name: "API_TOKEN", secretRef: "vault://secrets/api-token", scope: "test" }
        ]
      }
    });

    expect(sanitized.accountRef).toBe("vault://accounts/admin");
    expect(sanitized.environments).toEqual(["staging"]);
    expect(sanitized.keyPages).toEqual(["/login"]);
    expect(sanitized.selectorHints).toEqual(["data-testid=login-submit"]);
    expect(sanitized.loginPagePath).toBe("/login");
    expect(sanitized.workspaceRoot).toBe("/workspace/customer-portal");
    expect(sanitized.prUrl).toBe("https://github.com/acme/customer-portal/pull/42");
    expect(sanitized.requirementDocs).toEqual(["docs/requirements/login.md"]);
    expect(sanitized.bugTickets).toEqual(["docs/bugs/BUG-123.md"]);
    expect(sanitized.apiDocs).toEqual(["docs/openapi.json"]);
    expect(sanitized.gitDiffs).toEqual(["patches/pr-42.diff"]);
    expect(sanitized.githubIssues).toEqual(["https://github.com/acme/customer-portal/issues/43"]);
    expect(sanitized.jiraIssues).toEqual(["https://company.atlassian.net/browse/QA-123"]);
    expect(sanitized.openApiUrls).toEqual(["https://api.example.test/openapi.json"]);
    expect(sanitized.requirementText).toBe("Admins must be able to sign in.");
    expect(sanitized.runtime?.start?.command).toBe("pnpm");
    expect(sanitized.runtime?.healthCheck?.expectedStatus).toEqual([200]);
    expect(sanitized.runtime?.cleanup).toBeUndefined();
    expect(sanitized.runtime?.routes).toHaveLength(1);
    expect(sanitized.runtime?.testAccounts).toHaveLength(1);
    expect(sanitized.runtime?.env).toHaveLength(1);
  });

  it("keeps browser execution controls in the seeded run creation response", async () => {
    const client = createWorkbenchClient("demo");
    const response = await client.createTestOfficerRun({
      projectName: "Customer Portal QA",
      targetAppName: "Customer Portal",
      baseUrl: "https://portal.example.test",
      accountRef: "vault://accounts/customer-admin",
      businessObjective: "Verify admins can sign in and create a customer.",
      mode: "plan-assisted",
      keyPages: ["/login", "/customers/new"],
      selectorHints: ["data-testid=login-submit"],
      scenarioRequests: [
        { family: "auth-login", pagePath: "/login", enabled: true }
      ],
      executor: "playwright",
      headless: false,
      trace: true,
      recordVideo: true
    });

    expect(response.executor).toBe("playwright");
    expect(response.headless).toBe(false);
    expect(response.trace).toBe(true);
    expect(response.recordVideo).toBe(true);
    expect(response.manifest.mission.mode).toBe("plan-assisted");
    expect(response.gate?.diagnostics?.newFindings?.length).toBeGreaterThan(0);
    expect(response.gate?.diagnostics?.newArtifactSignals?.[0]).toContain("expected completed rows");
  });

  it("exposes run-level audit detail through the workbench client", async () => {
    const client = createWorkbenchClient("demo");
    const manifest = getDemoTestOfficerManifest();
    const detail = await client.getTestOfficerAuditRunDetail(manifest.run.id);

    expect(detail.runId).toBe(manifest.run.id);
    expect(detail.sourceContexts.length).toBe(manifest.sourceContexts?.length ?? 0);
    expect(detail.failureAttributions.length).toBe(
      manifest.failureAttributions?.length ? manifest.failureAttributions.length : manifest.findings.length
    );
    expect(detail.artifacts.length).toBe(manifest.artifacts.length);
    expect(detail.gateResults[0]).toMatchObject({
      id: `${manifest.run.id}:gate`,
      exitCode: 2
    });
    expect(detail.runtimeLifecycle.length).toBe(manifest.run.metadata?.runtimeLifecycle?.length ?? 0);
    if (detail.sourceContexts.length > 0) {
      expect(detail.sourceContexts[0]?.usageScopes.length).toBeGreaterThan(0);
    }
    if (detail.failureAttributions.length > 0) {
      expect(detail.failureAttributions[0]?.likelyCause).toBeTruthy();
      expect(detail.failureAttributions[0]?.recommendation).toBeTruthy();
      expect(detail.failureAttributions[0]?.signals).toHaveProperty("evidenceIds");
    }
    if (detail.artifacts.length > 0) {
      expect(detail.artifacts[0]?.metadata).toBeDefined();
      expect(detail.artifacts.find((artifact) => artifact.kind === "console-log")?.metadata.firstError)
        .toContain("expected completed rows");
    }
  });

  it("exposes seeded registry manifests through the workbench client", async () => {
    const client = createWorkbenchClient("demo");
    const registry = await client.getTestOfficerRegistryManifest(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );

    expect(registry.counts.scenarios).toBe(1);
    expect(registry.counts.onboardingProtocols).toBe(1);
    expect(registry.entries.map((entry) => entry.kind)).toContain("selector-map-registry");
  });

  it("exposes seeded onboarding and mission-package registry resources through the workbench client", async () => {
    const client = createWorkbenchClient("demo");
    const onboarding = await client.getTestOfficerOnboardingProtocol(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );
    const missionPackage = await client.getTestOfficerMissionPackage(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );

    expect(onboarding.keyPages).toHaveLength(4);
    expect(onboarding.scenarioRequests.map((scenario) => scenario.family)).toContain("form-submission");
    expect(missionPackage.counts.scenarios).toBe(4);
    expect(missionPackage.scenarios.map((scenario) => scenario.name)).toContain("Golden path");
  });

  it("exposes seeded selector, fixture, scenario, and oracle registry resources through the workbench client", async () => {
    const client = createWorkbenchClient("demo");
    const selectorMaps = await client.getTestOfficerSelectorMaps(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );
    const fixtures = await client.getTestOfficerFixtures(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );
    const scenarios = await client.getTestOfficerScenarios(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );
    const oracles = await client.getTestOfficerOracles(
      "run_mission-task-filter-completed-2026-07-03-10-00-00"
    );

    expect(selectorMaps[0]?.entries[0]?.id).toBe("task-filter-completed-tab");
    expect(fixtures[0]?.kind).toBe("seed-data");
    expect(scenarios[0]?.failureClasses).toContain("environment-issue");
    expect(oracles[0]?.checks[0]?.requiredEvidence).toContain("dom-snapshot");
  });

  it("exposes provider configuration in seeded catalog data", () => {
    const catalog = getDemoCatalog();

    expect(catalog.analysis_provider_config.market_data_provider).toBe("persisted_fallback");
    expect(catalog.analysis_providers[0]?.provider_name).toContain("market-provider");
  });

  it("keeps seeded run lineage fields stable for report reproducibility", () => {
    const bundle = getDemoBundle();

    expect(bundle.run.input_snapshot_ref).toContain("analysis-snapshots");
    expect(bundle.snapshot.intake_strategy).toBe("seeded_demo_bundle");
    expect(bundle.snapshot.price_provider_status).toBe("seeded");
    expect(bundle.snapshot.fallback_reasons[0]).toContain("presentation-only");
    expect(bundle.reports[0]?.report_version).toBeTruthy();
  });

  it("exposes multiple seeded runs so history playback can switch fixed reports", () => {
    const runs = getDemoAnalysisRuns("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001");
    const historical = getDemoBundle("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001", runs[1]?.id);

    expect(runs).toHaveLength(2);
    expect(runs[0]?.created_at > runs[1]?.created_at).toBe(true);
    expect(historical.run.id).toBe(runs[1]?.id);
    expect(historical.reports[0]?.report_version).toBe("auto-0.9.0");
  });

  it("builds a human-scale delta between frozen runs", () => {
    const runs = getDemoAnalysisRuns("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001");
    const current = getDemoBundle("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001", runs[0]?.id);
    const baseline = getDemoBundle("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001", runs[1]?.id);
    const summary = buildRunComparisonSummary(current, baseline);

    expect(summary.current_report_version).toBe("auto-1.0.0");
    expect(summary.baseline_report_version).toBe("auto-0.9.0");
    expect(summary.judge_score_delta).toBeGreaterThan(0);
    expect(summary.confidence_delta).toBeGreaterThan(0);
    expect(summary.added_gates).toContain("No real-market confirmation attached");
    expect(summary.removed_gates).toContain("Historical demo run retained for lineage playback");
    expect(summary.removed_fallbacks).toContain("Older seeded run preserved for report comparison and workflow playback.");
    expect(summary.thesis_changed).toBe(true);
  });

  it("builds a seeded run lineage timeline with report and audit milestones", () => {
    const assetId = "c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001";
    const runs = getDemoAnalysisRuns(assetId);
    const bundles = runs.map((run) => getDemoBundle(assetId, run.id));
    const timeline = buildRunLineageTimeline(assetId, bundles, getDemoAuditRecords());

    expect(timeline.asset_id).toBe(assetId);
    expect(timeline.entries).toHaveLength(2);
    expect(timeline.entries[0]?.report_version).toBe("auto-1.0.0");
    expect(timeline.entries[0]?.evidence_count).toBeGreaterThan(0);
    expect(timeline.entries[0]?.evidence_items[0]?.title).toBe("Demand stack remains full");
    expect(timeline.entries[0]?.evidence_items[0]?.summary).toContain("hyperscaler orders");
    expect(timeline.entries[0]?.report_thesis).toContain("fixed run");
    expect(timeline.entries[0]?.recommendation_reasoning).toContain("Judge gate");
    expect(timeline.entries[0]?.audit_actions).toContain("report.generated");
    expect(timeline.entries[1]?.report_version).toBe("auto-0.9.0");
  });

  it("promotes lineage-focused evidence to the top of research review", () => {
    const bundle = getDemoBundle();
    const view = buildFocusedEvidenceList(bundle.evidence, bundle.evidence[1]?.id);

    expect(view.focusedEvidence?.id).toBe(bundle.evidence[1]?.id);
    expect(view.orderedEvidence[0]?.id).toBe(bundle.evidence[1]?.id);
    expect(view.orderedEvidence[1]?.id).toBe(bundle.evidence[0]?.id);
  });

  it("can filter research evidence down to the selected immutable run set", () => {
    const bundle = getDemoBundle();
    const filtered = filterEvidenceForSelectedRun(bundle.evidence, [bundle.evidence[1]!.id], true);

    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.id).toBe(bundle.evidence[1]?.id);
  });

  it("can filter research reports down to the selected immutable run set", () => {
    const current = getDemoBundle();
    const historical = getDemoBundle("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001", "09c5233b-a4dc-4d8d-908f-cd7c7c9b2001");
    const filtered = filterReportsForSelectedRun(
      [current.reports[0]!, historical.reports[0]!],
      current.run.id,
      current.run.report_ids,
      true
    );

    expect(filtered).toHaveLength(1);
    expect(filtered[0]?.analysis_run_id).toBe(current.run.id);
  });

  it("builds a dossier summary from the selected immutable run bundle", () => {
    const bundle = getDemoBundle();
    const summary = buildRunDossierSummary(bundle);
    const dossier = buildSelectedRunDossier(summary);

    expect(dossier?.reportVersion).toBe("auto-1.0.0");
    expect(dossier?.judgeVerdict).toBe("warn");
    expect(dossier?.gateCount).toBeGreaterThan(0);
    expect(dossier?.fallbackCount).toBeGreaterThan(0);
    expect(dossier?.recommendationAction).toBe("hold");
    expect(dossier?.provider).toContain("demo-seed-market-provider");
    expect(dossier?.refreshRecommendation).toBe(bundle.snapshot.refresh_recommendation);
    expect(dossier?.staleReasons).toEqual(bundle.snapshot.stale_reasons);
    expect(dossier?.evidenceCitationIds).toEqual(bundle.snapshot.evidence_citation_ids);
    expect(dossier?.modelName).toBe("heuristic-trend-ensemble");
    expect(dossier?.modelStatus).toBe("demo_seed");
    expect(dossier?.deploymentApproved).toBe(false);
    expect(dossier?.riskProbability).toBe(0.58);
    expect(dossier?.featureCoverage).toBe(0.62);
  });

  it("builds a global run replay context from the selected immutable run bundle", () => {
    const bundle = getDemoBundle();
    const summary = buildRunReplaySummary(bundle);
    const context = buildSelectedRunContext(summary, true);

    expect(summary.source_name).toBe(bundle.run.provenance.source_name);
    expect(summary.confidence).toBe(bundle.run.provenance.confidence);
    expect(context?.assetTicker).toBe("NVDA");
    expect(context?.runLabel).toBe(bundle.run.id.slice(0, 8));
    expect(context?.reportVersion).toBe("auto-1.0.0");
    expect(context?.judgeVerdict).toBe("warn");
    expect(context?.sourceName).toBe(bundle.run.provenance.source_name);
    expect(context?.provider).toContain("demo-seed-market-provider");
    expect(context?.onlySelectedRunResearch).toBe(true);
    expect(context?.fallbackCount).toBeGreaterThan(0);
  });

  it("builds a run scope summary from the selected immutable run bundle", () => {
    const bundle = getDemoBundle();
    const summary = buildRunScopeSummary(bundle);

    expect(summary.run_id).toBe(bundle.run.id);
    expect(summary.asset_id).toBe(bundle.asset.id);
    expect(summary.evidence_ids).toEqual(bundle.run.evidence_ids);
    expect(summary.report_ids).toEqual(bundle.run.report_ids);
    expect(summary.evidence_count).toBe(bundle.run.evidence_ids.length);
    expect(summary.report_count).toBe(bundle.run.report_ids.length);
  });

  it("builds a lineage detail summary from the selected immutable run bundle", () => {
    const bundle = getDemoBundle();
    const summary = buildRunLineageDetailSummary(bundle);

    expect(summary.run_id).toBe(bundle.run.id);
    expect(summary.input_snapshot_ref).toBe(bundle.run.input_snapshot_ref);
    expect(summary.intake_strategy).toBe(bundle.snapshot.intake_strategy);
    expect(summary.price_provider_status).toBe(bundle.snapshot.price_provider_status);
    expect(summary.evidence_provider_status).toBe(bundle.snapshot.evidence_provider_status);
    expect(summary.judge_verdict).toBe(bundle.judge_scores[0]?.verdict);
    expect(summary.model_name).toBe(bundle.predictions[0]?.model_name);
    expect(summary.model_status).toBe(bundle.predictions[0]?.model_status);
    expect(summary.risk_probability).toBe(bundle.predictions[0]?.risk_probability);
    expect(summary.report_version).toBe(bundle.reports[0]?.report_version);
    expect(summary.refresh_recommendation).toBe(bundle.snapshot.refresh_recommendation);
    expect(summary.evidence_citation_ids).toEqual(bundle.snapshot.evidence_citation_ids);
  });
});
