import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from "react";

export type UiLanguage = "zh-CN" | "en-US";

const STORAGE_KEY = "cn-research-ui-language";

const messages = {
  "zh-CN": {
    "language.chinese": "中文",
    "language.english": "English",
    "language.label": "界面语言",
    "brand.name": "A股量化研究平台",
    "brand.tagline": "零预算 · 研究级 · 可复现 · 证据驱动",
    "header.context": "当前研究上下文",
    "header.market": "CN / 沪深日线",
    "header.closeConfirmed": "收盘确认 · Asia/Shanghai",
    "header.strictGate": "严格门禁",
    "banner.research": "研究级公开数据 · 非投资建议 · 不可直接交易 · 免费数据产物永不进入正式发布",
    "banner.formal": "正式模式需要授权数据、SLA、完整历史可见时间和发布审批；任一条件缺失时系统将阻断。",
    "mode.demo": "演示模式",
    "mode.sandbox": "沙盒模式",
    "mode.research": "A股研究模式",
    "mode.real": "正式模式（需授权）",
    "research.eyebrow": "研究",
    "research.title": "证据、价格与报告",
    "research.dataQuality": "1 · 数据质量与资格",
    "research.backendStatus": "后端验收状态",
    "research.data": "数据",
    "research.training": "训练",
    "research.prediction": "预测",
    "research.evidence": "证据",
    "research.blockingReasons": "阻断原因",
    "research.abstainReasons": "拒答原因",
    "research.roster": "2 · 研究模型清单",
    "research.rosterEmpty": "研究清单尚未就绪",
    "research.rosterEmptyBody": "任务保持不可用，不从任意训练目录加载模型。",
    "research.tasks": "3 · 方向、收益与风险",
    "research.notSignal": "非交易信号",
    "research.taskUnavailable": "任务不可用",
    "research.insufficientEvidence": "证据不足，暂不预测",
    "research.waitingEvidence": "等待冻结快照、研究清单和完整哈希证据。",
    "research.influence": "可核验影响事实",
    "research.nonCausal": "这些是模型输入依据，不代表因果关系。",
    "research.shadow": "4 · Shadow 前向验证",
    "research.noShadow": "尚无前向 Shadow 记录",
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
    "hero.eyebrow": "A 股研究工作台",
    "hero.preOpen": "盘前研究",
    "hero.close": "收盘确认研究",
    "hero.title": "让每一个判断，都有数据边界。",
    "hero.body": "免费公开数据驱动的研究概率、风险区间和可复核证据。研究结果不构成投资建议，也不直接用于交易。",
    "hero.asOf": "数据截至",
    "hero.waiting": "等待快照",
    "shadow.frozen": "已冻结",
    "shadow.valid": "有效",
    "shadow.abstain": "暂不判断",
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
    "status.abstain": "暂不判断",
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
    "header.market": "CN / Shanghai & Shenzhen daily bars",
    "header.closeConfirmed": "Close confirmed · Asia/Shanghai",
    "header.strictGate": "Strict gate",
    "banner.research": "Public research data · Not investment advice · Not for direct trading · Free-data outputs never enter formal release",
    "banner.formal": "Formal mode requires licensed data, an SLA, complete historical visibility and release approval. The system blocks when any requirement is missing.",
    "mode.demo": "Demo mode",
    "mode.sandbox": "Sandbox mode",
    "mode.research": "A-share research",
    "mode.real": "Formal mode (licensed)",
    "research.eyebrow": "Research",
    "research.title": "Evidence, price layers and reports",
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
    "hero.eyebrow": "A-share research workbench",
    "hero.preOpen": "Pre-open research",
    "hero.close": "Close-confirmed research",
    "hero.title": "Every judgment has a data boundary.",
    "hero.body": "Research probabilities, risk intervals and reviewable evidence from public data. Results are not investment advice and are not used for direct trading.",
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
    formatDateTime: (value) => value ? new Date(value).toLocaleString(language) : messages[language]["hero.waiting"]
  }), [language]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
