import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import { useI18n } from "../../i18n";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "../governance/runStatus";
import { SelectedRunDossierCard } from "../dossier/SelectedRunDossierCard";
import { useAnalysisWorkspace } from "./useAnalysisWorkspace";

export function AnalysisPanel() {
  const { l, term } = useI18n();
  const workspace = useAnalysisWorkspace();
  const replaySummary = workspace.replaySummary;
  const dossier = workspace.dossier;
  const failureMessage = formatQueryFailure(
    workspace.triggerError ?? workspace.reportError ?? workspace.replayError ?? workspace.dossierError,
    l("无法加载所选分析运行。", "Unable to load the selected analysis run.")
  );
  const missingSourceMetadata = replaySummary
    ? hasMissingSourceMetadata({ mode: replaySummary.mode, provider: replaySummary.provider, as_of: replaySummary.as_of })
    : false;
  const staleSource = replaySummary ? isStaleAsOf(replaySummary.as_of) : false;

  return (
    <Panel
      eyebrow={l("分析", "Analysis")}
      title={l("运行、评审与固定报告", "Run, Judge, Fixed Report")}
      actions={
        workspace.canTriggerAnalysis ? (
          <button
            className="primary-button"
            type="button"
            onClick={() => void workspace.triggerAnalysis()}
          >
            {workspace.isTriggeringAnalysis ? l("正在分析…", "Running...") : l("开始分析", "Trigger Analysis")}
          </button>
        ) : null
      }
    >
      {workspace.selectedAssetId && !workspace.selectedRunId && !workspace.hasRuns ? (
        <InlineNotice
          title={l("尚无分析运行", "No Analysis Run Yet")}
          body={l("该研究对象已存在，但尚未生成不可变分析运行。请先启动分析，使报告、证据范围和评审结果都绑定到可复现快照。", "This asset exists, but no immutable analysis run has been generated yet. Trigger one first so reports, evidence scope, and Judge output all bind to a reproducible snapshot.")}
        />
      ) : replaySummary && dossier ? (
        <>
          {missingSourceMetadata ? (
            <InlineNotice
              title={l("来源元数据缺失", "Source Metadata Missing")}
              tone="block"
              body={l("运行已加载，但模式、数据源或数据截至时间不完整。重新生成运行前，请勿采信结论。", "The run loaded, but its mode/provider/as-of metadata is incomplete. Do not trust the conclusion until the run is regenerated.")}
            />
          ) : null}
          {staleSource ? (
            <InlineNotice
              title={l("数据已过期", "Data Is Stale")}
              tone="warn"
              body={l("来源数据已超过新鲜度策略允许范围。系统保留该运行用于回放，但建议先重新分析。", "Source data is older than the freshness policy allows. The UI keeps the run visible for replay, but recommends triggering a new analysis before action.")}
            />
          ) : null}
          <article className="story-card">
            <div className="story-card__header">
              <strong>{replaySummary.asset_ticker} {l("分析运行", "run")}</strong>
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
              {l("冻结运行包包含不可变报告和受评审范围约束的研究结论。", "Frozen run bundle with immutable report output and judge-scoped recommendation.")}
            </p>
            <ul className="flat-list">
              <li>{l("模式", "Mode")}: {term(replaySummary.mode)}</li>
              <li>{l("数据源", "Provider")}: {replaySummary.provider}</li>
              <li>{l("数据截至", "As of")}: {replaySummary.as_of ?? l("暂无", "n/a")}</li>
              <li>{l("覆盖设置", "Overrides")}: {replaySummary.overrides.map(term).join(", ") || l("无", "None")}</li>
            </ul>
            <div className="metric-strip">
              <div className="metric-card">
                <div className="eyebrow">{l("评审", "Judge")}</div>
                <div className="metric-card__value">{term(dossier.judgeVerdict)}</div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">{l("置信度", "Confidence")}</div>
                <div className="metric-card__value">{Math.round(dossier.confidence * 100)}%</div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">{l("风险概率", "Risk Probability")}</div>
                <div className="metric-card__value">
                  {dossier.riskProbability == null ? "n/a" : `${Math.round(dossier.riskProbability * 100)}%`}
                </div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">{l("合成数据占比", "Synthetic Share")}</div>
                <div className="metric-card__value">{Math.round(dossier.syntheticShare * 100)}%</div>
              </div>
              <div className="metric-card">
                <div className="eyebrow">{l("特征覆盖率", "Feature Coverage")}</div>
                <div className="metric-card__value">{Math.round(dossier.featureCoverage * 100)}%</div>
              </div>
            </div>
          </article>
          <SelectedRunDossierCard dossier={dossier} />
          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("研究观察立场", "Observation stance")}</strong>
              <span className="tag">{term(dossier.recommendationAction)}</span>
            </div>
            <p>{term(dossier.recommendationReasoning)}</p>
            {dossier.recommendationGuardrails.length > 0 ? (
              <ul className="flat-list">
                {dossier.recommendationGuardrails.map((guardrail) => <li key={guardrail}>{term(guardrail)}</li>)}
              </ul>
            ) : null}
          </article>
          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("风险结论", "Risk Conclusion")}</strong>
              <span className="tag">{term(dossier.riskLevel)}</span>
            </div>
            <p>{term(dossier.riskSummary)}</p>
            {dossier.riskStaleAfter ? (
              <p className="muted">{l(`请在 ${dossier.riskStaleAfter} 前刷新。`, `Refresh before ${dossier.riskStaleAfter}.`)}</p>
            ) : null}
          </article>
          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("评审门禁", "Judge Gates")}</strong>
            </div>
            <ul className="flat-list">
              {(dossier.gatingReasons.length > 0 ? dossier.gatingReasons : [l("无门禁原因", "No gating reasons")]).map((reason) => (
                <li key={reason}>{term(reason)}</li>
              ))}
            </ul>
          </article>
          {(dossier.priceFreshnessStatus !== "fresh" ||
            dossier.evidenceFreshnessStatus !== "fresh" ||
            dossier.staleReasons.length > 0) ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{l("新鲜度与刷新建议", "Freshness & Refresh")}</strong>
                <span className="tag">{term(dossier.refreshRecommendation)}</span>
              </div>
              <ul className="flat-list">
                <li>{l("价格新鲜度", "Price freshness")}: {term(dossier.priceFreshnessStatus)}</li>
                <li>{l("证据新鲜度", "Evidence freshness")}: {term(dossier.evidenceFreshnessStatus)}</li>
              </ul>
              {dossier.staleReasons.length > 0 ? (
                <ul className="flat-list">
                  {dossier.staleReasons.map((reason) => (
                    <li key={reason}>{term(reason)}</li>
                  ))}
                </ul>
              ) : null}
            </article>
          ) : null}
          {dossier.fallbackReasons.length > 0 ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{l("降级原因", "Fallback Reasons")}</strong>
                <span className="tag">{dossier.fallbackCount}</span>
              </div>
              <ul className="flat-list">
                {dossier.fallbackReasons.map((reason) => (
                  <li key={reason}>{term(reason)}</li>
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
              {workspace.isGeneratingReport ? l("正在生成…", "Generating...") : l("从本次运行生成报告", "Generate Report From Run")}
            </button>
          </div>
          {dossier.reportBodyMarkdown ? (
            <article className="report-preview">
              <div className="story-card__header">
                <strong>{term(dossier.reportTitle)}</strong>
                <span className="tag">{dossier.reportVersion}</span>
              </div>
              <pre>{dossier.reportBodyMarkdown}</pre>
            </article>
          ) : null}
        </>
      ) : (
        <div>
          <p className="muted">{l("请选择研究对象并启动分析，以查看固定运行包和生成报告。", "Pick an asset and trigger an analysis run to inspect the fixed bundle and generated report.")}</p>
          {workspace.selectedRunId ? <p className="muted">{failureMessage}</p> : null}
        </div>
      )}
    </Panel>
  );
}
