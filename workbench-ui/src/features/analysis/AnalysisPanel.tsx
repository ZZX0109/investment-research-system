import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "../governance/runStatus";
import { SelectedRunDossierCard } from "../dossier/SelectedRunDossierCard";
import { useAnalysisWorkspace } from "./useAnalysisWorkspace";

export function AnalysisPanel() {
  const workspace = useAnalysisWorkspace();
  const replaySummary = workspace.replaySummary;
  const dossier = workspace.dossier;
  const failureMessage = formatQueryFailure(
    workspace.triggerError ?? workspace.reportError ?? workspace.replayError ?? workspace.dossierError,
    "Unable to load the selected analysis run."
  );
  const missingSourceMetadata = replaySummary
    ? hasMissingSourceMetadata({ mode: replaySummary.mode, provider: replaySummary.provider, as_of: replaySummary.as_of })
    : false;
  const staleSource = replaySummary ? isStaleAsOf(replaySummary.as_of) : false;

  return (
    <Panel
      eyebrow="Analysis"
      title="Run, Judge, Fixed Report"
      actions={
        workspace.canTriggerAnalysis ? (
          <button
            className="primary-button"
            type="button"
            onClick={() => void workspace.triggerAnalysis()}
          >
            {workspace.isTriggeringAnalysis ? "Running..." : "Trigger Analysis"}
          </button>
        ) : null
      }
    >
      {workspace.selectedAssetId && !workspace.selectedRunId && !workspace.hasRuns ? (
        <InlineNotice
          title="No Analysis Run Yet"
          body="This asset exists, but no immutable analysis run has been generated yet. Trigger one first so reports, evidence scope, and Judge output all bind to a reproducible snapshot."
        />
      ) : replaySummary && dossier ? (
        <>
          {missingSourceMetadata ? (
            <InlineNotice
              title="Source Metadata Missing"
              tone="block"
              body="The run loaded, but its mode/provider/as-of metadata is incomplete. Do not trust the conclusion until the run is regenerated."
            />
          ) : null}
          {staleSource ? (
            <InlineNotice
              title="Data Is Stale"
              tone="warn"
              body="Source data is older than the freshness policy allows. The UI keeps the run visible for replay, but recommends triggering a new analysis before action."
            />
          ) : null}
          <article className="story-card">
            <div className="story-card__header">
              <strong>{replaySummary.asset_ticker} run</strong>
              <SourceBadge
                provenance={{
                  data_mode: replaySummary.data_mode as "demo" | "sandbox" | "real",
                  source_type: replaySummary.source_type as "real" | "synthetic" | "backfilled" | "manual_override",
                  source_name: replaySummary.source_name,
                  observed_at: replaySummary.observed_at,
                  confidence: replaySummary.confidence
                }}
              />
            </div>
            <p className="muted">
              Frozen run bundle with immutable report output and judge-scoped recommendation.
            </p>
            <ul className="flat-list">
              <li>Mode: {replaySummary.mode}</li>
              <li>Provider: {replaySummary.provider}</li>
              <li>As of: {replaySummary.as_of ?? "n/a"}</li>
              <li>Overrides: {replaySummary.overrides.join(", ") || "None"}</li>
            </ul>
            <div className="metric-strip">
              <div className="metric-card">
                <div className="eyebrow">Judge</div>
                <div className="metric-card__value">{dossier.judgeVerdict}</div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">Confidence</div>
                <div className="metric-card__value">{Math.round(dossier.confidence * 100)}%</div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">Risk Probability</div>
                <div className="metric-card__value">
                  {dossier.riskProbability == null ? "n/a" : `${Math.round(dossier.riskProbability * 100)}%`}
                </div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">Synthetic Share</div>
                <div className="metric-card__value">{Math.round(dossier.syntheticShare * 100)}%</div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">Feature Coverage</div>
                <div className="metric-card__value">{Math.round(dossier.featureCoverage * 100)}%</div>
              </div>
            </div>
          </article>
          <SelectedRunDossierCard dossier={dossier} />
          <article className="story-card">
            <div className="story-card__header">
              <strong>Observation stance</strong>
              <span className="tag">{dossier.recommendationAction}</span>
            </div>
            <p>{dossier.recommendationReasoning}</p>
            {dossier.recommendationGuardrails.length > 0 ? (
              <ul className="flat-list">
                {dossier.recommendationGuardrails.map((guardrail) => <li key={guardrail}>{guardrail}</li>)}
              </ul>
            ) : null}
          </article>
          <article className="story-card">
            <div className="story-card__header">
              <strong>Risk Conclusion</strong>
              <span className="tag">{dossier.riskLevel}</span>
            </div>
            <p>{dossier.riskSummary}</p>
            {dossier.riskStaleAfter ? (
              <p className="muted">Refresh before {dossier.riskStaleAfter}.</p>
            ) : null}
          </article>
          <article className="story-card">
            <div className="story-card__header">
              <strong>Judge Gates</strong>
            </div>
            <ul className="flat-list">
              {(dossier.gatingReasons.length > 0 ? dossier.gatingReasons : ["No gating reasons"]).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </article>
          {(dossier.priceFreshnessStatus !== "fresh" ||
            dossier.evidenceFreshnessStatus !== "fresh" ||
            dossier.staleReasons.length > 0) ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>Freshness & Refresh</strong>
                <span className="tag">{dossier.refreshRecommendation}</span>
              </div>
              <ul className="flat-list">
                <li>Price freshness: {dossier.priceFreshnessStatus}</li>
                <li>Evidence freshness: {dossier.evidenceFreshnessStatus}</li>
              </ul>
              {dossier.staleReasons.length > 0 ? (
                <ul className="flat-list">
                  {dossier.staleReasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              ) : null}
            </article>
          ) : null}
          {dossier.fallbackReasons.length > 0 ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>Fallback Reasons</strong>
                <span className="tag">{dossier.fallbackCount}</span>
              </div>
              <ul className="flat-list">
                {dossier.fallbackReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </article>
          ) : null}
          <div className="button-row">
            <button
              className="ghost-button"
              type="button"
              onClick={() => void workspace.generateReport()}
              disabled={!workspace.canGenerateReport}
            >
              {workspace.isGeneratingReport ? "Generating..." : "Generate Report From Run"}
            </button>
          </div>
          {dossier.reportBodyMarkdown ? (
            <article className="report-preview">
              <div className="story-card__header">
                <strong>{dossier.reportTitle}</strong>
                <span className="tag">{dossier.reportVersion}</span>
              </div>
              <pre>{dossier.reportBodyMarkdown}</pre>
            </article>
          ) : null}
        </>
      ) : (
        <div>
          <p className="muted">Pick an asset and trigger an analysis run to inspect the fixed bundle and generated report.</p>
          {workspace.selectedRunId ? <p className="muted">{failureMessage}</p> : null}
        </div>
      )}
    </Panel>
  );
}
