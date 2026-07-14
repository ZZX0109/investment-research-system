import type { SelectedRunDossier } from "./model";

type SelectedRunDossierCardProps = {
  dossier: SelectedRunDossier;
  showMetrics?: boolean;
};

export function SelectedRunDossierCard({
  dossier,
  showMetrics = false
}: SelectedRunDossierCardProps) {
  return (
    <article className="story-card story-card--focused" data-testid="selected-run-dossier">
      <div className="story-card__header">
        <strong>Selected Run Dossier</strong>
        <span className="tag">{dossier.reportVersion}</span>
      </div>
      <p className="muted">{dossier.reportTitle}</p>
      {showMetrics ? (
        <div className="metric-strip">
          <div className="metric-card">
            <div className="eyebrow">Judge</div>
            <div className="metric-card__value">{dossier.judgeVerdict}</div>
          </div>
          <div className="metric-card">
            <div className="eyebrow">Gates</div>
            <div className="metric-card__value">{dossier.gateCount}</div>
          </div>
          <div className="metric-card">
            <div className="eyebrow">Fallbacks</div>
            <div className="metric-card__value">{dossier.fallbackCount}</div>
          </div>
          <div className="metric-card">
            <div className="eyebrow">Action</div>
            <div className="metric-card__value">{dossier.recommendationAction}</div>
          </div>
        </div>
      ) : null}
      <p>{dossier.reportThesis}</p>
      <p className="muted">{dossier.recommendationReasoning}</p>
      <ul className="flat-list">
        <li>Source mode: {dossier.mode}</li>
        <li>Provider: {dossier.provider}</li>
        <li>As of: {dossier.asOf ?? "n/a"}</li>
        <li>Overrides: {dossier.overrides.join(", ") || "None"}</li>
        <li>Synthetic ratio: {Math.round(dossier.syntheticRatio * 100)}%</li>
        <li>Price freshness: {dossier.priceFreshnessStatus}</li>
        <li>Evidence freshness: {dossier.evidenceFreshnessStatus}</li>
        <li>Refresh recommendation: {dossier.refreshRecommendation}</li>
      </ul>
      <div className="story-card__header">
        <strong>Model Evidence</strong>
        <span className="tag">{dossier.modelStatus}</span>
      </div>
      <ul className="flat-list">
        <li>Model: {dossier.modelName}@{dossier.modelVersion}</li>
        <li>Approved: {dossier.deploymentApproved ? "yes" : "no"}</li>
        <li>
          Risk probability:{" "}
          {dossier.riskProbability == null ? "n/a" : `${Math.round(dossier.riskProbability * 100)}%`}
        </li>
        <li>Feature coverage: {Math.round(dossier.featureCoverage * 100)}%</li>
        <li>Missing features: {dossier.missingFeatures.join(", ") || "None"}</li>
        {dossier.modelDiagnostic ? <li>Runtime drift: {Math.round(dossier.modelDiagnostic.drift_score * 100)}%; provider missing: {Math.round(dossier.modelDiagnostic.provider_missing_rate * 100)}%</li> : null}
        {dossier.modelDiagnostic?.out_of_range_features.length ? <li>Out-of-range features: {dossier.modelDiagnostic.out_of_range_features.join(", ")}</li> : null}
      </ul>
      {dossier.inferenceWarnings.length > 0 ? (
        <ul className="flat-list">
          {dossier.inferenceWarnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {dossier.staleReasons.length > 0 ? (
        <ul className="flat-list">
          {dossier.staleReasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      {dossier.evidenceCitationIds.length > 0 ? (
        <p className="muted mono">Citations: {dossier.evidenceCitationIds.join(", ")}</p>
      ) : null}
    </article>
  );
}
