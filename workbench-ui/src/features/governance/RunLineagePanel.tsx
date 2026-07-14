import { startTransition, useEffect, useState } from "react";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import {
  useAnalysisRunsQuery,
  useAuditRecordsQuery,
  useDomainCatalogQuery,
  useRunComparisonQuery,
  useRunLineageDetailSummaryQuery,
  useRunLineageQuery
} from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "./runStatus";

export function RunLineagePanel() {
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const setSelectedRunId = useWorkbenchStore((state) => state.setSelectedRunId);
  const focusRunWorkspace = useWorkbenchStore((state) => state.focusRunWorkspace);
  const setSelectedEvidenceId = useWorkbenchStore((state) => state.setSelectedEvidenceId);
  const catalogQuery = useDomainCatalogQuery();
  const runsQuery = useAnalysisRunsQuery(selectedAssetId);
  const timelineQuery = useRunLineageQuery(selectedAssetId);
  const detailSummaryQuery = useRunLineageDetailSummaryQuery(selectedRunId, selectedAssetId);
  const auditQuery = useAuditRecordsQuery();

  const runs = runsQuery.data ?? [];
  const comparisonRunId =
    selectedRunId && runs.length > 0 ? runs[runs.findIndex((run) => run.id === selectedRunId) + 1]?.id ?? null : null;
  const detailSummary = detailSummaryQuery.data;
  const timeline = timelineQuery.data;
  const providerConfig = catalogQuery.data?.analysis_provider_config;
  const providers = catalogQuery.data?.analysis_providers ?? [];
  const comparisonQuery = useRunComparisonQuery(selectedRunId, comparisonRunId, selectedAssetId);
  const comparisonSummary = comparisonQuery.data ?? null;
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const detailFailure = formatQueryFailure(detailSummaryQuery.error, "Unable to load run lineage detail.");
  const timelineFailure = formatQueryFailure(timelineQuery.error, "Unable to load run lineage timeline.");

  useEffect(() => {
    if (runs.length === 0) {
      return;
    }
    if (selectedRunId && runs.some((run) => run.id === selectedRunId)) {
      return;
    }
    startTransition(() => {
      setSelectedRunId(runs[0]?.id ?? null);
    });
  }, [runs, selectedRunId, setSelectedRunId]);

  useEffect(() => {
    if (!timeline?.entries.length) {
      setExpandedRunId(null);
      return;
    }
    if (expandedRunId && timeline.entries.some((entry) => entry.run_id === expandedRunId)) {
      return;
    }
    setExpandedRunId(timeline.entries[0]?.run_id ?? null);
  }, [timeline, expandedRunId]);

  const lineageAudit = (auditQuery.data ?? []).filter((record) => {
    if (!selectedRunId || !selectedAssetId) {
      return false;
    }
    return (
      record.target_id === selectedRunId ||
      record.details.analysis_run_id === selectedRunId ||
      record.details.asset_id === selectedAssetId
    );
  });

  return (
    <Panel eyebrow="Lineage" title="Run Lineage">
      {selectedAssetId ? (
        <article className="story-card">
          <div className="story-card__header">
            <strong>Run History</strong>
            <span className="tag">{runs.length}</span>
          </div>
          {runs.length > 0 ? (
            <div className="asset-list">
              {runs.map((run) => (
                <button
                  key={run.id}
                  data-testid={`run-history-${run.id}`}
                  className={`asset-card ${selectedRunId === run.id ? "asset-card--active" : ""}`}
                  type="button"
                  onClick={() => focusRunWorkspace(run.id)}
                >
                  <div>
                    <strong>{run.created_at.slice(0, 10)}</strong>
                    <div className="muted mono">{run.id.slice(0, 8)}</div>
                  </div>
                  <span className="tag">{run.provenance.data_mode}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted">No analysis runs yet for this asset. Trigger one to create a reproducible snapshot.</p>
          )}
        </article>
      ) : null}
      {detailSummary ? (
        <div className="stack-list">
          {hasMissingSourceMetadata(detailSummary) ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>Lineage Metadata Missing</strong>
                <span className="tag">BLOCK</span>
              </div>
              <p>The selected run is missing required source metadata. Keep the record visible for audit, but do not surface it as a trustworthy recommendation.</p>
            </article>
          ) : null}
          {isStaleAsOf(detailSummary.as_of) ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>Lineage Snapshot Is Stale</strong>
                <span className="tag">HOLD</span>
              </div>
              <p>The stored run remains replayable, but the source timestamp is older than the freshness window and should be re-analyzed.</p>
            </article>
          ) : null}
          <article className="story-card">
            <div className="story-card__header">
              <strong>1. Snapshot</strong>
              <span className="tag">{detailSummary.intake_strategy}</span>
            </div>
            <p className="muted mono">{detailSummary.input_snapshot_ref}</p>
            <ul className="flat-list">
              <li>Captured at: {detailSummary.captured_at}</li>
              <li>Mode: {detailSummary.mode}</li>
              <li>Provider: {detailSummary.provider}</li>
              <li>As of: {detailSummary.as_of ?? "n/a"}</li>
              <li>Overrides: {detailSummary.overrides.join(", ") || "None"}</li>
              <li>Data modes: {detailSummary.data_modes.join(", ") || "n/a"}</li>
              <li>Source types: {detailSummary.source_types.join(", ") || "n/a"}</li>
              <li>Latest close: {detailSummary.latest_close ?? "n/a"}</li>
            </ul>
          </article>

          <article className="story-card">
            <div className="story-card__header">
              <strong>2. Provider Stack</strong>
              <span className="tag">{providers.length} configured</span>
            </div>
            <ul className="flat-list">
              <li>Configured market provider: {providerConfig?.market_data_provider ?? "n/a"}</li>
              <li>Configured evidence provider: {providerConfig?.evidence_provider ?? "n/a"}</li>
              <li>
                Price intake: {detailSummary.price_provider_name}@{detailSummary.price_provider_version} (
                {detailSummary.price_provider_status})
              </li>
              <li>
                Evidence intake: {detailSummary.evidence_provider_name}@{detailSummary.evidence_provider_version} (
                {detailSummary.evidence_provider_status})
              </li>
            </ul>
          </article>

          <article className="story-card">
            <div className="story-card__header">
              <strong>3. Judge & Observation Stance</strong>
              <span className="tag">{detailSummary.judge_verdict}</span>
            </div>
            <ul className="flat-list">
              <li>Judge score: {Math.round(detailSummary.judge_score * 100)}%</li>
              <li>Observation stance: {detailSummary.recommendation_action}</li>
              <li>Model confidence: {Math.round(detailSummary.model_confidence * 100)}%</li>
              <li>Model: {detailSummary.model_name}@{detailSummary.model_version}</li>
              <li>Model status: {detailSummary.model_status}</li>
              <li>Approved: {detailSummary.deployment_approved ? "yes" : "no"}</li>
              <li>
                Risk probability:{" "}
                {detailSummary.risk_probability == null
                  ? "n/a"
                  : `${Math.round(detailSummary.risk_probability * 100)}%`}
              </li>
              <li>Feature coverage: {Math.round(detailSummary.feature_coverage * 100)}%</li>
            </ul>
            {detailSummary.missing_features.length > 0 ? (
              <p className="muted">Missing model features: {detailSummary.missing_features.join(", ")}</p>
            ) : null}
            {detailSummary.inference_warnings.length > 0 ? (
              <ul className="flat-list">
                {detailSummary.inference_warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <p className="muted">{detailSummary.recommendation_reasoning}</p>
          </article>

          <article className="story-card">
            <div className="story-card__header">
              <strong>4. Fallback & Report</strong>
              <span className="tag">{detailSummary.report_version}</span>
            </div>
            <ul className="flat-list">
              {(detailSummary.fallback_reasons.length > 0
                ? detailSummary.fallback_reasons
                : ["No provider fallback recorded for this run."]).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {detailSummary.report_title ? <p className="muted">Latest report: {detailSummary.report_title}</p> : null}
          </article>

          {comparisonSummary ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>5. Delta vs Prior Run</strong>
                <span className="tag">{comparisonSummary.baseline_report_version}</span>
              </div>
              <ul className="flat-list">
                <li>
                  Judge delta: {comparisonSummary.judge_score_delta >= 0 ? "+" : ""}
                  {Math.round(comparisonSummary.judge_score_delta * 100)} pts
                </li>
                <li>
                  Confidence delta: {comparisonSummary.confidence_delta >= 0 ? "+" : ""}
                  {Math.round(comparisonSummary.confidence_delta * 100)} pts
                </li>
                <li>
                  Latest close delta:{" "}
                  {comparisonSummary.latest_close_delta == null
                    ? "n/a"
                    : `${comparisonSummary.latest_close_delta >= 0 ? "+" : ""}${comparisonSummary.latest_close_delta.toFixed(2)}`}
                </li>
                <li>
                  Model version: {comparisonSummary.baseline_model_version} {"->"} {comparisonSummary.current_model_version}
                </li>
                <li>
                  Report version: {comparisonSummary.baseline_report_version} {"->"} {comparisonSummary.current_report_version}
                </li>
                <li>Report thesis changed: {comparisonSummary.thesis_changed ? "yes" : "no"}</li>
              </ul>
              {(comparisonSummary.added_gates.length > 0 ||
                comparisonSummary.removed_gates.length > 0 ||
                comparisonSummary.added_fallbacks.length > 0 ||
                comparisonSummary.removed_fallbacks.length > 0) ? (
                <ul className="flat-list">
                  {comparisonSummary.added_gates.map((reason) => (
                    <li key={`gate-add-${reason}`}>Gate added: {reason}</li>
                  ))}
                  {comparisonSummary.removed_gates.map((reason) => (
                    <li key={`gate-remove-${reason}`}>Gate removed: {reason}</li>
                  ))}
                  {comparisonSummary.added_fallbacks.map((reason) => (
                    <li key={`fallback-add-${reason}`}>Fallback added: {reason}</li>
                  ))}
                  {comparisonSummary.removed_fallbacks.map((reason) => (
                    <li key={`fallback-remove-${reason}`}>Fallback removed: {reason}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No gate or fallback drift versus the prior frozen run.</p>
              )}
            </article>
          ) : null}

          {timeline ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{comparisonSummary ? "6. Report Timeline" : "5. Report Timeline"}</strong>
                <span className="tag">{timeline.entries.length}</span>
              </div>
              <div className="stack-list">
                {timeline.entries.map((entry) => {
                  const isExpanded = expandedRunId === entry.run_id;
                  return (
                    <article className="story-card" key={entry.run_id}>
                      <button
                        className={`asset-card ${isExpanded ? "asset-card--active" : ""}`}
                        type="button"
                        onClick={() => {
                          setExpandedRunId(isExpanded ? null : entry.run_id);
                          if (!isExpanded) {
                            focusRunWorkspace(entry.run_id);
                          }
                        }}
                      >
                        <div>
                          <strong>
                            {entry.created_at.slice(0, 10)} | {entry.report_version ?? "pending"}
                          </strong>
                          <div className="muted">
                            {entry.judge_verdict ?? "n/a"} | {entry.price_provider_status}/{entry.evidence_provider_status}
                          </div>
                        </div>
                        <span className="tag">{entry.audit_actions.length} events</span>
                      </button>
                      {isExpanded ? (
                        <div className="stack-list">
                          <div className="button-row">
                            <button
                              className="ghost-button"
                              type="button"
                              onClick={() => focusRunWorkspace(entry.run_id)}
                            >
                              Open Run In Workspace
                            </button>
                          </div>
                          <p className="muted mono">{entry.input_snapshot_ref}</p>
                          <ul className="flat-list">
                            <li>Evidence count: {entry.evidence_count}</li>
                            <li>Model version: {entry.model_version ?? "n/a"}</li>
                            <li>Observation stance: {entry.recommendation_action ?? "n/a"}</li>
                            <li>
                              Data mix: synthetic {Math.round(entry.synthetic_share * 100)}% / real{" "}
                              {Math.round(entry.real_share * 100)}%
                            </li>
                            <li>Mode/provider: {entry.mode} / {entry.provider}</li>
                            <li>As of: {entry.as_of ?? "n/a"}</li>
                            <li>Report generated at: {entry.report_generated_at ?? "pending"}</li>
                          </ul>
                          {entry.report_title || entry.report_thesis ? (
                            <div>
                              <strong>{entry.report_title ?? "Report"}</strong>
                              <p className="muted">{entry.report_thesis ?? "No thesis captured."}</p>
                            </div>
                          ) : null}
                          {entry.recommendation_reasoning ? (
                            <p className="muted">{entry.recommendation_reasoning}</p>
                          ) : null}
                          {entry.evidence_items.length > 0 ? (
                            <div className="stack-list">
                              {entry.evidence_items.map((evidence) => (
                                <button
                                  className="asset-card"
                                  key={evidence.id}
                                  type="button"
                                  onClick={() => {
                                    focusRunWorkspace(entry.run_id);
                                    setSelectedEvidenceId(evidence.id);
                                  }}
                                >
                                  <div className="story-card__header">
                                    <strong>{evidence.title}</strong>
                                    <SourceBadge
                                      provenance={{
                                        data_mode: evidence.data_mode as "demo" | "sandbox" | "real",
                                        source_type: evidence.source_type as "real" | "synthetic" | "backfilled" | "manual_override",
                                        source_name: "lineage-evidence",
                                        observed_at: entry.created_at,
                                        confidence: 1
                                      }}
                                    />
                                  </div>
                                  <p>{evidence.summary}</p>
                                </button>
                              ))}
                            </div>
                          ) : null}
                          {(entry.gating_reasons.length > 0 || entry.fallback_reasons.length > 0) ? (
                            <ul className="flat-list">
                              {entry.gating_reasons.map((reason) => (
                                <li key={`gate-${entry.run_id}-${reason}`}>Gate: {reason}</li>
                              ))}
                              {entry.fallback_reasons.map((reason) => (
                                <li key={`fallback-${entry.run_id}-${reason}`}>Fallback: {reason}</li>
                              ))}
                            </ul>
                          ) : null}
                          {entry.audit_actions.length > 0 ? (
                            <p className="muted">Audit actions: {entry.audit_actions.join(", ")}</p>
                          ) : null}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            </article>
          ) : null}

          <article className="story-card">
            <div className="story-card__header">
              <strong>{timeline ? (comparisonSummary ? "7. Audit Trail" : "6. Audit Trail") : comparisonSummary ? "6. Audit Trail" : "5. Audit Trail"}</strong>
              <span className="tag">{lineageAudit.length}</span>
            </div>
            <ul className="flat-list">
              {lineageAudit.length > 0 ? (
                lineageAudit.slice(0, 5).map((record) => (
                  <li key={record.id}>
                    {record.action} [{record.provenance.data_mode}/{record.provenance.source_type}]
                  </li>
                ))
              ) : (
                <li>No lineage-specific audit events yet.</li>
              )}
            </ul>
          </article>
        </div>
      ) : (
        <div>
          <p className="muted">Load an analysis run to inspect its snapshot, provider stack, judge result, report version, and audit lineage.</p>
          {selectedRunId ? <p className="muted">{detailSummaryQuery.isError ? detailFailure : timelineQuery.isError ? timelineFailure : "No run details loaded yet."}</p> : null}
        </div>
      )}
    </Panel>
  );
}
