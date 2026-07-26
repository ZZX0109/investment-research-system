import type { SelectedRunDossier } from "./model";
import { useI18n } from "../../i18n";

type SelectedRunDossierCardProps = {
  dossier: SelectedRunDossier;
  showMetrics?: boolean;
};

export function SelectedRunDossierCard({
  dossier,
  showMetrics = false
}: SelectedRunDossierCardProps) {
  const { l, term } = useI18n();
  return (
    <article className="story-card story-card--focused" data-testid="selected-run-dossier">
      <div className="story-card__header">
        <strong>{l("所选运行档案", "Selected Run Dossier")}</strong>
        <span className="tag">{dossier.reportVersion}</span>
      </div>
      <p className="muted">{term(dossier.reportTitle)}</p>
      {showMetrics ? (
        <div className="metric-strip">
          <div className="metric-card">
            <div className="eyebrow">{l("评审", "Judge")}</div>
            <div className="metric-card__value">{term(dossier.judgeVerdict)}</div>
          </div>
          <div className="metric-card">
            <div className="eyebrow">{l("门禁", "Gates")}</div>
            <div className="metric-card__value">{dossier.gateCount}</div>
          </div>
          <div className="metric-card">
            <div className="eyebrow">{l("降级", "Fallbacks")}</div>
            <div className="metric-card__value">{dossier.fallbackCount}</div>
          </div>
          <div className="metric-card">
            <div className="eyebrow">{l("观察立场", "Action")}</div>
            <div className="metric-card__value">{term(dossier.recommendationAction)}</div>
          </div>
        </div>
      ) : null}
      <p>{term(dossier.reportThesis)}</p>
      <p className="muted">{term(dossier.recommendationReasoning)}</p>
      <ul className="flat-list">
        <li>{l("来源模式", "Source mode")}: {term(dossier.mode)}</li>
        <li>{l("数据源", "Provider")}: {dossier.provider}</li>
        <li>{l("数据截至", "As of")}: {dossier.asOf ?? l("暂无", "n/a")}</li>
        <li>{l("覆盖设置", "Overrides")}: {dossier.overrides.map(term).join(", ") || l("无", "None")}</li>
        <li>{l("合成数据占比", "Synthetic ratio")}: {Math.round(dossier.syntheticRatio * 100)}%</li>
        <li>{l("价格新鲜度", "Price freshness")}: {term(dossier.priceFreshnessStatus)}</li>
        <li>{l("证据新鲜度", "Evidence freshness")}: {term(dossier.evidenceFreshnessStatus)}</li>
        <li>{l("刷新建议", "Refresh recommendation")}: {term(dossier.refreshRecommendation)}</li>
      </ul>
      <div className="story-card__header">
        <strong>{l("模型证据", "Model Evidence")}</strong>
        <span className="tag">{term(dossier.modelStatus)}</span>
      </div>
      <ul className="flat-list">
        <li>{l("模型", "Model")}: {dossier.modelName}@{dossier.modelVersion}</li>
        <li>{l("已批准", "Approved")}: {dossier.deploymentApproved ? l("是", "yes") : l("否", "no")}</li>
        <li>
          {l("风险概率", "Risk probability")}:{" "}
          {dossier.riskProbability == null ? l("暂无", "n/a") : `${Math.round(dossier.riskProbability * 100)}%`}
        </li>
        <li>{l("特征覆盖率", "Feature coverage")}: {Math.round(dossier.featureCoverage * 100)}%</li>
        <li>{l("缺失特征", "Missing features")}: {dossier.missingFeatures.join(", ") || l("无", "None")}</li>
        {dossier.modelDiagnostic ? <li>{l("运行漂移", "Runtime drift")}: {Math.round(dossier.modelDiagnostic.drift_score * 100)}%; {l("数据源缺失率", "provider missing")}: {Math.round(dossier.modelDiagnostic.provider_missing_rate * 100)}%</li> : null}
        {dossier.modelDiagnostic?.out_of_range_features.length ? <li>{l("超出范围的特征", "Out-of-range features")}: {dossier.modelDiagnostic.out_of_range_features.join(", ")}</li> : null}
      </ul>
      {dossier.inferenceWarnings.length > 0 ? (
        <ul className="flat-list">
          {dossier.inferenceWarnings.map((warning) => (
            <li key={warning}>{term(warning)}</li>
          ))}
        </ul>
      ) : null}
      {dossier.staleReasons.length > 0 ? (
        <ul className="flat-list">
          {dossier.staleReasons.map((reason) => (
            <li key={reason}>{term(reason)}</li>
          ))}
        </ul>
      ) : null}
      {dossier.evidenceCitationIds.length > 0 ? (
        <p className="muted mono">{l("证据引用", "Citations")}: {dossier.evidenceCitationIds.join(", ")}</p>
      ) : null}
    </article>
  );
}
