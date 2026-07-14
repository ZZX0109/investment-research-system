import type { TestOfficerOnboardingDraft, TestOfficerOnboardingPreview } from "../../../api/types";
import type { TestOfficerSummary } from "../model";
import type { TestOfficerDataState, TestOfficerRuntimeConfig, TestOfficerUiState } from "../useTestOfficerWorkspace";
import { splitCommandArgs, splitList } from "../formatters";
import { Detail } from "./primitives";

interface TestOfficerInputContextProps {
  manifest: NonNullable<TestOfficerDataState["manifest"]>;
  onboardingDraft: TestOfficerOnboardingDraft;
  onboardingPreview: TestOfficerOnboardingPreview;
  requestDraft: TestOfficerOnboardingDraft;
  selectedExecutor: TestOfficerUiState["selectedExecutor"];
  setSelectedExecutor: TestOfficerUiState["setSelectedExecutor"];
  headless: TestOfficerUiState["headless"];
  setHeadless: TestOfficerUiState["setHeadless"];
  traceEnabled: TestOfficerUiState["traceEnabled"];
  setTraceEnabled: TestOfficerUiState["setTraceEnabled"];
  videoEnabled: TestOfficerUiState["videoEnabled"];
  setVideoEnabled: TestOfficerUiState["setVideoEnabled"];
  setDraftOverrides: TestOfficerUiState["setDraftOverrides"];
  updateRuntimeDraft: (nextRuntime: TestOfficerRuntimeConfig) => void;
  summary?: TestOfficerSummary;
  missionPreviewMutation: TestOfficerDataState["missionPreviewMutation"];
  createRunMutation: TestOfficerDataState["createRunMutation"];
}

export function TestOfficerInputContext({
  manifest,
  onboardingDraft,
  onboardingPreview,
  requestDraft,
  selectedExecutor,
  setSelectedExecutor,
  headless,
  setHeadless,
  traceEnabled,
  setTraceEnabled,
  videoEnabled,
  setVideoEnabled,
  setDraftOverrides,
  updateRuntimeDraft,
  summary,
  missionPreviewMutation,
  createRunMutation
}: TestOfficerInputContextProps) {
  return (
            <section className="story-card">
              <div className="story-card__header">
                <strong>Input Context</strong>
                <span className="tag">{manifest.mission.mode}</span>
              </div>
              <div className="form-stack test-officer-intake-form">
                <label>
                  <span>Project name</span>
                  <input
                    value={onboardingDraft.projectName}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, projectName: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Target app</span>
                  <input
                    value={onboardingDraft.targetAppName}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, targetAppName: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Base URL</span>
                  <input
                    value={onboardingDraft.baseUrl}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, baseUrl: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Business objective</span>
                  <textarea
                    rows={4}
                    value={onboardingDraft.businessObjective}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, businessObjective: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Test account ref</span>
                  <input
                    value={onboardingDraft.accountRef}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, accountRef: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Auth strategy</span>
                  <select
                    value={onboardingDraft.authStrategy ?? "session"}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        authStrategy: event.target.value as NonNullable<TestOfficerOnboardingDraft["authStrategy"]>
                      }))
                    }
                  >
                    <option value="none">none</option>
                    <option value="basic">basic</option>
                    <option value="session">session</option>
                    <option value="oauth">oauth</option>
                    <option value="custom">custom</option>
                  </select>
                </label>
                <label>
                  <span>Login path</span>
                  <input
                    value={onboardingDraft.loginPagePath ?? ""}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, loginPagePath: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Environment</span>
                  <input
                    value={(onboardingDraft.environments ?? []).join(", ")}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        environments: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>Start command</span>
                  <input
                    value={onboardingDraft.runtime?.start?.command ?? ""}
                    placeholder="pnpm"
                    onChange={(event) =>
                      updateRuntimeDraft({
                        start: {
                          ...(onboardingDraft.runtime?.start ?? {}),
                          command: event.target.value,
                          args: onboardingDraft.runtime?.start?.args ?? []
                        }
                      })
                    }
                  />
                </label>
                <label>
                  <span>Start args</span>
                  <input
                    value={(onboardingDraft.runtime?.start?.args ?? []).join(" ")}
                    placeholder="preview --host 127.0.0.1"
                    onChange={(event) =>
                      updateRuntimeDraft({
                        start: {
                          ...(onboardingDraft.runtime?.start ?? { command: "" }),
                          args: splitCommandArgs(event.target.value)
                        }
                      })
                    }
                  />
                </label>
                <label>
                  <span>Health URL</span>
                  <input
                    value={onboardingDraft.runtime?.healthCheck?.url ?? ""}
                    placeholder={`${onboardingDraft.baseUrl.replace(/\/+$/, "")}/healthz`}
                    onChange={(event) =>
                      updateRuntimeDraft({
                        healthCheck: {
                          ...(onboardingDraft.runtime?.healthCheck ?? {}),
                          url: event.target.value,
                          expectedStatus: onboardingDraft.runtime?.healthCheck?.expectedStatus ?? [200]
                        }
                      })
                    }
                  />
                </label>
                <label>
                  <span>Cleanup command</span>
                  <input
                    value={onboardingDraft.runtime?.cleanup?.command ?? ""}
                    placeholder="pnpm"
                    onChange={(event) =>
                      updateRuntimeDraft({
                        cleanup: {
                          ...(onboardingDraft.runtime?.cleanup ?? {}),
                          command: event.target.value,
                          args: onboardingDraft.runtime?.cleanup?.args ?? []
                        }
                      })
                    }
                  />
                </label>
                <label>
                  <span>Cleanup args</span>
                  <input
                    value={(onboardingDraft.runtime?.cleanup?.args ?? []).join(" ")}
                    placeholder="run test:cleanup"
                    onChange={(event) =>
                      updateRuntimeDraft({
                        cleanup: {
                          ...(onboardingDraft.runtime?.cleanup ?? { command: "" }),
                          args: splitCommandArgs(event.target.value)
                        }
                      })
                    }
                  />
                </label>
                <label>
                  <span>Workspace root</span>
                  <input
                    value={onboardingDraft.workspaceRoot ?? ""}
                    placeholder="/workspace/customer-portal"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, workspaceRoot: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>PR URL</span>
                  <input
                    value={onboardingDraft.prUrl ?? ""}
                    placeholder="https://github.com/org/repo/pull/42"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, prUrl: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Requirement docs</span>
                  <input
                    value={(onboardingDraft.requirementDocs ?? []).join(", ")}
                    placeholder="docs/requirements/login.md"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        requirementDocs: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>Bug tickets</span>
                  <input
                    value={(onboardingDraft.bugTickets ?? []).join(", ")}
                    placeholder="docs/bugs/BUG-123.md"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        bugTickets: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>API docs</span>
                  <input
                    value={(onboardingDraft.apiDocs ?? []).join(", ")}
                    placeholder="docs/openapi.json"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        apiDocs: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>Git diff paths</span>
                  <input
                    value={(onboardingDraft.gitDiffs ?? []).join(", ")}
                    placeholder="patches/pr-42.diff"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        gitDiffs: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>GitHub issues</span>
                  <input
                    value={(onboardingDraft.githubIssues ?? []).join(", ")}
                    placeholder="https://github.com/org/repo/issues/123"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        githubIssues: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>Jira issues</span>
                  <input
                    value={(onboardingDraft.jiraIssues ?? []).join(", ")}
                    placeholder="https://company.atlassian.net/browse/QA-123"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        jiraIssues: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>OpenAPI URLs</span>
                  <input
                    value={(onboardingDraft.openApiUrls ?? []).join(", ")}
                    placeholder="https://api.example.test/openapi.json"
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        openApiUrls: splitList(event.target.value)
                      }))
                    }
                  />
                </label>
                <label>
                  <span>Requirement text</span>
                  <textarea
                    rows={3}
                    value={onboardingDraft.requirementText ?? ""}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({ ...current, requirementText: event.target.value }))
                    }
                  />
                </label>
                <label>
                  <span>Mission mode</span>
                  <select
                    value={onboardingDraft.mode}
                    onChange={(event) =>
                      setDraftOverrides((current) => ({
                        ...current,
                        mode: event.target.value as TestOfficerOnboardingDraft["mode"]
                      }))
                    }
                  >
                    <option value="scripted">scripted</option>
                    <option value="plan-assisted">plan-assisted</option>
                    <option value="ai-exploratory">ai-exploratory</option>
                  </select>
                </label>
                <label>
                  <span>Executor</span>
                  <select
                    value={selectedExecutor}
                    onChange={(event) =>
                      setSelectedExecutor(event.target.value as "memory" | "playwright")
                    }
                  >
                    <option value="memory">memory</option>
                    <option value="playwright">playwright</option>
                  </select>
                </label>
                <label>
                  <span>Browser mode</span>
                  <select
                    value={headless ? "headless" : "headed"}
                    onChange={(event) => setHeadless(event.target.value === "headless")}
                  >
                    <option value="headless">headless</option>
                    <option value="headed">headed</option>
                  </select>
                </label>
              </div>
              <div className="test-officer-inline-pairs">
                <button
                  className={`ghost-button ${traceEnabled ? "ghost-button--active" : ""}`}
                  type="button"
                  onClick={() => setTraceEnabled((current) => !current)}
                >
                  trace {traceEnabled ? "on" : "off"}
                </button>
                <button
                  className={`ghost-button ${videoEnabled ? "ghost-button--active" : ""}`}
                  type="button"
                  onClick={() => setVideoEnabled((current) => !current)}
                >
                  video {videoEnabled ? "on" : "off"}
                </button>
              </div>
              <dl className="detail-list">
                <Detail label="Project" value={manifest.project.name} />
                <Detail label="Target" value={manifest.targetApp.name} />
                <Detail label="Base URL" value={manifest.targetApp.baseUrl} mono />
                <Detail label="Preview" value={`${onboardingPreview.enabledScenarioCount} scenarios · ${onboardingPreview.pageCount} pages`} />
                <Detail label="Selector Coverage" value={`${onboardingPreview.selectorCoverage}%`} />
                <Detail label="Executor" value={selectedExecutor} />
                {summary?.registrySummary ? (
                  <Detail
                    label="Run Registry"
                    value={[
                      summary.registrySummary.selectors ? "selectors" : null,
                      summary.registrySummary.fixtures ? "fixtures" : null,
                      summary.registrySummary.onboarding ? "onboarding" : null,
                      summary.registrySummary.missionPackage ? "mission-package" : null,
                      `${summary.registrySummary.scenarios} scenarios`,
                      `${summary.registrySummary.oracles} oracles`,
                      `${summary.registrySummary.artifacts} artifacts`
                    ].filter(Boolean).join(" · ")}
                  />
                ) : null}
                {manifest.run.metadata?.executionConfig ? (
                  <Detail
                    label="Last Run Config"
                    value={[
                      manifest.run.metadata.executionConfig.executor ?? "memory",
                      manifest.run.metadata.executionConfig.headless === false ? "headed" : "headless",
                      `trace ${manifest.run.metadata.executionConfig.trace ? "on" : "off"}`,
                      `video ${manifest.run.metadata.executionConfig.recordVideo ? "on" : "off"}`
                    ].join(" · ")}
                  />
                ) : null}
              </dl>
              <div className="test-officer-inline-pairs">
                {onboardingPreview.scenarios.map((scenario) => (
                  <span
                    className={`tag ${scenario.enabled ? "tag--good" : "tag--warn"}`}
                    key={`${scenario.family}-${scenario.pagePath}`}
                  >
                    {scenario.label}
                  </span>
                ))}
              </div>
              <div className="button-row">
                <button
                  className="primary-button"
                  type="button"
                  disabled={missionPreviewMutation.isPending}
                  onClick={() => missionPreviewMutation.mutate(requestDraft)}
                >
                  {missionPreviewMutation.isPending ? "Validating..." : "Validate With Platform"}
                </button>
                <button
                  className="ghost-button"
                  type="button"
                  disabled={createRunMutation.isPending}
                  onClick={() =>
                    createRunMutation.mutate({
                      ...requestDraft,
                      executor: selectedExecutor,
                      headless,
                      trace: traceEnabled,
                      recordVideo: videoEnabled
                    })
                  }
                >
                  {createRunMutation.isPending ? "Creating run..." : "Create Run Bundle"}
                </button>
              </div>
              {missionPreviewMutation.isError ? (
                <p className="muted">
                  Platform preview failed: {missionPreviewMutation.error instanceof Error
                    ? missionPreviewMutation.error.message
                    : "unknown error"}
                </p>
              ) : null}
              {createRunMutation.isError ? (
                <p className="muted">
                  Run creation failed: {createRunMutation.error instanceof Error
                    ? createRunMutation.error.message
                    : "unknown error"}
                </p>
              ) : null}
              {createRunMutation.data ? (
                <div className="notice-card">
                  <strong>Run Created</strong>
                  <p className="muted">
                    {createRunMutation.data.runId} · executor {createRunMutation.data.executor} · {createRunMutation.data.headless ? "headless" : "headed"} · review {createRunMutation.data.reviewStatus}
                  </p>
                  <p className="mono">
                    trace {createRunMutation.data.trace ? "on" : "off"} · video {createRunMutation.data.recordVideo ? "on" : "off"}
                  </p>
                  {createRunMutation.data.gate ? (
                    <>
                      <p className="mono">
                        gate exit {createRunMutation.data.gate.exitCode} · {createRunMutation.data.gate.passed ? "passed" : "failed"}
                        {createRunMutation.data.gate.reasons.length
                          ? ` · ${createRunMutation.data.gate.reasons.join(", ")}`
                          : ""}
                      </p>
                      {createRunMutation.data.gate.diagnostics?.newArtifactSignals?.length ||
                      createRunMutation.data.gate.diagnostics?.newFindings?.length ? (
                        <ul className="flat-list">
                          {(createRunMutation.data.gate.diagnostics.newFindings ?? []).slice(0, 2).map((finding) => (
                            <li key={`finding-${finding}`}>
                              <strong>Gate finding</strong> · {finding}
                            </li>
                          ))}
                          {(createRunMutation.data.gate.diagnostics.newArtifactSignals ?? []).slice(0, 2).map((signal) => (
                            <li key={`artifact-${signal}`}>
                              <strong>Gate artifact signal</strong> · {signal}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </>
                  ) : null}
                </div>
              ) : null}
            </section>
  );
}
