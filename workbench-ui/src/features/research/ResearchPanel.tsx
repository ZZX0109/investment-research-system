import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import { SelectedRunDossierCard } from "../dossier/SelectedRunDossierCard";
import { useResearchWorkspace } from "./useResearchWorkspace";
import { useDeploymentStatusQuery, useDirectionalForecastQuery, useMarketObservationQuery, useRefreshMarketObservationMutation, useResearchForecastQuery } from "../../hooks/useWorkbenchQueries";

export function ResearchPanel() {
  const workspace = useResearchWorkspace();
  const deployment = useDeploymentStatusQuery();
  const trustedCard = deployment.data?.trusted_risk_gate;
  const publicExperiment = deployment.data?.public_experiment;
  const marketObservation = useMarketObservationQuery(workspace.assetId);
  const outcome = marketObservation.data?.outcomes.find((item) => item.run_id === workspace.selectedRunId) ?? marketObservation.data?.outcomes[0];
  const direction = useDirectionalForecastQuery(workspace.selectedRunId);
  const forecast = useResearchForecastQuery(workspace.selectedRunId);
  const refreshObservation = useRefreshMarketObservationMutation(workspace.assetId);

  return (
    <Panel eyebrow="Research" title="Evidence, Price Layers, Reports">
      {workspace.assetId ? (
        <>
          <div className="metric-strip">
            <div className="metric-card">
              <div className="eyebrow">Latest Close</div>
              <div className="metric-card__value">{workspace.latestCloseLabel}</div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">Evidence</div>
              <div className="metric-card__value">
                {workspace.evidenceCount} / {workspace.totalEvidenceCount}
              </div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">Runs / Reports</div>
              <div className="metric-card__value">
                {workspace.runCount} / {workspace.filteredReportsCount}
              </div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">Configured Providers</div>
              <div className="metric-card__value">{workspace.providerNamesLabel}</div>
            </div>
          </div>
          {trustedCard ? (
            <article className="story-card" data-testid="trusted-risk-gate-card">
              <div className="story-card__header">
                <strong>Trusted Risk Gate</strong>
                <span className="tag">{String(trustedCard.framework_version ?? "v1")}</span>
              </div>
              <p className="muted">
                PIT data, structured events, regime approval, Judge degradation, and frozen run replay govern this research signal.
              </p>
            </article>
          ) : null}
          {publicExperiment ? (
            <article className="story-card" data-testid="public-experiment-summary">
              <div className="story-card__header">
                <strong>Experiment Provenance</strong>
                <span className="tag">{String(publicExperiment.schema_version ?? "unavailable")}</span>
              </div>
              <p className="muted">
                Training run {String((publicExperiment.identity as Record<string, unknown> | undefined)?.training_run_id ?? "n/a")};
                &nbsp; markets: {Array.isArray(publicExperiment.included_markets) ? publicExperiment.included_markets.join(", ") : "n/a"}.
              </p>
            </article>
          ) : null}
          {marketObservation.data ? (
            <article className="story-card" data-testid="market-observation-panel">
              <div className="story-card__header"><strong>Approved Risk vs Real Price</strong><span className="tag">{marketObservation.data.market_status}</span></div>
              <div className="metric-strip">
                <div className="metric-card"><div className="eyebrow">Risk Forecast</div><div className="metric-card__value">{outcome?.predicted_risk == null ? "n/a" : `${Math.round(outcome.predicted_risk * 100)}%`}</div></div>
                <div className="metric-card"><div className="eyebrow">Predicted At</div><div className="metric-card__value">{outcome?.prediction_price?.toFixed(2) ?? "n/a"}</div></div>
                <div className="metric-card"><div className="eyebrow">Latest Real</div><div className="metric-card__value">{marketObservation.data.latest_price?.toFixed(2) ?? "n/a"}</div></div>
                <div className="metric-card"><div className="eyebrow">Return</div><div className="metric-card__value">{outcome?.cumulative_return == null ? "n/a" : `${(outcome.cumulative_return * 100).toFixed(2)}%`}</div></div>
              </div>
              <p className="muted">Delayed provider: {marketObservation.data.provider}. {marketObservation.data.market_status === "closed" || marketObservation.data.market_status === "holiday" ? "Market is not open; latest displayed value is the most recent authoritative value." : "Quote refreshes no more than once every five minutes during the session."}</p>
              <p className="muted">Provider status: {marketObservation.data.provider_status}; last success: {marketObservation.data.last_success_at ?? "none"}; consecutive failures: {marketObservation.data.consecutive_failures}.</p>
              {outcome ? <p className="muted">Outcome: {outcome.outcome}; observed {outcome.observed_trading_days}/60 trading days; classification: {outcome.error_category ?? "pending"}; Judge: {outcome.judge_verdict ?? "n/a"}; realized drawdown: {outcome.realized_max_drawdown == null ? "pending" : `${(outcome.realized_max_drawdown * 100).toFixed(2)}%`}.</p> : <InlineNotice title="No Prediction Observation" body="Generate a real analysis run before comparing its risk forecast with real prices." />}
              {marketObservation.data.degraded_reasons.length ? <InlineNotice title="Market Data Degraded" tone="warn" body={marketObservation.data.degraded_reasons.join(", ")} /> : null}
              <div className="button-row"><button className="ghost-button" type="button" disabled={refreshObservation.isPending} onClick={() => refreshObservation.mutate()}>{refreshObservation.isPending ? "Refreshing..." : "Refresh delayed quote"}</button></div>
            </article>
          ) : null}
          {workspace.selectedRunId ? (
            <article className="story-card" data-testid="trusted-close-research">
              <div className="story-card__header"><strong>{forecast.data?.decision_context === "pre_open" ? "Trusted Pre-open Research" : "Trusted Close Research"}</strong><span className="tag">{forecast.data?.data_status.quality_status ?? "checking"}</span></div>
              {forecast.data ? <>
                <div className="metric-strip">
                  <div className="metric-card"><div className="eyebrow">Data As Of</div><div className="metric-card__value">{new Date(forecast.data.data_status.as_of).toLocaleString()}</div></div>
                  <div className="metric-card"><div className="eyebrow">Data Coverage</div><div className="metric-card__value">{Math.round(forecast.data.data_status.coverage_ratio * 100)}%</div></div>
                  <div className="metric-card"><div className="eyebrow">Evidence Coverage</div><div className="metric-card__value">{Math.round(forecast.data.evidence_coverage * 100)}%</div></div>
                  <div className="metric-card"><div className="eyebrow">20D &gt;8% Drawdown</div><div className="metric-card__value">{forecast.data.drawdown_20d ? `${Math.round(forecast.data.drawdown_20d.threshold_probability * 100)}%` : "abstain"}</div></div>
                </div>
                <p className="muted">{forecast.data.decision_context === "pre_open" ? "Next-session pre-open" : "Confirmed-close"} research only; this is not an intraday trading signal. Decision time: {forecast.data.decision_time ? new Date(forecast.data.decision_time).toLocaleString() : "unavailable"}; source time: {forecast.data.data_status.latest_source_time ? new Date(forecast.data.data_status.latest_source_time).toLocaleString() : "unavailable"}; delay: {forecast.data.data_status.latency_seconds == null ? "n/a" : `${Math.round(forecast.data.data_status.latency_seconds)}s`}; cache: {forecast.data.data_status.cache_state}; providers: {forecast.data.data_status.provider_chain.join(" → ") || "unavailable"}.</p>
                {forecast.data.direction_5d ? <p>5-day direction: up {Math.round(forecast.data.direction_5d.up * 100)}%, down {Math.round(forecast.data.direction_5d.down * 100)}%, flat {Math.round(forecast.data.direction_5d.flat * 100)}%.</p> : <p className="muted">1/5-day direction and 20-day return distributions remain hidden until their independent manifests are approved.</p>}
                {forecast.data.gating_reasons.length ? <InlineNotice title="Research Gates" tone="warn" body={forecast.data.gating_reasons.join("; ")} /> : null}
              </> : <p className="muted">No frozen trusted-close forecast is available for this historical run.</p>}
            </article>
          ) : null}
          {workspace.selectedRunId ? (
            <article className="story-card" data-testid="directional-research-status">
              <div className="story-card__header"><strong>Research-only Direction Signal</strong><span className="tag">{direction.data?.status ?? "checking"}</span></div>
              {direction.data?.status === "approved" && direction.data.forecast ? <p>{direction.data.forecast.direction} at {Math.round(direction.data.forecast.confidence * 100)}% confidence.</p> : <p className="muted">Direction model is still under independent walk-forward and regime validation. It does not affect the approved drawdown-risk gate.</p>}
            </article>
          ) : null}
          {workspace.priceChart.length ? (
            <div className="chart-frame" aria-label="Asset cumulative return and drawdown chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={workspace.priceChart} margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" minTickGap={28} />
                  <YAxis unit="%" width={52} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(2)}%`]} />
                  <Legend />
                  <Line type="monotone" dataKey="returnPct" name="Cumulative return" stroke="#2c6e62" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="drawdownPct" name="Drawdown" stroke="#a85c35" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <InlineNotice title="Price Series Unavailable" tone="warn" body="No timestamped real price series is available for charting." />
          )}
          {workspace.selectedRunId ? (
            <div className="button-row">
              <button
                data-testid="toggle-run-scoped-research"
                className="ghost-button"
                type="button"
                onClick={workspace.toggleRunScopedResearch}
              >
                {workspace.onlySelectedRunResearch ? "Show All Asset Research" : "Scope Research To Selected Run"}
              </button>
            </div>
          ) : null}
          {workspace.assetId && !workspace.hasRuns ? (
            <InlineNotice
              title="No Historical Run"
              body="Research data can be browsed, but reports and evidence scope become replayable only after an immutable analysis run is generated."
            />
          ) : null}
          {workspace.hasQueryFailure ? (
            <InlineNotice
              title="Research Data Failed To Load"
              tone="block"
              body={workspace.failureMessage}
            />
          ) : null}
          {workspace.selectedRunMissingSource ? (
            <InlineNotice
              title="Selected Run Source Missing"
              tone="block"
              body="This selected run is missing mode, provider, or as-of metadata. Keep it visible for audit, but regenerate before using the report."
            />
          ) : null}
          {workspace.selectedRunStaleSource ? (
            <InlineNotice
              title="Selected Run Source Is Stale"
              tone="warn"
              body="The selected report remains fixed to its original run, but its source timestamp is outside the freshness window."
            />
          ) : null}
          {workspace.dossier ? <SelectedRunDossierCard dossier={workspace.dossier} showMetrics /> : null}
          <div className="stack-list">
            {workspace.evidenceView.focusedEvidence ? (
              <article className="story-card story-card--focused">
                <div className="story-card__header">
                  <strong>Focused From Run Lineage</strong>
                  <button className="ghost-button" type="button" onClick={workspace.clearFocusedEvidence}>
                    Clear Focus
                  </button>
                </div>
                <p className="muted">
                  Reviewing the evidence currently linked from the selected run timeline entry.
                </p>
              </article>
            ) : null}
            {workspace.onlySelectedRunResearch && workspace.selectedRunId ? (
              <article className="story-card">
                <div className="story-card__header">
                  <strong>Run-Scoped Research</strong>
                  <span className="tag">
                    {workspace.runScopeSummary?.evidence_count ?? 0} evidence / {workspace.runScopeSummary?.report_count ?? 0} reports
                  </span>
                </div>
                <p className="muted">
                  Evidence and reports are filtered to the immutable set captured on the selected analysis run.
                </p>
              </article>
            ) : null}
            {workspace.evidenceView.orderedEvidence.map((entry) => (
              <article
                className={`story-card ${workspace.selectedEvidenceId === entry.id ? "story-card--focused" : ""}`}
                key={entry.id}
              >
                <div className="story-card__header">
                  <strong>{entry.title}</strong>
                  <SourceBadge provenance={entry.provenance} />
                </div>
                <p>{entry.summary}</p>
              </article>
            ))}
            {workspace.onlySelectedRunResearch && workspace.evidenceView.orderedEvidence.length === 0 ? (
              <p className="muted">The selected run has no persisted evidence linked yet.</p>
            ) : null}
          </div>
          <div className="stack-list">
            {workspace.filteredReports.map((report) => (
              <article
                className={`story-card ${workspace.selectedRunId && report.analysis_run_id === workspace.selectedRunId ? "story-card--focused" : ""}`}
                key={report.id}
              >
                <div className="story-card__header">
                  <strong>{report.title}</strong>
                  <span className="tag">{report.report_version}</span>
                </div>
                <p>{report.thesis}</p>
              </article>
            ))}
            {workspace.onlySelectedRunResearch && workspace.filteredReports.length === 0 ? (
              <p className="muted">The selected run has no generated reports yet.</p>
            ) : null}
          </div>
        </>
      ) : (
        <p className="muted">Select an asset to inspect evidence, price layering, and generated reports.</p>
      )}
    </Panel>
  );
}
