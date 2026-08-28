import { AlertTriangle, ArrowRight, BarChart3, CheckCircle2, Clock3, GitCompareArrows, Search, ShieldCheck, WalletCards } from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Panel } from "./Panel";
import { useI18n } from "../i18n";
import {
  useResearchDiscoveryQuery,
  usePortfolioRiskQuery,
  useReportsQuery,
  useReportSchedulesQuery,
  useResearchCompareQuery,
} from "../hooks/useWorkbenchQueries";
import type {
  Asset,
  AssetSnapshot,
  ResearchAcceptanceReport,
  ResearchLifecycleStatus,
  ResearchModelRoster,
  ResearchShadowSummary,
  ResearchDiscoverySymbol,
} from "../api/types";
import type { ResearchWorkspaceSection } from "./ResearchControlCenter";

type Props = {
  section: ResearchWorkspaceSection;
  assets: Asset[];
  selectedAsset: Asset | null;
  snapshot: AssetSnapshot | null;
  acceptance: ResearchAcceptanceReport | null;
  lifecycle: ResearchLifecycleStatus | null;
  rosters: ResearchModelRoster[];
  shadow: ResearchShadowSummary | null;
  onOpenDiscoveredAsset: (candidate: ResearchDiscoverySymbol) => void;
};

export function ResearchModulePanels(props: Props) {
  switch (props.section) {
    case "today": return <TodayPanel {...props} />;
    case "discover": return <DiscoverPanel onOpenDiscoveredAsset={props.onOpenDiscoveredAsset} />;
    case "compare": return <ComparePanel assets={props.assets} selectedAsset={props.selectedAsset} />;
    case "portfolio": return <PortfolioPanel />;
    case "research": return <ResearchRoomPanel {...props} />;
    case "alerts": return <AlertsPanel lifecycle={props.lifecycle} />;
    default: return null;
  }
}

function TodayPanel({ snapshot, acceptance, lifecycle, shadow, selectedAsset }: Props) {
  const { l } = useI18n();
  const blockers = unique([
    ...(acceptance?.blocking_reasons ?? []),
    ...(lifecycle?.blocking_reasons ?? []),
    ...(snapshot?.long_term_blocking_reasons ?? []),
  ]);
  return <section className="research-control-page">
    <Panel eyebrow={l("今日研究", "Today")} title={l("先看变化，再决定下一步研究", "See what changed before choosing the next research step")}>
      <div className="research-module-hero">
        <div><strong>{selectedAsset ? `${selectedAsset.ticker} · ${selectedAsset.name}` : l("尚未选择标的", "No subject selected")}</strong><span>{snapshot?.data_as_of ? `${l("快照截止", "Snapshot cutoff")} ${snapshot.data_as_of.slice(0, 10)}` : l("等待同源快照", "Waiting for shared snapshot")}</span></div>
        <span className="research-module-badge"><ShieldCheck size={14} />{l("研究观察", "Research observation")}</span>
      </div>
      <div className="research-module-grid">
        <ActionCard icon={<Search size={17} />} title={l("发现候选", "Discover candidates")} detail={l("从完整研究池筛选，再进入公司页。", "Filter the research universe before opening a company.")} />
        <ActionCard icon={<GitCompareArrows size={17} />} title={l("验证对比", "Validate with peers")} detail={l("只比较同一截止日、可追溯的评分卡。", "Compare only traceable scorecards with one cutoff.")} />
        <ActionCard icon={<BarChart3 size={17} />} title={l("检查长期模型", "Check long-term models")} detail={shadow ? `${shadow.valid_session_count}/60 ${l("Shadow 有效日", "valid Shadow days")} · ${l("真实预测日", "dates with real predictions")} ${shadow.real_prediction_trade_date_count ?? 0} · ${l("真实预测", "real")} ${shadow.real_prediction_count ?? 0} · ${l("空预测", "empty")} ${shadow.empty_prediction_count ?? 0}` : l("Shadow 状态尚未返回", "Shadow status unavailable")} />
      </div>
      <div className="research-module-columns">
        <div><h3>{l("最新可见变化", "Latest visible changes")}</h3><ul className="research-control-page__list">
          <li><span>{l("数据更新", "Data update")}</span><strong>{lifecycle?.latest_data_update?.slice(0, 16) ?? "—"}</strong></li>
          <li><span>{l("交易日", "Trade date")}</span><strong>{lifecycle?.latest_trade_date ?? snapshot?.market_observation.trade_date ?? "—"}</strong></li>
          <li><span>{l("接受度", "Acceptance")}</span><strong>{acceptance?.status ?? "—"}</strong></li>
        </ul></div>
        <div><h3>{l("需要先处理", "Resolve before relying")}</h3>{blockers.length ? <ul className="research-control-page__list research-control-page__list--warning">{blockers.slice(0, 5).map((item) => <li key={item}><AlertTriangle size={13} />{item}</li>)}</ul> : <p className="muted">{l("没有返回阻塞项；仍需检查数据层级。", "No blockers returned; still inspect the data tier.")}</p>}</div>
      </div>
    </Panel>
  </section>;
}

function DiscoverPanel({ onOpenDiscoveredAsset }: { onOpenDiscoveredAsset: (candidate: ResearchDiscoverySymbol) => void }) {
  const { l } = useI18n();
  const [query, setQuery] = useState("");
  const [assetType, setAssetType] = useState<"all" | "equity" | "etf">("all");
  const [eligibility, setEligibility] = useState<"all" | "model" | "quote_only" | "unavailable">("all");
  const discovery = useResearchDiscoveryQuery({ query, limit: 60, assetType, eligibility });
  const rows = discovery.data?.symbols ?? [];
  const capability = (row: ResearchDiscoverySymbol) => row.model_eligible
    ? l("可进入回测/模型门禁", "Eligible for backtest/model gates")
    : row.quote_research_eligible
      ? l("仅行情研究", "Quote research only")
      : l("行情尚未入库", "No persisted price series");
  return <section className="research-control-page"><Panel eyebrow={l("发现", "Discover")} title={l("当前全市场发现：先看可用边界，再进入公司研究", "Current-market discovery: check scope before opening research")}>
    <div className="research-module-toolbar"><div className="research-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={l("搜索代码或公司名", "Search symbol or company")} /></div><span className="muted">{discovery.data?.counts.model_eligible ?? 0} / {discovery.data?.counts.current_universe ?? 0} {l("可进入免费模型范围 / 当前枚举", "free-model scope / current enumeration")}</span></div>
    <div className="research-discovery-filters" aria-label={l("发现筛选", "Discovery filters")}>
      <label>{l("类型", "Type")}<select value={assetType} onChange={(event) => setAssetType(event.target.value as typeof assetType)}><option value="all">{l("全部", "All")}</option><option value="equity">{l("股票", "Equity")}</option><option value="etf">ETF</option></select></label>
      <label>{l("研究范围", "Research scope")}<select value={eligibility} onChange={(event) => setEligibility(event.target.value as typeof eligibility)}><option value="all">{l("全部", "All")}</option><option value="model">{l("可进入模型门禁", "Model-gated")}</option><option value="quote_only">{l("仅行情研究", "Quote only")}</option><option value="unavailable">{l("行情未入库", "No price")}</option></select></label>
      <span className="muted">{l(`匹配 ${discovery.data?.counts.matched ?? 0} 个，显示前 ${discovery.data?.counts.displayed ?? 0} 个`, `${discovery.data?.counts.matched ?? 0} matched; showing ${discovery.data?.counts.displayed ?? 0}`)}</span>
    </div>
    <p className="muted research-discovery-note">{l("覆盖当前公开枚举，不代表历史成分股、退市状态或 PIT 已获证明。点击可加入工作区；页面会保留“仅行情研究”边界。", "This covers the current public enumeration, not historical membership, delist state, or proven PIT. Click to add an asset; quote-only boundaries stay visible.")}</p>
    {discovery.data?.blocking_reasons?.length ? <Notice text={discovery.data.blocking_reasons.join(" · ")} /> : null}
    <div className="research-universe-table research-universe-table--discovery"><div className="research-universe-table__head"><span>{l("标的", "Subject")}</span><span>{l("类型", "Type")}</span><span>{l("数据范围", "Data scope")}</span><span>{l("可用性", "Eligibility")}</span><span /></div>{rows.map((row) => <button type="button" className="research-universe-table__row" key={row.symbol} onClick={() => onOpenDiscoveredAsset(row)}><span><strong>{row.symbol}</strong><small>{row.name}</small></span><span>{row.exchange} · {row.asset_type}</span><span>{row.scope === "raw_quote_only" ? l("原始行情", "Raw quote") : l("原始 + 前复权", "Raw + adjusted")}</span><span><small>{capability(row)}</small></span><ArrowRight size={15} /></button>)}</div>
    {discovery.isLoading ? <p className="muted">{l("正在读取当前公开枚举…", "Reading current public enumeration…")}</p> : null}
    {!rows.length && !discovery.isLoading ? <p className="muted">{l("没有匹配的当前标的，或公开枚举暂不可用。", "No current subjects match, or the public enumeration is unavailable.")}</p> : null}
  </Panel></section>;
}

function ComparePanel({ assets, selectedAsset }: { assets: Asset[]; selectedAsset: Asset | null }) {
  const { l } = useI18n();
  const symbols = useMemo(() => [selectedAsset?.ticker, ...assets.map((asset) => asset.ticker)].filter((value, index, array): value is string => Boolean(value) && array.indexOf(value) === index).slice(0, 4), [assets, selectedAsset]);
  const comparison = useResearchCompareQuery(symbols);
  return <section className="research-control-page"><Panel eyebrow={l("对比", "Compare")} title={l("同日评分卡对比", "Same-cutoff scorecard comparison")}>
    <div className="research-module-toolbar"><span className="muted">{symbols.join(" · ") || l("至少选择两个标的", "Select at least two subjects")}</span>{comparison.data?.as_of ? <span className="research-cutoff"><Clock3 size={13} />{comparison.data.as_of}</span> : null}</div>
    {comparison.data?.cohort_status === "incomplete" ? <Notice text={comparison.data.blocking_reasons.join(" · ")} /> : null}
    {comparison.data?.symbols?.length ? <div className="research-compare-grid"><div className="research-compare-grid__head"><span>{l("标的", "Subject")}</span><span>{l("综合", "Composite")}</span><span>{l("质量", "Quality")}</span><span>{l("成长稳定", "Growth")}</span><span>{l("长期风险", "Risk")}</span><span>{l("状态", "Status")}</span></div>{comparison.data.symbols.map((row) => { const card = row.scorecard; return <div className="research-compare-grid__row" key={row.symbol}><strong>{row.symbol}</strong><span>{formatNumber(card?.composite_score)}</span><span>{formatNumber(card?.long_term_quality)}</span><span>{formatNumber(card?.growth_stability)}</span><span>{formatNumber(card?.long_term_risk)}</span><Status value={row.status} /></div>; })}</div> : <EmptyState text={l("当前没有足够的同日评分卡可比较；系统会保留缺口，不生成伪排名。", "There are not enough same-cutoff scorecards; gaps are preserved and no ranking is fabricated.")} />}
  </Panel></section>;
}

function PortfolioPanel() {
  const { l } = useI18n();
  const risk = usePortfolioRiskQuery();
  const value = risk.data;
  return <section className="research-control-page"><Panel eyebrow={l("组合", "Portfolio")} title={l("组合级风险观察", "Portfolio-level risk observation")}>
    {!value ? <EmptyState text={risk.isLoading ? l("正在读取组合风险…", "Reading portfolio risk…") : l("组合风险快照尚未形成；不会用单标的推断组合风险。", "No portfolio risk snapshot yet; single-name data is not used as a portfolio proxy.")} /> : <><div className="research-data-grid"><Metric label={l("总市值", "Market value")} value={formatNumber(value.total_market_value)} /><Metric label={l("集中度 HHI", "Concentration HHI")} value={formatNumber(value.concentration_hhi)} /><Metric label={l("20 日波动", "20d volatility")} value={formatNumber(value.volatility_20d)} /><Metric label={l("最大回撤", "Max drawdown")} value={formatNumber(value.max_drawdown)} /><Metric label={l("行业数", "Industries")} value={String(Object.keys(value.industry_exposure).length)} /><Metric label={l("风险贡献", "Risk contributions")} value={String(Object.keys(value.position_risk_contributions).length)} /></div><div className="research-module-columns"><div><h3>{l("压力情景", "Stress scenarios")}</h3><KeyValues values={value.stress_scenarios} /></div><div><h3>{l("组合警告", "Warnings")}</h3>{value.warnings.length ? <ul className="research-control-page__list research-control-page__list--warning">{value.warnings.map((item) => <li key={item}><AlertTriangle size={13} />{item}</li>)}</ul> : <p className="muted">{l("没有返回警告。", "No warnings returned.")}</p>}</div></div></>}
  </Panel></section>;
}

function ResearchRoomPanel({ acceptance, rosters, selectedAsset }: Props) {
  const { l } = useI18n();
  const taskEntries = Object.entries(acceptance?.tasks ?? {});
  const reports = useReportsQuery(selectedAsset?.id ?? null);
  return <section className="research-control-page"><Panel eyebrow={l("研究室", "Research room")} title={l("模型、证据和可复核产物", "Models, evidence and reviewable artifacts")}>
    <div className="research-module-grid"><ActionCard icon={<BarChart3 size={17} />} title={l("任务契约", "Task contract")} detail={l("120/240 日超额收益 + 120/240 日未来最大回撤。", "120/240d excess return + 120/240d future max drawdown.")} /><ActionCard icon={<ShieldCheck size={17} />} title={l("模型 roster", "Model roster")} detail={`${rosters.length} ${l("个已读取；hash 与 PIT 边界保留。", "loaded; hashes and PIT boundary retained.")}`} /><ActionCard icon={<WalletCards size={17} />} title={l("研究结论", "Research conclusion")} detail={l("结论必须带支持证据、反方证据、缺口和失效条件。", "Every conclusion carries support, contrary evidence, gaps and invalidation conditions.")} /></div>
    <div className="research-module-columns"><div><h3>{l("任务状态", "Task status")}</h3>{taskEntries.length ? <ul className="research-control-page__list">{taskEntries.map(([task, value]) => <li key={task}><span>{task}</span><Status value={typeof value === "object" && value ? String(value.status ?? "unknown") : "unknown"} /></li>)}</ul> : <EmptyState text={l("接受度报告尚未返回任务状态。", "Acceptance report has no task status yet.")} />}</div><div><h3>{l("报告与产物", "Reports and artifacts")}</h3>{reports.data?.length ? <ul className="research-control-page__list">{reports.data.slice(0, 4).map((report) => <li key={report.id}><span>{report.title}<small>{report.updated_at.slice(0, 10)} · {report.report_version}</small></span><Status value={report.status} /></li>)}</ul> : <EmptyState text={reports.isLoading ? l("正在读取报告…", "Reading reports…") : l("当前标的尚无研究报告。", "No research report for this subject yet.")} />}</div><div><h3>{l("产物边界", "Artifact boundary")}</h3><ul className="research-control-page__list"><li><CheckCircle2 size={13} /><span>{l("报告、预测、特征和模型均保留 hash", "Reports, predictions, features and models retain hashes")}</span></li><li><CheckCircle2 size={13} /><span>{l("未达到门槛的模型保持 research_only", "Models below threshold remain research_only")}</span></li><li><AlertTriangle size={13} /><span>{l("指标缺失不会被当作 0", "Missing metrics are not treated as zero")}</span></li></ul></div></div>
  </Panel></section>;
}

function AlertsPanel({ lifecycle }: { lifecycle: ResearchLifecycleStatus | null }) {
  const { l } = useI18n();
  const schedules = useReportSchedulesQuery();
  const jobs = lifecycle?.jobs ?? [];
  return <section className="research-control-page"><Panel eyebrow={l("提醒", "Alerts")} title={l("可验证的事件、数据和任务状态", "Verifiable events, data changes and job states")}>
    <div className="research-module-grid"><Metric label={l("报告计划", "Report schedules")} value={String(schedules.data?.length ?? 0)} /><Metric label={l("研究任务", "Research jobs")} value={String(jobs.length)} /><Metric label={l("下次训练", "Next training")} value={lifecycle?.next_training?.slice(0, 16) ?? "—"} /></div>
    <div className="research-module-columns"><div><h3>{l("报告计划", "Report schedules")}</h3>{schedules.data?.length ? <ul className="research-control-page__list">{schedules.data.map((schedule) => <li key={schedule.id}><span>{schedule.frequency} · {schedule.timezone}</span><Status value={schedule.enabled ? "enabled" : "disabled"} /></li>)}</ul> : <EmptyState text={l("尚无报告计划。", "No report schedules yet.")} />}</div><div><h3>{l("最近任务", "Recent jobs")}</h3>{jobs.length ? <ul className="research-control-page__list">{jobs.slice(0, 6).map((job) => <li key={job.id}><span>{job.job_type}</span><Status value={job.state} /></li>)}</ul> : <EmptyState text={l("尚无研究任务记录。", "No research jobs recorded yet.")} />}</div></div>
  </Panel></section>;
}

function ActionCard({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) { return <div className="research-action-card"><span>{icon}</span><strong>{title}</strong><p>{detail}</p></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="research-data-card research-data-card--muted"><span>{label}</span><strong>{value}</strong></div>; }
function KeyValues({ values }: { values: Record<string, number> }) { const entries = Object.entries(values); return entries.length ? <ul className="research-control-page__list">{entries.slice(0, 8).map(([key, value]) => <li key={key}><span>{key}</span><strong>{formatNumber(value)}</strong></li>)}</ul> : <p className="muted">—</p>; }
function Status({ value }: { value: string }) { const good = ["available", "complete", "passed", "succeeded", "enabled", "research_only"].includes(value); return <span className={`trust-status-chip trust-status-chip--${good ? "good" : "warn"}`}>{value}</span>; }
function Notice({ text }: { text: string }) { return <div className="research-module-notice"><AlertTriangle size={14} />{text}</div>; }
function EmptyState({ text }: { text: string }) { return <p className="research-module-empty">{text}</p>; }
function formatNumber(value: number | null | undefined) { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—"; }
function unique(values: string[]) { return Array.from(new Set(values.filter(Boolean))); }
