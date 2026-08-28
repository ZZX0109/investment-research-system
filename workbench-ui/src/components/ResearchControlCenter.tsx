import {
  Activity,
  AlertTriangle,
  BarChart3,
  Building2,
  CheckCircle2,
  Clock3,
  Database,
  GitCompareArrows,
  Layers3,
  LockKeyhole,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  WalletCards,
} from "lucide-react";
import type { ReactNode } from "react";
import { Panel } from "./Panel";
import { useI18n } from "../i18n";
import type {
  AssetSnapshot,
  ResearchAcceptanceReport,
  ResearchCompletionReport,
  ResearchDataQualityReport,
  ResearchLifecycleStatus,
  ResearchModelRoster,
  ResearchShadowSummary,
  ResearchDeliveryManifest,
} from "../api/types";

export type ResearchWorkspaceSection =
  | "today"
  | "discover"
  | "company"
  | "compare"
  | "portfolio"
  | "research"
  | "alerts"
  | "data"
  | "trust"
  | "settings";

type SectionItem = {
  id: ResearchWorkspaceSection;
  icon: typeof Search;
  zh: string;
  en: string;
};

const SECTION_ITEMS: SectionItem[] = [
  { id: "today", icon: Sparkles, zh: "今日", en: "Today" },
  { id: "discover", icon: Search, zh: "发现", en: "Discover" },
  { id: "company", icon: Building2, zh: "公司", en: "Company" },
  { id: "compare", icon: GitCompareArrows, zh: "对比", en: "Compare" },
  { id: "portfolio", icon: WalletCards, zh: "组合", en: "Portfolio" },
  { id: "research", icon: BarChart3, zh: "研究室", en: "Research" },
  { id: "alerts", icon: AlertTriangle, zh: "提醒", en: "Alerts" },
  { id: "data", icon: Database, zh: "数据中心", en: "Data" },
  { id: "trust", icon: ShieldCheck, zh: "信任中心", en: "Trust" },
  { id: "settings", icon: Settings, zh: "设置", en: "Settings" },
];

export function ResearchWorkspaceNav({
  active,
  onChange,
}: {
  active: ResearchWorkspaceSection;
  onChange: (section: ResearchWorkspaceSection) => void;
}) {
  const { l } = useI18n();
  return (
    <nav className="research-workspace-nav" aria-label={l("研究工作流", "Research workflow")}>
      <div className="research-workspace-nav__label">
        <Layers3 size={15} aria-hidden="true" />
        <span>{l("研究工作流", "Research workflow")}</span>
      </div>
      <div className="research-workspace-nav__items" role="tablist" aria-label={l("研究模块", "Research modules")}>
        {SECTION_ITEMS.map(({ id, icon: Icon, zh, en }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active === id}
            className={active === id ? "is-active" : undefined}
            onClick={() => onChange(id)}
          >
            <Icon size={14} aria-hidden="true" />
            <span>{l(zh, en)}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}

export function ResearchStatusStrip({
  snapshot,
  acceptance,
  lifecycle,
  shadow,
  dataQuality,
}: {
  snapshot: AssetSnapshot | null;
  acceptance: ResearchAcceptanceReport | null;
  lifecycle: ResearchLifecycleStatus | null;
  shadow: ResearchShadowSummary | null;
  dataQuality: ResearchDataQualityReport | null;
}) {
  const { l } = useI18n();
  const dataDate =
    snapshot?.data_as_of ??
    snapshot?.market_observation.trade_date ??
    lifecycle?.latest_trade_date ??
    null;
  const acceptanceLabel = acceptance
    ? acceptance.status === "complete"
      ? l("通过", "pass")
      : acceptance.status === "partial"
        ? l("部分通过", "partial")
        : l("阻塞", "blocked")
    : l("未读取", "not loaded");
  const acceptanceTone = acceptance?.status === "complete" ? "good" : "warn";
  const longTermLabel = snapshot?.long_term_status
    ? humanizeStatus(snapshot.long_term_status, l)
    : l("未形成", "not formed");
  const shadowLabel = shadow
    ? `${shadow.valid_session_count}/60${shadow.real_prediction_count != null ? ` (${l("真实", "real")} ${shadow.real_prediction_count})` : ""}`
    : "—";
  const modelScopeCoverage = dataQuality?.model_backtest_scope.coverage_ratio ?? null;

  return (
    <section className="research-status-strip" aria-label={l("研究状态摘要", "Research status summary")}>
      <StatusItem
        icon={<LockKeyhole size={15} aria-hidden="true" />}
        label={l("数据层", "Data tier")}
        value={l("研究级 PIT", "Research PIT")}
        detail={l("仅研究，不可直接部署", "Research only; not deployable")}
        tone="warn"
      />
      <StatusItem
        icon={<Clock3 size={15} aria-hidden="true" />}
        label={l("数据截止", "Data as of")}
        value={dataDate ? dataDate.slice(0, 10) : "—"}
        detail={l("以快照截止日为准", "Uses the snapshot cutoff")}
        tone={dataDate ? "good" : "muted"}
      />
      <StatusItem
        icon={<Activity size={15} aria-hidden="true" />}
        label={l("模型行情范围", "Model price scope")}
        value={modelScopeCoverage == null ? "—" : `${(modelScopeCoverage * 100).toFixed(1)}%`}
        detail={l("沪深 A 股 + 基准 ETF，需 raw+qfq", "Shanghai/Shenzhen A shares + benchmark ETFs; raw+qfq required")}
        tone={modelScopeCoverage != null && modelScopeCoverage >= 0.98 ? "good" : "warn"}
      />
      <StatusItem
        icon={<BarChart3 size={15} aria-hidden="true" />}
        label={l("长期模型", "Long-term model")}
        value={longTermLabel}
        detail={l("长期评分卡可用性", "Scorecard availability")}
        tone={snapshot?.long_term_status === "available" ? "good" : "warn"}
      />
      <StatusItem
        icon={<CheckCircle2 size={15} aria-hidden="true" />}
        label={l("接受度", "Acceptance")}
        value={acceptanceLabel}
        detail={l("数据、模型、证据三道门", "Data, model and evidence gates")}
        tone={acceptanceTone}
      />
      <StatusItem
        icon={<ShieldCheck size={15} aria-hidden="true" />}
        label={l("Shadow 追踪", "Shadow tracking")}
        value={shadowLabel}
        detail={l("有效交易日 / 目标 60", "Valid trade dates / target 60")}
        tone={shadow && shadow.valid_session_count >= 60 ? "good" : "warn"}
      />
    </section>
  );
}

export function ResearchDataReadinessBanner({
  quality,
  onOpenData,
}: {
  quality: ResearchDataQualityReport | null;
  onOpenData: () => void;
}) {
  const { l } = useI18n();
  const modelCoverage = quality?.model_backtest_scope.coverage_ratio;
  const qfqMissing = quality?.quote_only_scope.qfq_missing_symbol_count;
  const findDataset = (id: string) => quality?.datasets.find((item) => item.id === id);
  const financials = findDataset("financial_fields");
  const actions = findDataset("corporate_actions");
  const isLoaded = Boolean(quality);
  return (
    <section className="research-data-readiness" aria-label={l("免费研究版数据范围", "Free research data scope")}>
      <div className="research-data-readiness__heading">
        <div>
          <span>{l("免费研究版 · 能力边界", "Free research edition · capability boundary")}</span>
          <h2>{l("先看数据能支持什么，再看模型给出什么", "See what data supports before reading model output")}</h2>
          <p>{l(
            "面向需要自己验证经营、财务和风险证据的 A 股长期研究者。行情浏览、收益研究和全市场历史结论使用不同数据门槛。",
            "For A-share long-term researchers who want to verify business, financial and risk evidence. Quote research, return research and full-market historical claims use different gates.",
          )}</p>
        </div>
        <button type="button" className="ghost-button" onClick={onOpenData}>
          <Database size={14} aria-hidden="true" /> {l("查看完整数据清单", "View full data inventory")}
        </button>
      </div>
      <div className="research-data-readiness__grid">
        <ReadinessCard
          title={l("可做：沪深收益研究与模型", "Available: Shanghai/Shenzhen return research and models")}
          value={!isLoaded ? "—" : modelCoverage == null ? "—" : `${(modelCoverage * 100).toFixed(1)}%`}
          detail={!isLoaded ? l("正在读取真实数据状态", "Loading persisted data status") : l(
            `${quality?.model_backtest_scope.eligible_symbol_count ?? 0} 个标的同时具备 raw 与前复权行情；仍会经过历史长度、流动性和质量门禁。`,
            `${quality?.model_backtest_scope.eligible_symbol_count ?? 0} symbols have both raw and front-adjusted prices; history, liquidity and quality gates still apply.`,
          )}
          tone={modelCoverage != null && modelCoverage >= 0.98 ? "good" : "warn"}
        />
        <ReadinessCard
          title={l("仅可查：北交所 / 范围外标的", "Quote only: BSE / out-of-scope symbols")}
          value={!isLoaded ? "—" : `${quality?.quote_only_scope.raw_symbol_count ?? 0} ${l("个", "symbols")}`}
          detail={!isLoaded ? l("原始行情状态未读取", "Raw-price status not loaded") : l(
            `${qfqMissing ?? 0} 个缺少前复权，且免费版不允许这部分进入模型或收益回测。`,
            `${qfqMissing ?? 0} lack front-adjusted prices; the free edition never sends this scope into models or return backtests.`,
          )}
          tone="warn"
        />
        <ReadinessCard
          title={l("仍受限：历史全市场结论", "Restricted: full-market historical claims")}
          value={!isLoaded ? "—" : financials?.published_at_coverage == null ? l("待核验", "unverified") : `${(financials.published_at_coverage * 100).toFixed(1)}%`}
          detail={!isLoaded ? l("发布时间与公司行为状态未读取", "Publication-time and corporate-action status not loaded") : l(
            `财务发布时间证明和公司行为仍不完整（公司行为 ${formatCoverage(actions?.coverage_ratio)}），不能宣称全市场无幸存者偏差回测。`,
            `Financial publication proof and corporate actions remain incomplete (corporate actions ${formatCoverage(actions?.coverage_ratio)}); no full-market survivorship-safe backtest claim is made.`,
          )}
          tone="warn"
        />
      </div>
    </section>
  );
}

function StatusItem({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: "good" | "warn" | "muted";
}) {
  return (
    <div className={`research-status-strip__item research-status-strip__item--${tone}`}>
      <div className="research-status-strip__item-head">
        {icon}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export function ResearchSectionIntro({
  section,
  selectedLabel,
  assetCount,
}: {
  section: ResearchWorkspaceSection;
  selectedLabel: string;
  assetCount: number;
}) {
  const { l } = useI18n();
  const copy: Record<Exclude<ResearchWorkspaceSection, "today" | "data" | "trust">, { zh: string; en: string; noteZh: string; noteEn: string }> = {
    discover: {
      zh: "发现：先从研究池筛选，再进入同源快照",
      en: "Discover: start with the research universe, then open a shared snapshot",
      noteZh: `当前研究池有 ${assetCount} 个可选标的；左侧列表是入口，缺失数据会在后续步骤明确标注。`,
      noteEn: `${assetCount} subjects are currently in the research pool. The picker is the entry point and missing data is surfaced downstream.`,
    },
    company: {
      zh: `公司：${selectedLabel} 的经营与长期变化`,
      en: `Company: business and long-term change for ${selectedLabel}`,
      noteZh: "公司页只使用同一份快照驱动行情、事实卡、评分卡和 AI 解释，避免多个模块出现不同数字。",
      noteEn: "The company view uses one snapshot for prices, facts, scorecard and AI explanation so modules cannot drift apart.",
    },
    compare: {
      zh: "对比：并排比较需要先补齐多标的同日快照",
      en: "Compare: side-by-side comparison requires same-day snapshots for multiple subjects",
      noteZh: "当前版本先展示研究池和单标的证据。未形成可审计的同日多标的快照前，不生成排名或结论。",
      noteEn: "This version shows the research pool and single-subject evidence. No ranking is generated before auditable same-day snapshots exist.",
    },
    portfolio: {
      zh: "组合：从研究结论走向组合级风险观察",
      en: "Portfolio: move from research conclusions to portfolio-level risk observation",
      noteZh: "组合视图保留研究观察边界；仓位、相关性、集中度和压力情景应以可追溯数据为前提。",
      noteEn: "Portfolio view stays within research-observation boundaries; positions, correlation, concentration and stress need traceable data.",
    },
    research: {
      zh: "研究室：把问题、证据、反方证据和待观察项串成闭环",
      en: "Research: connect questions, evidence, contrary evidence and watch items",
      noteZh: "右侧 AI 助手负责解释，不替代证据。每次回答都应保留来源、截止日和缺口。",
      noteEn: "The AI assistant explains but does not replace evidence. Each answer retains sources, cutoff and gaps.",
    },
    alerts: {
      zh: "提醒：只提醒可验证的事件与证据变化",
      en: "Alerts: notify only on verifiable events and evidence changes",
      noteZh: "提醒不等于交易信号；当前先把公告、财报、覆盖率和模型状态变化放在研究上下文里。",
      noteEn: "An alert is not a trading signal. The first layer tracks notices, reports, coverage and model-state changes in context.",
    },
    settings: {
      zh: "设置：管理研究边界、模型配置和显示偏好",
      en: "Settings: manage research boundaries, model configuration and display preferences",
      noteZh: "设置只影响项目配置和展示方式，不会改变历史快照，也不会绕过数据或模型门禁。",
      noteEn: "Settings change project configuration and presentation only; they never mutate snapshots or bypass data/model gates.",
    },
  };
  const value = copy[section as keyof typeof copy];
  if (!value) return null;
  return (
    <section className="research-section-intro" aria-live="polite">
      <div className="research-section-intro__title">
        <Sparkles size={17} aria-hidden="true" />
        <h2>{l(value.zh, value.en)}</h2>
      </div>
      <p>{l(value.noteZh, value.noteEn)}</p>
    </section>
  );
}

export function ResearchSettingsCenter({
  acceptance,
  lifecycle,
}: {
  acceptance: ResearchAcceptanceReport | null;
  lifecycle: ResearchLifecycleStatus | null;
}) {
  const { l } = useI18n();
  const openModelSettings = () => window.dispatchEvent(new CustomEvent("open-llm-config"));
  return (
    <section className="research-control-page">
      <Panel eyebrow={l("设置", "Settings")} title={l("研究边界与项目配置", "Research boundaries and project configuration")}>
        <div className="research-module-grid">
          <DataCard label={l("当前数据层", "Current data tier")} value="research_pit" detail={l("研究级，不可直接部署", "Research-grade; not deployable")} tone="warn" />
          <DataCard label={l("接受度门禁", "Acceptance gates")} value={acceptance?.status ?? l("未读取", "not loaded")} detail={l("数据、模型、证据共同决定可用性", "Data, model and evidence jointly determine usability")} tone={acceptance?.status === "complete" ? "good" : "warn"} />
          <DataCard label={l("最近数据更新", "Latest data update")} value={lifecycle?.latest_data_update?.slice(0, 16) ?? "—"} detail={lifecycle?.latest_trade_date ?? l("交易日未返回", "Trade date unavailable")} />
        </div>
        <div className="research-control-page__columns">
          <div>
            <h3>{l("项目 AI", "Project AI")}</h3>
            <p className="muted">{l("配置统一的项目模型接口；密钥只保存在本机凭证库，页面不会显示明文。", "Configure the shared project model endpoint; credentials stay in the local vault and are never shown in plaintext.")}</p>
            <button type="button" className="primary-button" onClick={openModelSettings}>{l("打开项目 AI 设置", "Open project AI settings")}</button>
          </div>
          <div>
            <h3>{l("不可绕过的规则", "Non-bypassable rules")}</h3>
            <ul className="research-control-page__list">
              <li><CheckCircle2 size={13} aria-hidden="true" />{l("缺少 PIT 证据时拒答", "Abstain when PIT evidence is missing")}</li>
              <li><CheckCircle2 size={13} aria-hidden="true" />{l("研究级模型不会自动生产部署", "Research models are never auto-deployed")}</li>
              <li><CheckCircle2 size={13} aria-hidden="true" />{l("不输出买卖、目标价或收益承诺", "No buy/sell, target-price or return promises")}</li>
            </ul>
          </div>
        </div>
      </Panel>
    </section>
  );
}

export function ResearchDataCenter({
  snapshot,
  acceptance,
  lifecycle,
  completion,
  quality,
}: {
  snapshot: AssetSnapshot | null;
  acceptance: ResearchAcceptanceReport | null;
  lifecycle: ResearchLifecycleStatus | null;
  completion: ResearchCompletionReport | null;
  quality: ResearchDataQualityReport | null;
}) {
  const { l } = useI18n();
  const fundamentals = snapshot?.fundamental_coverage?.coverage_pct ?? null;
  const providerCounts = acceptance?.data?.provider_counts ?? {};
  const qualityCounts = acceptance?.data?.quality_status_counts ?? {};
  const eventStates = acceptance?.data?.event_coverage_states ?? {};
  const blockerList = unique([
    ...(snapshot?.long_term_blocking_reasons ?? []),
    ...(acceptance?.blocking_reasons ?? []),
    ...(lifecycle?.blocking_reasons ?? []),
  ]);
  const rawPrices = quality?.datasets.find((item) => item.id === "raw_prices");
  const qfqPrices = quality?.datasets.find((item) => item.id === "hushen_qfq_prices");
  const outsideScope = quality?.datasets.find((item) => item.id === "outside_scope_adjusted_prices");
  const financialFields = quality?.datasets.find((item) => item.id === "financial_fields");
  const financialRatioBackfill = quality?.datasets.find((item) => item.id === "financial_ratio_backfill");
  const financialCoreBulkBackfill = quality?.datasets.find((item) => item.id === "financial_core_bulk_backfill");
  const financialStatementBulkBackfill = quality?.datasets.find((item) => item.id === "financial_statement_bulk_backfill");
  const researchSampleLayer = quality?.datasets.find((item) => item.id === "research_sample_layer");
  const corporateActions = quality?.datasets.find((item) => item.id === "corporate_actions");
  const lifecycleData = quality?.datasets.find((item) => item.id === "security_lifecycle");
  const macroReleaseTimes = quality?.datasets.find((item) => item.id === "macro_release_times");

  return (
    <section className="research-control-page">
      <Panel eyebrow={l("数据中心", "Data center")} title={l("数据截止、覆盖率与质量状态", "Cutoff, coverage and quality") }>
        <p className="research-control-page__lead">
          {l(
            "这里回答三个问题：数据截至何时、哪些字段已覆盖、哪些结论仍被数据缺口阻塞。所有未知状态都保留为未知。",
            "This answers three questions: when data stops, which fields are covered, and which conclusions remain blocked. Unknown stays unknown.",
          )}
        </p>
        <div className="research-data-grid">
          <DataCard label={l("数据层", "Data tier")} value={l("research_pit", "research_pit")} detail={l("历史可见性与版本需审计", "Historical visibility and versions require audit")} tone="warn" />
          <DataCard label={l("原始行情", "Raw prices")} value={formatCoverage(rawPrices?.coverage_ratio)} detail={l(`${rawPrices?.available_count ?? 0}/${rawPrices?.target_count ?? 0} 标的可供浏览`, `${rawPrices?.available_count ?? 0}/${rawPrices?.target_count ?? 0} symbols for quote research`)} tone={rawPrices?.status === "available" ? "good" : "warn"} />
          <DataCard label={l("模型/回测行情", "Model/backtest prices")} value={formatCoverage(qfqPrices?.coverage_ratio)} detail={l(`仅沪深 A 股 + ETF：${qfqPrices?.available_count ?? 0}/${qfqPrices?.target_count ?? 0}`, `Shanghai/Shenzhen + ETFs only: ${qfqPrices?.available_count ?? 0}/${qfqPrices?.target_count ?? 0}`)} tone={qfqPrices?.status === "available" ? "good" : "warn"} />
          <DataCard label={l("范围外行情", "Out-of-scope prices")} value={`${outsideScope?.target_count ?? 0}`} detail={l(`${outsideScope?.missing_symbol_count ?? 0} 个缺前复权，不入模型/回测`, `${outsideScope?.missing_symbol_count ?? 0} lack qfq; excluded from models/backtests`)} tone="warn" />
          <DataCard label={l("行情截止", "Market cutoff")} value={snapshot?.market_observation.trade_date ?? "—"} detail={snapshot?.market_observation.source ?? l("来源未记录", "source not recorded")} />
          <DataCard label={l("财务字段", "Financial fields")} value={formatCoverage(financialFields?.coverage_ratio ?? (fundamentals == null ? null : fundamentals / 100))} detail={l(`发布时间证明 ${formatCoverage(financialFields?.published_at_coverage)}`, `Publication-time proof ${formatCoverage(financialFields?.published_at_coverage)}`)} tone={financialFields?.pit_verified ? "good" : "warn"} />
          <DataCard label={l("宏观发布时间", "Macro release times")} value={formatCoverage(macroReleaseTimes?.coverage_ratio)} detail={l(`${macroReleaseTimes?.available_count ?? 0}/${macroReleaseTimes?.target_count ?? 0} 条有 published_at；日期级证据仍不等于完整 PIT`, `${macroReleaseTimes?.available_count ?? 0}/${macroReleaseTimes?.target_count ?? 0} rows have published_at; date-level evidence is not complete PIT`)} tone={macroReleaseTimes?.status === "complete" ? "good" : "warn"} />
          <DataCard label={l("核心财报批量回补", "Bulk core financial reports")} value={formatCoverage(financialCoreBulkBackfill?.coverage_ratio)} detail={l(`${financialCoreBulkBackfill?.available_count ?? 0}/${financialCoreBulkBackfill?.target_count ?? 0} 报告期 · ${financialCoreBulkBackfill?.dimensions?.row_count ?? 0} 条 · 完整性错误 ${financialCoreBulkBackfill?.dimensions?.invalid_page_count ?? 0}`, `${financialCoreBulkBackfill?.available_count ?? 0}/${financialCoreBulkBackfill?.target_count ?? 0} periods · ${financialCoreBulkBackfill?.dimensions?.row_count ?? 0} rows · integrity errors ${financialCoreBulkBackfill?.dimensions?.invalid_page_count ?? 0}`)} tone={financialCoreBulkBackfill?.status === "complete" && financialCoreBulkBackfill?.dimensions?.invalid_page_count === 0 ? "good" : "warn"} />
          <DataCard label={l("四表批量回补", "Four-statement backfill")} value={formatCoverage(financialStatementBulkBackfill?.coverage_ratio)} detail={l(`${financialStatementBulkBackfill?.available_count ?? 0}/${financialStatementBulkBackfill?.target_count ?? 0} 报告期 · ${financialStatementBulkBackfill?.dimensions?.row_count ?? 0} 条 · 完整性错误 ${financialStatementBulkBackfill?.dimensions?.invalid_page_count ?? 0}`, `${financialStatementBulkBackfill?.available_count ?? 0}/${financialStatementBulkBackfill?.target_count ?? 0} periods · ${financialStatementBulkBackfill?.dimensions?.row_count ?? 0} rows · integrity errors ${financialStatementBulkBackfill?.dimensions?.invalid_page_count ?? 0}`)} tone={financialStatementBulkBackfill?.status === "complete" && financialStatementBulkBackfill?.dimensions?.invalid_page_count === 0 ? "good" : "warn"} />
          <DataCard label={l("全市场财务回补", "Full-market financial backfill")} value={formatCoverage(financialRatioBackfill?.coverage_ratio)} detail={l(`${financialRatioBackfill?.available_count ?? 0}/${financialRatioBackfill?.target_count ?? 0} 标的 · 发布时间/修订对账后才可用于 PIT`, `${financialRatioBackfill?.available_count ?? 0}/${financialRatioBackfill?.target_count ?? 0} symbols · PIT requires publication/revision reconciliation`)} tone={financialRatioBackfill?.status === "complete" ? "good" : "warn"} />
          <DataCard label={l("研究样本层", "Research sample layer")} value={formatCoverage(researchSampleLayer?.coverage_ratio)} detail={l(`${researchSampleLayer?.available_count ?? 0}/${researchSampleLayer?.target_count ?? 0} 已合并；后台 staging ${researchSampleLayer?.dimensions?.staging_symbol_count ?? 0} 个标的`, `${researchSampleLayer?.available_count ?? 0}/${researchSampleLayer?.target_count ?? 0} promoted; ${researchSampleLayer?.dimensions?.staging_symbol_count ?? 0} symbols in staging`)} tone={researchSampleLayer?.status === "available" ? "good" : "warn"} />
          <DataCard label={l("公司行为", "Corporate actions")} value={formatCoverage(corporateActions?.coverage_ratio)} detail={l(`${corporateActions?.available_count ?? 0}/${corporateActions?.target_count ?? 0} 标的`, `${corporateActions?.available_count ?? 0}/${corporateActions?.target_count ?? 0} symbols`)} tone={corporateActions?.status === "complete" ? "good" : "warn"} />
          <DataCard label={l("生命周期", "Lifecycle history")} value={formatCoverage(lifecycleData?.coverage_ratio)} detail={l("ST、退市、行业历史尚不完整", "ST, delisting and industry history remain incomplete")} tone={lifecycleData?.status === "complete" ? "good" : "warn"} />
        </div>
        <div className="research-control-page__columns">
          <div>
            <h3>{l("质量计数", "Quality counts")}</h3>
            <KeyValueList values={qualityCounts} empty={l("质量统计尚未返回", "Quality counts are not available")} />
          </div>
          <div>
            <h3>{l("事件覆盖", "Event coverage")}</h3>
            <KeyValueList values={eventStates} empty={l("事件覆盖尚未返回", "Event coverage is not available")} />
          </div>
          <div>
            <h3>{l("数据阻塞项", "Data blockers")}</h3>
            {blockerList.length ? (
              <ul className="research-control-page__list research-control-page__list--warning">
                {blockerList.map((item) => <li key={item}><AlertTriangle size={13} aria-hidden="true" />{item}</li>)}
              </ul>
            ) : <p className="muted">{l("当前没有返回阻塞原因；这不等于所有数据已完整。", "No blockers were returned; this does not prove complete data.")}</p>}
          </div>
        </div>
        <div className="research-completion-summary">
          <div><strong>{completion?.summary.missing ?? "—"}</strong><span>{l("项数据/能力待补", "gates still missing")}</span></div>
          <div><strong>{completion?.summary.passed ?? "—"}</strong><span>{l("项已通过审计", "gates passed")}</span></div>
          <div><strong>{completion?.summary.total ?? "—"}</strong><span>{l("项总门禁", "total gates")}</span></div>
        </div>
        <div className="research-completion-list">
          <h3>{l("完整缺失清单", "Complete missing-data list")}</h3>
          {completion?.missing_data?.length ? <ul className="research-control-page__list research-control-page__list--warning">{completion.missing_data.map((item) => <li key={item.id}><AlertTriangle size={13} /><span><strong>{item.name ?? item.id}</strong><small>{item.remediation ?? item.gap ?? l("待补齐", "to be completed")}</small></span></li>)}</ul> : <p className="muted">{l("缺失清单尚未读取；这不等于数据完整。", "Missing-data list is not loaded; this does not prove completeness.")}</p>}
        </div>
        <div className="research-completion-list">
          <h3>{l("数据完成执行计划", "Data-completion runbook")}</h3>
          {completion?.data_completion_plan?.steps?.length ? (
            <ul className="research-control-page__list">
              {completion.data_completion_plan.steps.map((step) => (
                <li key={step.id}>
                  <StatusChip value={step.status} />
                  <span><strong>{step.id}</strong><small>{step.dataset ?? "—"}{step.blocking_reasons?.length ? ` · ${step.blocking_reasons.join(" · ")}` : ""}{step.command?.length ? ` · ${step.command.slice(1).join(" ")}` : ""}</small></span>
                </li>
              ))}
            </ul>
          ) : <p className="muted">{l("完成计划尚未读取。", "Completion runbook is not loaded.")}</p>}
        </div>
      </Panel>
    </section>
  );
}

export function ResearchTrustCenter({
  snapshot,
  acceptance,
  lifecycle,
  rosters,
  shadow,
  delivery,
}: {
  snapshot: AssetSnapshot | null;
  acceptance: ResearchAcceptanceReport | null;
  lifecycle: ResearchLifecycleStatus | null;
  rosters: ResearchModelRoster[];
  shadow: ResearchShadowSummary | null;
  delivery: ResearchDeliveryManifest | null;
}) {
  const { l } = useI18n();
  const blockers = unique([
    ...(acceptance?.blocking_reasons ?? []),
    ...(lifecycle?.blocking_reasons ?? []),
    ...(snapshot?.long_term_blocking_reasons ?? []),
  ]);
  const evidenceCount = snapshot?.evidence_merge_result?.sources.length ?? 0;
  const taskStates = Object.entries(acceptance?.tasks ?? {});
  return (
    <section className="research-control-page">
      <Panel eyebrow={l("信任中心", "Trust center")} title={l("为什么可以相信、哪里不能相信", "Why to trust it — and where not to") }>
        <div className="trust-hero">
          <div className="trust-hero__icon"><ShieldCheck size={24} aria-hidden="true" /></div>
          <div>
            <strong>{l("当前是研究级 PIT，不是生产投顾或自动交易系统", "This is research-grade PIT, not production advice or auto-trading")}</strong>
            <p>{l("系统必须同时满足数据、模型、证据三道门；任何一道门不满足，就降级、拒答或保留缺口。", "The system has data, model and evidence gates. If any gate fails, it degrades, abstains or preserves the gap.")}</p>
          </div>
          <span className="trust-hero__badge">{l("不可直接部署", "Not deployable")}</span>
        </div>
        <div className="trust-gates">
          <TrustGate title={l("数据 / PIT", "Data / PIT")} status={acceptance?.data ? l("已返回检查", "check returned") : l("未读取", "not loaded")} detail={l("截止日、质量、事件时序和 provider chain 必须可追溯。", "Cutoff, quality, event timing and provider chain must be traceable.")} good={Boolean(acceptance?.data)} />
          <TrustGate title={l("模型 / 评估", "Model / evaluation")} status={`${rosters.length} ${l("个 roster", "rosters")}`} detail={l("需要任务级指标、hash、版本、shadow 和失败原因。", "Requires task metrics, hashes, versions, shadow and failure reasons.")} good={rosters.length > 0} />
          <TrustGate title={l("证据 / 引用", "Evidence / citations")} status={`${evidenceCount} ${l("个来源", "sources")}`} detail={l("回答应能回到公告、财报或结构化事实，不能把缺失写成结论。", "Answers must trace to notices, reports or structured facts; missing is not a conclusion.")} good={evidenceCount > 0} />
        </div>
        <div className="research-completion-summary">
          <div><strong>{delivery?.release_channel ?? "—"}</strong><span>{l("发布通道", "release channel")}</span></div>
          <div><strong>{delivery ? Object.values(delivery.gates).filter(Boolean).length : "—"}</strong><span>{l("已通过交付门禁", "delivery gates passed")}</span></div>
          <div><strong>{delivery?.missing_gates.length ?? "—"}</strong><span>{l("待处理门禁", "gates remaining")}</span></div>
        </div>
        <div className="research-control-page__columns research-control-page__columns--trust">
          <div>
            <h3>{l("模型任务", "Model tasks")}</h3>
            {taskStates.length ? (
              <ul className="research-control-page__list">
                {taskStates.slice(0, 8).map(([task, value]) => <li key={task}><span>{task}</span><StatusChip value={typeof value === "object" && value && "status" in value ? String(value.status) : l("未知", "unknown")} /></li>)}
              </ul>
            ) : <p className="muted">{l("接受度报告尚未返回任务状态。", "Task status is not available from acceptance report.")}</p>}
          </div>
          <div>
            <h3>{l("Shadow 进度", "Shadow progress")}</h3>
            <div className="trust-progress">
              <div><strong>{shadow?.valid_session_count ?? 0}</strong><span>/ 60 {l("有效交易日", "valid trade dates")}</span></div>
              <div className="trust-progress__bar"><span style={{ width: `${Math.min(100, ((shadow?.valid_session_count ?? 0) / 60) * 100)}%` }} /></div>
              <small>{shadow?.primary_change_60_status === "eligible_for_review" ? l("达到 review 门槛", "eligible for review") : l("未达到 60 会话门槛", "below the 60-session gate")}</small>
              <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-muted, #888)" }}>
                <div>{l("真实预测", "Real predictions")}: <strong>{shadow?.real_prediction_count ?? 0}</strong> / {l("空预测", "empty")}: <strong>{shadow?.empty_prediction_count ?? 0}</strong></div>
                <div>{l("有真实预测的交易日", "Trade dates with real predictions")}: <strong>{shadow?.real_prediction_trade_date_count ?? 0}</strong> / 60</div>
                <div>{l("占位拒答", "Placeholder abstains")}: <strong>{shadow?.prediction_state_counts?.placeholder_abstain ?? 0}</strong> · {l("门禁拒答", "Gated abstains")}: <strong>{shadow?.prediction_state_counts?.gated_abstain ?? 0}</strong> · {l("证据无效", "Invalid evidence")}: <strong>{shadow?.prediction_state_counts?.invalid_evidence ?? 0}</strong></div>
                <div>{l("结果回填", "Outcomes backfilled")}: <strong>{shadow?.outcome_backfill_count ?? 0}</strong> / {l("拒答率", "abstain rate")}: <strong>{((shadow?.abstain_rate ?? 0) * 100).toFixed(1)}%</strong></div>
              </div>
            </div>
          </div>
          <div>
            <h3>{l("审计边界", "Audit boundary")}</h3>
            <ul className="research-control-page__list">
              <li><CheckCircle2 size={13} aria-hidden="true" />{l("研究级数据，不宣称生产级", "Research-grade data, not production-grade")}</li>
              <li><CheckCircle2 size={13} aria-hidden="true" />{l("来源、截止日、版本和 hash 必须保留", "Sources, cutoff, version and hashes are retained")}</li>
              <li><AlertTriangle size={13} aria-hidden="true" />{l("没有证据就拒答或列为待补", "Abstain or mark missing when evidence is absent")}</li>
            </ul>
          </div>
        </div>
        <details className="trust-blockers">
          <summary>{l(`当前阻塞原因（${blockers.length}）`, `Current blockers (${blockers.length})`)}</summary>
          {blockers.length ? <ul className="research-control-page__list research-control-page__list--warning">{blockers.map((item) => <li key={item}><AlertTriangle size={13} aria-hidden="true" />{item}</li>)}</ul> : <p className="muted">{l("没有返回阻塞原因，但仍需结合质量与覆盖率判断。", "No blockers returned; still inspect quality and coverage.")}</p>}
        </details>
      </Panel>
    </section>
  );
}

function DataCard({ label, value, detail, tone = "muted" }: { label: string; value: string; detail: string; tone?: "good" | "warn" | "muted" }) {
  return <div className={`research-data-card research-data-card--${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function ReadinessCard({ title, value, detail, tone }: { title: string; value: string; detail: string; tone: "good" | "warn" }) {
  return <article className={`research-data-readiness__card research-data-readiness__card--${tone}`}><span>{title}</span><strong>{value}</strong><p>{detail}</p></article>;
}

function TrustGate({ title, status, detail, good }: { title: string; status: string; detail: string; good: boolean }) {
  return <div className={`trust-gate ${good ? "is-good" : "is-warn"}`}><div><span>{good ? <CheckCircle2 size={15} aria-hidden="true" /> : <AlertTriangle size={15} aria-hidden="true" />}</span><strong>{title}</strong></div><b>{status}</b><p>{detail}</p></div>;
}

function StatusChip({ value }: { value: string }) {
  return <span className={`trust-status-chip trust-status-chip--${value === "available" || value === "complete" ? "good" : "warn"}`}>{value}</span>;
}

function KeyValueList({ values, empty }: { values: Record<string, number>; empty: string }) {
  const entries = Object.entries(values);
  if (!entries.length) return <p className="muted">{empty}</p>;
  return <ul className="research-control-page__list">{entries.slice(0, 8).map(([key, value]) => <li key={key}><span>{key}</span><strong>{value}</strong></li>)}</ul>;
}

function formatCoverage(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function humanizeStatus(status: string, l: (zh: string, en: string) => string) {
  if (status === "available") return l("可用", "available");
  if (status === "blocked") return l("阻塞", "blocked");
  if (status === "research_only") return l("研究级", "research only");
  return status;
}

function unique(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}
