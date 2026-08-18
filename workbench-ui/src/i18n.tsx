import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from "react";

export type UiLanguage = "zh-CN" | "en-US";

const STORAGE_KEY = "cn-research-ui-language";

const messages = {
  "zh-CN": {
    "language.chinese": "中文",
    "language.english": "英文",
    "language.label": "界面语言",
    "brand.name": "A股量化研究平台",
    "brand.tagline": "零预算 · 研究级 · 可复现 · 证据驱动",
    "header.context": "当前研究上下文",
    "header.environment": "技术环境",
    "header.market": "CN / 沪深日线",
    "header.closeConfirmed": "收盘确认 · Asia/Shanghai",
    "header.strictGate": "严格门禁",
    "banner.research": "研究级公开数据 · 非投资建议 · 不可直接交易 · 数据来源与更新时间见本页结果",
    "banner.formal": "正式模式需要授权数据、SLA、完整历史可见时间和发布审批；任一条件缺失时系统将阻断。",
    "mode.demo": "演示模式",
    "mode.sandbox": "沙盒模式",
    "mode.research": "A股研究模式",
    "mode.real": "正式模式（需授权）",
    "research.eyebrow": "长期投资研究",
    "research.title": "先看数据，再看长期结论",
    "research.dataQuality": "1 · 数据质量与资格",
    "research.backendStatus": "后端验收状态",
    "research.data": "数据",
    "research.training": "训练",
    "research.prediction": "预测",
    "research.evidence": "证据",
    "research.blockingReasons": "阻断原因",
    "research.abstainReasons": "风险提示原因",
    "research.roster": "2 · 研究模型清单",
    "research.rosterEmpty": "研究清单尚未就绪",
    "research.rosterEmptyBody": "任务保持不可用，不从任意训练目录加载模型。",
    "research.tasks": "3 · 方向、收益与风险",
    "research.notSignal": "非交易信号",
    "research.taskUnavailable": "任务不可用",
    "research.insufficientEvidence": "数据不足，结果仅作风险提示",
    "research.waitingEvidence": "等待冻结快照、研究清单和完整哈希证据。",
    "research.influence": "可核验影响事实",
    "research.nonCausal": "这些是模型输入依据，不代表因果关系。",
    "research.shadow": "4 · 前向验证",
    "research.noShadow": "尚无前向验证记录",
    "research.noShadowBody": "完成下一次收盘研究后开始累计。",
    "research.direction": "方向概率",
    "research.return": "收益区间",
    "research.drawdown": "最大回撤风险",
    "research.up": "上行",
    "research.down": "下行",
    "research.flat": "横盘",
    "research.model": "模型",
    "research.provider": "数据源",
    "research.success": "成功",
    "research.failures": "失败",
    "research.fallbacks": "主备切换",
    "hero.eyebrow": "长期投资主流程",
    "hero.preOpen": "盘前研究",
    "hero.close": "收盘确认研究",
    "hero.title": "先看数据日期与来源，再理解长期投资价值。",
    "hero.body": "先看数据截至时间和缺口，再看经营、成长、估值、风险以及正反证据。1/5/20 日读数只放在短期观察中；所有内容仅供研究，不构成投资建议。",
    "hero.asOf": "数据截至",
    "hero.waiting": "等待快照",
    "shadow.frozen": "已冻结",
    "shadow.valid": "有效",
    "shadow.abstain": "谨慎参考",
    "shadow.forward": "20 日报告",
    "shadow.primary": "60 日主模型复核",
    "shadow.threshold": "尚未达到正式验证门槛",
    "status.complete": "已完成",
    "status.passed": "通过",
    "status.research_only": "研究级",
    "status.exploratory": "探索性",
    "status.partial": "部分可用",
    "status.degraded": "已降级",
    "status.unavailable": "不可用",
    "status.abstain": "谨慎参考",
    "status.blocked": "已阻断",
    "status.fresh": "新鲜",
    "status.stale_usable": "可用旧数据",
    "status.expired": "已过期",
    "status.unsupported": "未覆盖",
    "status.confirmed_none": "已确认无事件",
    "status.events_present": "有事件",
    "status.fetch_failed": "抓取失败"
  },
  "en-US": {
    "language.chinese": "中文",
    "language.english": "English",
    "language.label": "Interface language",
    "brand.name": "A-Share Quant Research Platform",
    "brand.tagline": "Zero-budget · Research-grade · Reproducible · Evidence-driven",
    "header.context": "Current research context",
    "header.environment": "Technical environment",
    "header.market": "CN / Shanghai & Shenzhen daily bars",
    "header.closeConfirmed": "Close confirmed · Asia/Shanghai",
    "header.strictGate": "Strict gate",
    "banner.research": "Public research data · Not investment advice · Not for direct trading · See each result for source and update time",
    "banner.formal": "Formal mode requires licensed data, an SLA, complete historical visibility and release approval. The system blocks when any requirement is missing.",
    "mode.demo": "Demo mode",
    "mode.sandbox": "Sandbox mode",
    "mode.research": "A-share research",
    "mode.real": "Formal mode (licensed)",
    "research.eyebrow": "Long-term investment research",
    "research.title": "Check the data, then the long-term view",
    "research.dataQuality": "1 · Data quality & eligibility",
    "research.backendStatus": "Backend acceptance status",
    "research.data": "Data",
    "research.training": "Training",
    "research.prediction": "Prediction",
    "research.evidence": "Evidence",
    "research.blockingReasons": "Blocking reasons",
    "research.abstainReasons": "Abstain reasons",
    "research.roster": "2 · Research model roster",
    "research.rosterEmpty": "Research roster is not ready",
    "research.rosterEmptyBody": "Tasks remain unavailable; models are never loaded from an arbitrary training folder.",
    "research.tasks": "3 · Direction, return & risk",
    "research.notSignal": "Not a trading signal",
    "research.taskUnavailable": "Task unavailable",
    "research.insufficientEvidence": "Insufficient evidence — prediction withheld",
    "research.waitingEvidence": "Waiting for a frozen snapshot, research roster and complete hash evidence.",
    "research.influence": "Verifiable input facts",
    "research.nonCausal": "These are model inputs, not causal claims.",
    "research.shadow": "4 · Shadow forward validation",
    "research.noShadow": "No forward Shadow records yet",
    "research.noShadowBody": "Accumulation starts after the next close-confirmed research run.",
    "research.direction": "Direction probability",
    "research.return": "Return interval",
    "research.drawdown": "Maximum drawdown risk",
    "research.up": "Up",
    "research.down": "Down",
    "research.flat": "Flat",
    "research.model": "Model",
    "research.provider": "Providers",
    "research.success": "success",
    "research.failures": "failures",
    "research.fallbacks": "fallbacks",
    "hero.eyebrow": "Long-term investment flow",
    "hero.preOpen": "Pre-open research",
    "hero.close": "Close-confirmed research",
    "hero.title": "Review data dates and sources before interpreting long-term value.",
    "hero.body": "Review the data cutoff and gaps first, then business quality, growth, valuation, risk, and evidence for and against. 1/5/20-day readings stay in short-term observation. Everything is research-only, not investment advice.",
    "hero.asOf": "Data as of",
    "hero.waiting": "Waiting for snapshot",
    "shadow.frozen": "Frozen",
    "shadow.valid": "Valid",
    "shadow.abstain": "Withheld",
    "shadow.forward": "20-day report",
    "shadow.primary": "60-day primary review",
    "shadow.threshold": "Formal validation threshold not yet met",
    "status.complete": "Complete",
    "status.passed": "Passed",
    "status.research_only": "Research only",
    "status.exploratory": "Exploratory",
    "status.partial": "Partial",
    "status.degraded": "Degraded",
    "status.unavailable": "Unavailable",
    "status.abstain": "Withheld",
    "status.blocked": "Blocked",
    "status.fresh": "Fresh",
    "status.stale_usable": "Stale usable",
    "status.expired": "Expired",
    "status.unsupported": "Unsupported",
    "status.confirmed_none": "Confirmed none",
    "status.events_present": "Events present",
    "status.fetch_failed": "Fetch failed"
  }
} as const;

type MessageKey = keyof typeof messages["zh-CN"];

interface I18nContextValue {
  language: UiLanguage;
  setLanguage(language: UiLanguage): void;
  t(key: MessageKey): string;
  l(chinese: string, english: string): string;
  term(value?: string | null): string;
  formatDateTime(value?: string | null): string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function initialLanguage(): UiLanguage {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "en-US" || stored === "zh-CN" ? stored : "zh-CN";
}

export function I18nProvider({ children }: PropsWithChildren) {
  const [language, setLanguage] = useState<UiLanguage>(initialLanguage);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, language);
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo<I18nContextValue>(() => ({
    language,
    setLanguage,
    t: (key) => messages[language][key],
    l: (chinese, english) => language === "zh-CN" ? chinese : english,
    term: (rawValue) => {
      if (!rawValue) return language === "zh-CN" ? "暂无" : "n/a";
      if (language === "en-US") {
        const neutralTerms: Record<string, string> = {
          buy: "Positive observation (not an action instruction)",
          sell: "Risk observation (not an action instruction)",
          hold: "Pause judgment",
          avoid: "Risk observation (not an action instruction)",
        };
        return neutralTerms[rawValue.toLowerCase()] ?? rawValue.replaceAll("_", " ");
      }
      const normalized = rawValue.toLowerCase();
      const chineseTerms: Record<string, string> = {
        research: "研究模式",
        real: "正式模式",
        demo: "演示模式",
        sandbox: "沙盒模式",
        synthetic: "合成数据",
        backfilled: "历史回补",
        manual_override: "人工录入",
        equity: "股票",
        etf: "ETF",
        active: "正常",
        inactive: "停用",
        pending: "等待中",
        running: "运行中",
        completed: "已完成",
        succeeded: "成功",
        failed: "失败",
        abstained: "已生成风险提示",
        pass: "通过",
        passed: "通过",
        warn: "警告",
        buy: "正向观察（非行动建议）",
        sell: "风险观察（非行动建议）",
        hold: "暂缓判断",
        avoid: "风险观察（非行动建议）",
        block: "阻断",
        blocked: "已阻断",
        approved: "已批准",
        rejected: "未批准",
        fresh: "新鲜",
        stale: "已过期",
        unavailable: "不可用",
        research_only: "仅供研究",
        exploratory: "探索性",
        manual: "手动",
        daily: "每日",
        weekly: "每周",
        monthly: "每月",
        event_triggered: "事件触发",
        bull: "牛市",
        bear: "熊市",
        range: "震荡",
        high_vol: "高波动",
        checking: "检查中",
        closed: "已收盘",
        holiday: "休市",
        missing: "缺失",
        seeded: "固定演示数据",
        demo_seed: "演示模型",
        seeded_demo_bundle: "固定演示数据包",
        persisted_fallback: "持久化备用源",
        market_data: "市场数据",
        evidence: "证据",
        analysis_run: "分析运行",
        research_report: "研究报告",
        fresh_enough_for_current_mode: "当前模式下数据足够新鲜",
        "analysis-run.created": "已创建分析运行",
        "report.generated": "已生成报告",
        task_intake: "任务接收",
        task_classification: "任务分类",
        plan_generation: "方案生成",
        tool_selection: "工具选择",
        evidence_collection: "证据收集",
        structured_feature_build: "结构化特征构建",
        model_inference: "模型推理",
        counter_evidence_search: "反向证据检索",
        self_audit: "自我审计",
        repair_or_abstain: "修复或风险提示",
        report_generation: "报告生成"
      };
      const chinesePhrases: Record<string, string> = {
        "Demo Investor": "演示用户",
        "NVDA Demo Analysis Report": "英伟达演示分析报告",
        "The system can narrate upside and caveats from a fixed run without hiding synthetic support.": "系统可以基于固定运行说明潜在上行与限制，同时明确披露合成数据支持。",
        "Judge gate prevents stronger action because the evidence stack is still mostly synthetic.": "由于证据栈仍以合成数据为主，评审门禁阻止系统给出更强结论。",
        "Demo analyst note says hyperscaler orders remain resilient into the next two quarters.": "演示分析员记录显示，超大规模客户订单在未来两个季度仍具韧性。",
        "Backfilled path shows higher highs and stable volume participation.": "历史回补路径显示价格高点抬升，成交量参与较稳定。",
        "A prior immutable run keeps the same thesis family but with a weaker confidence profile for comparison.": "An earlier immutable run keeps the same thesis family and can be compared by data and reading status.",
        "Demand stack remains full": "需求证据仍然充分",
        "Price momentum still positive": "价格动量仍为正",
        "Demo mode is presentation-only and should not produce live investment advice.": "演示模式仅用于展示，不应生成真实投资建议。",
        "Demo prediction is seeded synthetic output and is not approved for deployment.": "演示预测来自固定合成数据，未获准部署。",
        "Require live market confirmation before changing the research observation.": "改变研究观察前，需要真实市场数据确认。",
        "Synthetic share remains above the gate, so this run is suitable for demoing flow, not for real capital decisions.": "合成数据占比仍高于门禁阈值，本次运行仅适合展示流程，不适用于真实资金决策。",
        "Synthetic data share exceeds 50%": "合成数据占比超过 50%",
        "No real-market confirmation attached": "未附真实市场数据确认",
        "Historical demo run retained for lineage playback": "保留历史演示运行用于血缘回放",
        "Older seeded run preserved for report comparison and workflow playback.": "保留较早的固定演示运行，用于报告比较和流程回放。",
        "Portfolio risk requires real persisted positions and prices.": "组合风险需要真实持久化的持仓和价格数据。",
        "Stable presentation mode backed by fixed synthetic and backfilled records.": "稳定演示模式，由固定合成数据和历史回补记录支持。"
      };
      return chineseTerms[normalized] ?? chinesePhrases[rawValue] ?? rawValue;
    },
    formatDateTime: (value) => value ? new Date(value).toLocaleString(language) : messages[language]["hero.waiting"]
  }), [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
