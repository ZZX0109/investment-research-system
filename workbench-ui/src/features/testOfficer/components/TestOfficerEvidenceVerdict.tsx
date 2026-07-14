import type { TestOfficerCredentialKind, TestOfficerManifest } from "../../../api/types";
import { toneForRunStatus, type TestOfficerStepInspection as TestOfficerStepInspectionModel, type TestOfficerSummary } from "../model";
import type { TestOfficerDataState, TestOfficerUiState } from "../useTestOfficerWorkspace";
import { Detail } from "./primitives";

interface TestOfficerEvidenceVerdictProps {
  manifest: TestOfficerManifest;
  summary?: TestOfficerSummary;
  auditRunsQuery: TestOfficerDataState["auditRunsQuery"];
  auditRunDetailQuery: TestOfficerDataState["auditRunDetailQuery"];
  latestAuditGate?: NonNullable<TestOfficerDataState["auditRunDetailQuery"]["data"]>["gateResults"][number];
  topAuditAttribution?: NonNullable<TestOfficerDataState["auditRunDetailQuery"]["data"]>["failureAttributions"][number];
  topAuditSignals: string[];
  topAuditArtifactSignals: string[];
  credentialsQuery: TestOfficerDataState["credentialsQuery"];
  credentialDraft: TestOfficerUiState["credentialDraft"];
  setCredentialDraft: TestOfficerUiState["setCredentialDraft"];
  upsertCredentialMutation: TestOfficerDataState["upsertCredentialMutation"];
  inspection?: TestOfficerStepInspectionModel;
}

export function TestOfficerEvidenceVerdict({
  manifest,
  summary,
  auditRunsQuery,
  auditRunDetailQuery,
  latestAuditGate,
  topAuditAttribution,
  topAuditSignals,
  topAuditArtifactSignals,
  credentialsQuery,
  credentialDraft,
  setCredentialDraft,
  upsertCredentialMutation,
  inspection
}: TestOfficerEvidenceVerdictProps) {
  return (
            <section className="story-card">
              <div className="story-card__header">
                <strong>Evidence & Verdict</strong>
                <span className={`tag tag--${toneForRunStatus(manifest.judgeReport?.result ?? "unknown")}`}>
                  {manifest.judgeReport?.result ?? "unknown"}
                </span>
              </div>
              {manifest.judgeReport ? (
                <dl className="detail-list">
                  <Detail label="Judge" value={manifest.judgeReport.metadata?.source ?? "deterministic_judge"} />
                  <Detail label="LLM" value={manifest.judgeReport.metadata?.llmStatus ?? "not_configured"} />
                  <Detail label="Policy" value={manifest.judgeReport.metadata?.policyVersion ?? "judge-policy"} mono />
                  <Detail label="Confidence" value={`${Math.round(manifest.judgeReport.machineSummary.confidence * 100)}%`} />
                </dl>
              ) : null}
              <p className="muted">{manifest.judgeReport?.narrative ?? "Judge report is not available."}</p>
              {summary?.failureAttributionSummary.entries.length ? (
                <div className="notice-card">
                  <strong>Most Likely Causes</strong>
                  <ul className="flat-list">
                    {summary.failureAttributionSummary.entries.slice(0, 3).map((attribution) => (
                      <li key={attribution.id}>
                        <strong>#{attribution.rank} {Math.round(attribution.confidence * 100)}%</strong> · {attribution.likelyCause}
                        {attribution.signalSummary.length ? ` · ${attribution.signalSummary.join(" · ")}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {manifest.run.bundle.artifactAccess ? (
                <div className="notice-card">
                  <strong>Trust Boundary</strong>
                  <p className="muted">
                    Artifact access requires {manifest.run.bundle.artifactAccess.header}; development fallback is loopback-only.
                  </p>
                  <ul className="flat-list">
                    <li>Agent API calls require a Test Officer token outside seeded demo mode.</li>
                    <li>Artifacts and reports are redacted before persistence.</li>
                    <li>Machine evidence is separated from judge conclusions.</li>
                    <li>LLM status is explicit; deterministic fallback is visible.</li>
                    {manifest.run.bundle.artifactAccess.signedUrlTtlSeconds ? (
                      <li>Signed artifact URLs expire after {manifest.run.bundle.artifactAccess.signedUrlTtlSeconds} seconds.</li>
                    ) : null}
                    {manifest.run.bundle.artifactAccess.runTokenScope ? (
                      <li>Run-scoped downloads use {manifest.run.bundle.artifactAccess.runTokenHeader} for {manifest.run.bundle.artifactAccess.runTokenScope}.</li>
                    ) : null}
                  </ul>
                  <div className="credential-vault">
                    <div className="story-card__header">
                      <strong>Audit Index</strong>
                      <span className="tag">{auditRunsQuery.data?.length ?? 0} runs</span>
                    </div>
                    {auditRunsQuery.isError ? (
                      <p className="muted">
                        Audit index unavailable: {auditRunsQuery.error instanceof Error
                          ? auditRunsQuery.error.message
                          : "unknown error"}
                      </p>
                    ) : null}
                    {auditRunDetailQuery.data ? (
                      <>
                        <dl className="detail-list">
                          <Detail
                            label="Current Run Audit"
                            value={[
                              `${auditRunDetailQuery.data.sourceContexts.length} sources`,
                              `${auditRunDetailQuery.data.failureAttributions.length} attributions`,
                              `${auditRunDetailQuery.data.artifacts.length} artifacts`,
                              `${auditRunDetailQuery.data.gateResults.length} gate decisions`,
                              `${auditRunDetailQuery.data.runtimeLifecycle.length} runtime phases`
                            ].join(" · ")}
                          />
                          {latestAuditGate ? (
                            <Detail
                              label="Latest Gate"
                              value={[
                                latestAuditGate.passed ? "passed" : "failed",
                                `exit ${latestAuditGate.exitCode}`,
                                latestAuditGate.reasons.slice(0, 2).join(", ")
                              ].filter(Boolean).join(" · ")}
                            />
                          ) : null}
                          {topAuditAttribution ? (
                            <Detail
                              label="Top Failure Attribution"
                              value={[
                                `#${topAuditAttribution.rank}`,
                                topAuditAttribution.category,
                                `${Math.round(topAuditAttribution.confidence * 100)}% confidence`
                              ].join(" · ")}
                            />
                          ) : null}
                        </dl>
                        {topAuditAttribution || topAuditArtifactSignals.length > 0 ? (
                          <ul className="flat-list">
                            {topAuditAttribution ? (
                              <li>
                                <strong>Likely cause</strong> · {topAuditAttribution.likelyCause ?? "not classified yet"}
                              </li>
                            ) : null}
                            {topAuditAttribution?.recommendation ? (
                              <li>
                                <strong>Recommendation</strong> · {topAuditAttribution.recommendation}
                              </li>
                            ) : null}
                            {topAuditSignals.map((signal) => (
                              <li key={signal}>
                                <strong>Signal</strong> · {signal}
                              </li>
                            ))}
                            {topAuditArtifactSignals.map((signal) => (
                              <li key={signal}>
                                <strong>Artifact signal</strong> · {signal}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </>
                    ) : auditRunDetailQuery.isError ? (
                      <p className="muted">
                        Current run audit detail unavailable: {auditRunDetailQuery.error instanceof Error
                          ? auditRunDetailQuery.error.message
                          : "unknown error"}
                      </p>
                    ) : null}
                    <ul className="flat-list">
                      {(auditRunsQuery.data ?? []).slice(0, 3).map((run) => (
                        <li key={run.runId}>
                          <span className="mono">{run.runId}</span> · {run.projectId} · {run.status}/{run.reviewStatus}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="credential-vault">
                    <div className="story-card__header">
                      <strong>API Key Vault</strong>
                      <span className="tag">{credentialsQuery.data?.length ?? 0} stored</span>
                    </div>
                    {credentialsQuery.isError ? (
                      <p className="muted">
                        Vault unavailable: {credentialsQuery.error instanceof Error
                          ? credentialsQuery.error.message
                          : "unknown error"}
                      </p>
                    ) : null}
                    <ul className="flat-list">
                      {(credentialsQuery.data ?? []).slice(0, 4).map((credential) => (
                        <li key={credential.id}>
                          <span className="mono">{credential.id}</span> · {credential.kind} · {credential.secretPreview}
                        </li>
                      ))}
                    </ul>
                    <div className="credential-vault__form">
                      <label>
                        <span>ID</span>
                        <input
                          value={credentialDraft.id}
                          onChange={(event) =>
                            setCredentialDraft((current) => ({ ...current, id: event.target.value }))
                          }
                        />
                      </label>
                      <label>
                        <span>Label</span>
                        <input
                          value={credentialDraft.label}
                          onChange={(event) =>
                            setCredentialDraft((current) => ({ ...current, label: event.target.value }))
                          }
                        />
                      </label>
                      <label>
                        <span>Kind</span>
                        <select
                          value={credentialDraft.kind}
                          onChange={(event) =>
                            setCredentialDraft((current) => ({
                              ...current,
                              kind: event.target.value as TestOfficerCredentialKind
                            }))
                          }
                        >
                          <option value="api-key">api-key</option>
                          <option value="connector-token">connector-token</option>
                          <option value="test-account">test-account</option>
                          <option value="custom">custom</option>
                        </select>
                      </label>
                      <label>
                        <span>Provider</span>
                        <input
                          value={credentialDraft.provider}
                          onChange={(event) =>
                            setCredentialDraft((current) => ({ ...current, provider: event.target.value }))
                          }
                        />
                      </label>
                      <label className="credential-vault__secret">
                        <span>Secret</span>
                        <input
                          type="password"
                          value={credentialDraft.secret}
                          onChange={(event) =>
                            setCredentialDraft((current) => ({ ...current, secret: event.target.value }))
                          }
                        />
                      </label>
                      <button
                        className="ghost-button"
                        type="button"
                        disabled={upsertCredentialMutation.isPending || credentialDraft.secret.length === 0}
                        onClick={() =>
                          upsertCredentialMutation.mutate(
                            {
                              id: credentialDraft.id,
                              label: credentialDraft.label,
                              kind: credentialDraft.kind,
                              secret: credentialDraft.secret,
                              metadata: { provider: credentialDraft.provider }
                            },
                            {
                              onSuccess: () =>
                                setCredentialDraft((current) => ({ ...current, secret: "" }))
                            }
                          )
                        }
                      >
                        {upsertCredentialMutation.isPending ? "Saving..." : "Save key"}
                      </button>
                    </div>
                    {upsertCredentialMutation.isError ? (
                      <p className="muted">
                        Save failed: {upsertCredentialMutation.error instanceof Error
                          ? upsertCredentialMutation.error.message
                          : "unknown error"}
                      </p>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {inspection?.reportLinks.length ? (
                <div className="button-row">
                  {inspection.reportLinks.map((link) => (
                    <a className="ghost-button" href={link.href} key={link.label} rel="noreferrer" target="_blank">
                      {link.label}
                    </a>
                  ))}
                </div>
              ) : null}
            </section>
  );
}
