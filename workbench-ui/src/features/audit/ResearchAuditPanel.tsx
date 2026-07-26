import { RefreshCw, ShieldCheck } from "lucide-react";
import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import {
  useCreateResearchAuditMutation,
  useRefreshAssetMutation,
  useResearchCardQuery
} from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function ResearchAuditPanel() {
  const { l, term } = useI18n();
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const mode = useWorkbenchStore((state) => state.mode);
  const card = useResearchCardQuery(assetId);
  const refresh = useRefreshAssetMutation();
  const audit = useCreateResearchAuditMutation();
  const result = card.data?.audit;

  return (
    <Panel
      eyebrow={l("研究审计", "Research Audit")}
      title={l("证据与决策门禁", "Evidence & Decision Gate")}
      actions={
        <div className="button-row">
          <button
            className="icon-button"
            type="button"
            title={l("刷新研究数据", "Refresh real data")}
            disabled={!assetId || refresh.isPending}
            onClick={() => assetId && refresh.mutate({ assetId })}
          >
            <RefreshCw size={16} aria-hidden="true" />
            <span>{refresh.isPending ? l("刷新中", "Refreshing") : l("刷新", "Refresh")}</span>
          </button>
          <button
            className="icon-button icon-button--primary"
            type="button"
            title={l("执行研究审计", "Run research audit")}
            disabled={!(["research", "real"].includes(mode)) || !selectedRunId || audit.isPending}
            onClick={() => selectedRunId && audit.mutate(selectedRunId)}
          >
            <ShieldCheck size={16} aria-hidden="true" />
            <span>{audit.isPending ? l("审计中", "Auditing") : l("执行审计", "Audit")}</span>
          </button>
        </div>
      }
    >
      {refresh.data ? (
        <InlineNotice
          tone={refresh.data.refresh_run.state === "succeeded" ? "info" : "warn"}
          title={l(`刷新${term(refresh.data.refresh_run.state)}`, `Refresh ${refresh.data.refresh_run.state}`)}
          body={l(`${refresh.data.refresh_run.price_count} 条价格记录，${refresh.data.refresh_run.evidence_count} 条证据${refresh.data.refresh_run.cache_hit ? "；使用带时间戳的真实缓存" : ""}。`, `${refresh.data.refresh_run.price_count} price rows, ${refresh.data.refresh_run.evidence_count} evidence items${refresh.data.refresh_run.cache_hit ? "; timestamped real cache used" : ""}.`)}
        />
      ) : null}
      {result ? (
        <>
          <div className="metric-strip">
            <Metric label={l("结论", "Verdict")} value={term(result.verdict)} tone={result.verdict} />
            <Metric label={l("评分", "Score")} value={`${Math.round(result.score * 100)}%`} />
            <Metric label={l("证据预算", "Evidence budget")} value={`${result.evidence_budget}`} />
            <Metric label={l("文本量估计", "Token estimate")} value={`${result.token_estimate}`} />
          </div>
          <div className="audit-checks">
            {result.checks.map((check) => (
              <div className="audit-check" key={check.name}>
                <span className={`status-dot status-dot--${check.passed ? "pass" : check.severity}`} />
                <div>
                  <strong>{auditCheckTitle(check.name, l, term)}</strong>
                  <div className="muted">{auditCheckReason(check.name, check.reason, l)}</div>
                </div>
              </div>
            ))}
          </div>
          <article className="research-note">
            <strong>{l("反方观点", "Contrary view")}</strong>
            <p>{card.data?.contrary_view}</p>
          </article>
        </>
      ) : (
        <p className="muted">{l("请选择已分析的研究对象，以查看证据与审计门禁。", "Select an analyzed asset to inspect its evidence and audit gate.")}</p>
      )}
    </Panel>
  );
}

function auditCheckTitle(name: string, l: (zh: string, en: string) => string, term: (value: string) => string) {
  const titles: Record<string, [string, string]> = {
    model_approved: ["模型是否通过正式审批", "Formal model approval"],
    feature_coverage: ["特征数据是否足够完整", "Feature coverage"],
    evidence_present: ["是否有足够证据记录", "Evidence records"],
    pit_timestamps: ["历史数据时间是否可证明", "Point-in-time timestamps"],
    authority_mix: ["数据源是否满足正式要求", "Authorized data sources"],
    freshness: ["行情和证据是否足够新", "Data freshness"],
  };
  const pair = titles[name];
  return pair ? l(...pair) : term(name);
}

function auditCheckReason(name: string, reason: string, l: (zh: string, en: string) => string) {
  const reasons: Record<string, [string, string]> = {
    model_approved: ["研究模式只展示研究模型；正式部署模型尚未批准。", "Research mode only has research models; no formal deployment model is approved."],
    feature_coverage: ["部分可选特征或事件数据缺失，因此结果可能不完整。", "Optional features or event data are missing, so the result may be incomplete."],
    evidence_present: ["当前运行没有足够的证据记录支持正式结论。", "This run does not have enough evidence records for a formal conclusion."],
    pit_timestamps: ["免费历史回补无法完整证明当时可见时间，只能用于研究。", "Free historical backfills do not fully prove historical visibility and are research-only."],
    authority_mix: ["当前数据源没有满足正式授权和 SLA 要求。", "The current data sources do not meet formal authorization and SLA requirements."],
    freshness: ["行情或证据的新鲜度不满足正式门禁，需要重新刷新。", "Market or evidence freshness does not meet the formal gate; refresh is required."],
  };
  return reasons[name] ? l(...reasons[name]) : reason;
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric-card">
      <div className="eyebrow">{label}</div>
      <div className={`metric-card__value ${tone ? `metric-card__value--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
