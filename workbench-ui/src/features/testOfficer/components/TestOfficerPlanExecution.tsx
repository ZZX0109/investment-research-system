import type { TestOfficerManifest } from "../../../api/types";
import { toneForRunStatus, type TestOfficerRunTimeline, type TestOfficerSummary, type TestOfficerTimelineDebugContext } from "../model";
import type { TestOfficerDataState } from "../useTestOfficerWorkspace";
import { Detail } from "./primitives";

interface TestOfficerPlanExecutionProps {
  manifest: TestOfficerManifest;
  summary?: TestOfficerSummary;
  debugContext: TestOfficerTimelineDebugContext;
  timeline?: TestOfficerRunTimeline;
  selectTimelineNode: (nodeKey: string, relatedStepId?: string) => void;
  clearDebugContext: (tokenId: "node" | "check" | "artifact" | "all") => void;
  onboardingProtocolQuery: TestOfficerDataState["onboardingProtocolQuery"];
  missionPackageQuery: TestOfficerDataState["missionPackageQuery"];
  registryManifestQuery: TestOfficerDataState["registryManifestQuery"];
  platformPreview: TestOfficerDataState["missionPreviewMutation"]["data"];
}

export function TestOfficerPlanExecution({
  manifest,
  summary,
  debugContext,
  timeline,
  selectTimelineNode,
  clearDebugContext,
  onboardingProtocolQuery,
  missionPackageQuery,
  registryManifestQuery,
  platformPreview
}: TestOfficerPlanExecutionProps) {
  return (
            <section className="story-card">
              <div className="story-card__header">
                <strong>Plan & Execution</strong>
                <span className={`tag tag--${toneForRunStatus(manifest.run.status)}`}>{manifest.run.status}</span>
              </div>
              {debugContext.active ? (
                <div className="test-officer-filter-bar">
                  <strong>Debug Context</strong>
                  <div className="test-officer-filter-bar__tokens">
                    {debugContext.tokens.map((token) => (
                      <span className="tag test-officer-filter-token" key={token.id}>
                        <span>{token.label}: {token.value}</span>
                        <button
                          aria-label={`Clear ${token.label} context`}
                          className="test-officer-filter-token__clear"
                          type="button"
                          onClick={() => clearDebugContext(token.id as "node" | "check" | "artifact")}
                        >
                          x
                        </button>
                      </span>
                    ))}
                  </div>
                  <button
                    className="ghost-button"
                    type="button"
                    onClick={() => clearDebugContext("all")}
                  >
                    Clear context
                  </button>
                </div>
              ) : null}
              <div className="step-list">
                {timeline?.sections.map((section) => (
                  <div key={section.id}>
                    <div className="story-card__header">
                      <strong>{section.label}</strong>
                      <span className="tag">{section.items.length}</span>
                    </div>
                    {section.items.map((item) => (
                      <button
                        className={[
                          "step-button",
                          item.selected ? "step-button--active" : "",
                          item.emphasis === "highlighted" ? "step-button--highlighted" : "",
                          item.emphasis === "dimmed" ? "step-button--dimmed" : ""
                        ].filter(Boolean).join(" ")}
                        key={item.id}
                        type="button"
                        onClick={() => selectTimelineNode(item.nodeKey, item.relatedStepId)}
                      >
                        <span>{item.title}</span>
                        <span className={`tag tag--${toneForRunStatus(item.status)}`}>{item.status}</span>
                      </button>
                    ))}
                    <ul className="flat-list">
                      {section.items.map((item) => (
                        <li key={`${item.id}-detail`}>
                          <strong>{item.title}</strong>
                          {item.meta ? ` · ${item.meta}` : ""}
                          {item.detail ? ` · ${item.detail}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
              {summary?.comparisonDelta ? (
                <p className="muted">
                  Delta: {summary.comparisonDelta.findings} findings, {summary.comparisonDelta.failedSteps} failed steps.
                </p>
              ) : null}
              {manifest.run.bundle.registry ? (
                <div className="notice-card">
                  <strong>Registry Bundle</strong>
                  <p className="mono">
                    {manifest.run.bundle.registry.resourceManifestPath}
                  </p>
                  {summary?.registrySummary?.onboardingSummary ? (
                    <dl className="detail-list">
                      <Detail
                        label="Onboarding"
                        value={`${summary.registrySummary.onboardingSummary.pageCount} pages · ${summary.registrySummary.onboardingSummary.selectorHintCount} selector hints · ${summary.registrySummary.onboardingSummary.scenarioRequestCount} scenario requests`}
                      />
                      <Detail
                        label="Auth Context"
                        value={[
                          summary.registrySummary.onboardingSummary.authStrategy,
                          summary.registrySummary.onboardingSummary.accountRef ?? "no account ref"
                        ].join(" · ")}
                        mono
                      />
                      <Detail
                        label="Key Pages"
                        value={summary.registrySummary.onboardingSummary.pagePaths.join(" · ")}
                        mono
                      />
                    </dl>
                  ) : onboardingProtocolQuery.isLoading ? (
                    <p className="muted">Loading onboarding protocol...</p>
                  ) : null}
                  {summary?.registrySummary?.missionPackageSummary ? (
                    <dl className="detail-list">
                      <Detail
                        label="Generated Mission"
                        value={`${summary.registrySummary.missionPackageSummary.scenarioCount} scenarios · ${summary.registrySummary.missionPackageSummary.oracleCount} oracles · ${summary.registrySummary.missionPackageSummary.pageCount} pages`}
                      />
                      <Detail
                        label="Runtime Context"
                        value={[
                          summary.registrySummary.missionPackageSummary.authStrategy,
                          summary.registrySummary.missionPackageSummary.accountRef ?? "no credential ref"
                        ].join(" · ")}
                        mono
                      />
                    </dl>
                  ) : missionPackageQuery.isLoading ? (
                    <p className="muted">Loading generated mission package...</p>
                  ) : null}
                  {summary?.registrySummary?.entries.length ? (
                    <ul className="flat-list">
                      {summary.registrySummary.entries.map((entry) => (
                        <li key={entry.kind}>
                          <strong>{entry.kind}</strong> · {entry.recordCount} records
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">
                      {registryManifestQuery.isLoading
                        ? "Loading registry catalog..."
                        : "Registry catalog is not available for this run."}
                    </p>
                  )}
                  {summary?.registrySummary?.missionPackageSummary?.scenarioNames.length ? (
                    <ul className="flat-list">
                      {summary.registrySummary.missionPackageSummary.scenarioNames.map((scenarioName) => (
                        <li key={scenarioName}>
                          <strong>scenario</strong> · {scenarioName}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {summary ? (
                    <div className="credential-vault">
                      <div className="story-card__header">
                        <strong>Run Operating Model</strong>
                        <span className={`tag tag--${toneForRunStatus(summary.runtimeSummary.status)}`}>
                          runtime {summary.runtimeSummary.status}
                        </span>
                      </div>
                      <dl className="detail-list">
                        <Detail label="Health" value={summary.runtimeSummary.health} />
                        <Detail
                          label="Source Context"
                          value={`${summary.sourceContextSummary.ready}/${summary.sourceContextSummary.total} ready`}
                        />
                        <Detail
                          label="Source Boundary"
                          value={`${summary.sourceContextSummary.boundary.status} · ${summary.sourceContextSummary.boundary.summary}`}
                        />
                        <Detail
                          label="Source Kinds"
                          value={
                            summary.sourceContextSummary.byKind
                              .map((entry) => `${entry.kind}:${entry.count}`)
                              .join(" · ") || "none"
                          }
                          mono
                        />
                        <Detail
                          label="Sensitive Sources"
                          value={`${summary.sourceContextSummary.boundary.credentialedSources} credentialed · ${summary.sourceContextSummary.boundary.lowTrustSources} low-confidence · ${summary.sourceContextSummary.boundary.failedOrBlockedSources} failed/blocked`}
                        />
                        <Detail
                          label="Failure Signals"
                          value={`${summary.failureAttributionSummary.total} attribution records`}
                        />
                        <Detail
                          label="Retention"
                          value={`${summary.retentionSummary.total} candidates · ${summary.retentionSummary.protected} protected`}
                        />
                      </dl>
                      <div className="story-card__header">
                        <strong>Connector Trust Boundary</strong>
                        <span className={`tag tag--${summary.sourceContextSummary.boundary.tone}`}>
                          {summary.sourceContextSummary.boundary.status}
                        </span>
                      </div>
                      {summary.sourceContextSummary.boundary.warnings.length ? (
                        <ul className="flat-list">
                          {summary.sourceContextSummary.boundary.warnings.map((warning) => (
                            <li key={warning}>{warning}</li>
                          ))}
                        </ul>
                      ) : null}
                      {summary.sourceContextSummary.permissionCards.length ? (
                        <ul className="flat-list">
                          {summary.sourceContextSummary.permissionCards.map((permission) => (
                            <li key={permission.permission}>
                              <strong>{permission.permission}</strong> · {permission.count} source(s) · {permission.reasons.join(" · ")}
                              <span className="muted"> · {permission.sourceLabels.join(", ")}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {summary.sourceContextSummary.entries.length ? (
                        <ul className="flat-list">
                          {summary.sourceContextSummary.entries.slice(0, 3).map((source) => (
                            <li key={source.id}>
                              <strong>{source.kind}</strong> · {source.readState} · trust{" "}
                              {source.trust?.level ?? "unknown"}
                              {source.cache ? ` · cache ${source.cache.status}` : ""}
                              {source.retry ? ` · retry ${source.retry.attempts}/${source.retry.maxAttempts}` : ""}
                              {source.pagination ? ` · pages ${source.pagination.pagesRead}` : ""}
                              {source.rateLimit?.remaining != null ? ` · rate ${source.rateLimit.remaining} left` : ""}
                              {source.failureReason ? ` · ${source.failureReason}` : ""}
                              {source.permissionExplanations.length ? (
                                <span className="muted">
                                  {" "}
                                  · {source.permissionExplanations.map((entry) => `${entry.permission}: ${entry.reason}`).join(" · ")}
                                </span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">No connector source context was attached to this run.</p>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {platformPreview ? (
                <div className="notice-card">
                  <strong>Platform Preview</strong>
                  <p className="muted">
                    {platformPreview.mission.name} · {platformPreview.counts.scenarios} scenarios · {platformPreview.counts.oracles} oracles
                  </p>
                  <ul className="flat-list">
                    {platformPreview.scenarios.map((scenario) => (
                      <li key={scenario.id}>
                        <strong>{scenario.name}</strong> · {scenario.goal}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
  );
}
