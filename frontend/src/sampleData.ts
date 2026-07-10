import type { EvidenceRecord, PortfolioPayload, ResearchPayload } from "./components/types";

// Demo-only fixture payloads. Live application state should come from real API calls.
export const fallbackPortfolio: PortfolioPayload = {
  holdings: [
    { symbol: "NVDA", name: "NVIDIA", market: "us", sector: "AI 算力", shares: 60, costValue: 49500, marketValue: 70200, weight: 37.5, dayChange: 2.46 },
    { symbol: "TSLA", name: "Tesla", market: "us", sector: "电动车", shares: 90, costValue: 21600, marketValue: 23850, weight: 12.7, dayChange: -1.18 },
    { symbol: "QQQ", name: "Nasdaq 100 ETF", market: "us", sector: "科技指数", shares: 110, costValue: 43800, marketValue: 55200, weight: 29.5, dayChange: 0.74 },
    { symbol: "XLE", name: "Energy Select ETF", market: "us", sector: "能源对冲", shares: 220, costValue: 17600, marketValue: 35100, weight: 18.7, dayChange: -0.42 },
    { symbol: "600519", name: "贵州茅台", market: "cn", sector: "消费龙头", shares: 10, costValue: 16500, marketValue: 15880, weight: 8.5, dayChange: -0.36 },
    { symbol: "510300", name: "沪深300 ETF", market: "cn", sector: "宽基指数", shares: 3000, costValue: 10800, marketValue: 11370, weight: 6.1, dayChange: 0.28 }
  ],
  portfolioCurve: [100, 103, 101, 108, 112, 109, 117, 126, 121, 133, 138, 142],
  portfolioCurveSource: "frontend fallback placeholder",
  sectorExposure: [
    { name: "AI 算力", value: 37.5, color: "#2dbb88" },
    { name: "科技指数", value: 29.5, color: "#5f6fe8" },
    { name: "能源对冲", value: 18.7, color: "#f0a83a" },
    { name: "电动车", value: 12.7, color: "#e45f5f" },
    { name: "消费龙头", value: 8.5, color: "#2f9cbd" },
    { name: "宽基指数", value: 6.1, color: "#9a6ad6" }
  ],
  metrics: {
    marketValue: 201600,
    cost: 159800,
    todayPnl: 1813,
    totalReturn: 26.16,
    topWeight: 37.5
  },
  riskRadar: [
    { label: "集中度", value: 82 },
    { label: "波动率", value: 31 },
    { label: "回撤风险", value: 49 },
    { label: "行业暴露", value: 86 },
    { label: "事件风险", value: 65 }
  ],
  preference: { label: "均衡模式", description: "同时关注收益来源、证据质量、集中度和历史风险分布。" },
  events: [
    { title: "证据链刷新", summary: "行情、财报、新闻、历史类比和模型推断分开记录，并展示有效期。", tone: "good" },
    { title: "经验历史池", summary: "过期证据不会删除，会归档为复盘样本。", tone: "neutral" },
    { title: "前端 fallback", summary: "这组数据只用于 API 不可用时的界面占位，不作为真实投研事实。", tone: "warn" }
  ],
  cacheStatus: { label: "前端 fallback 缓存", asOf: "2026-07-02T00:00:00Z" }
};

const fallbackEvidence: EvidenceRecord[] = [
  {
    id: 1,
    claim: "前端 fallback 行情占位数据，不作为最新市场事实。",
    sourceType: "market_data",
    sourceName: "frontend fallback placeholder",
    observedAt: "2026-07-02T00:00:00Z",
    validUntil: "2026-07-03T00:00:00Z",
    confidence: 0.82,
    isModelInferred: false,
    isExpired: false
  },
  {
    id: 2,
    claim: "财务与估值摘要待真实财报接入；当前为 fallback 占位。",
    sourceType: "financial_report",
    sourceName: "frontend fallback placeholder",
    observedAt: "2026-06-30T00:00:00Z",
    validUntil: "2026-07-07T00:00:00Z",
    confidence: 0.72,
    isModelInferred: false,
    isExpired: false
  },
  {
    id: 3,
    claim: "综合建议由 Agent 基于证据链推断生成，证据过期后必须重算。",
    sourceType: "model_inference",
    sourceName: "Investment Agent Workflow Risk Review Agent",
    observedAt: "2026-07-02T00:00:00Z",
    validUntil: "2026-07-03T00:00:00Z",
    confidence: 0.62,
    isModelInferred: true,
    isExpired: false
  }
];

export const fallbackResearch: ResearchPayload = {
  symbol: "NVDA",
  name: "NVIDIA",
  market: "us",
  riskLabel: "中高风险",
  riskLevel: "high",
  profile: fallbackPortfolio.preference,
  run: {
    runId: "fallback-run",
    riskScore: 82,
    summary: "前端缓存投研 run。",
    startedAt: "2026-07-02T00:00:00Z",
    finishedAt: "2026-07-02T00:00:00Z",
    dataStatus: "fallback"
  },
  documentBlocks: [
    { title: "Agent 综合摘要", text: "Investment Agent Workflow 将行情与资讯收集、财务分析、策略回测、观察池、信号提醒、报告生成和 Judge 审稿拆成独立 Agent/Skill。" },
    { title: "反方观点 / 研究质量审查", text: "当前研究最可能被三类证据推翻: 最新财报指引转弱、行业新闻热度降温、价格快速上涨后进入高波动回撤。Judge 审的是研究严谨性，不评价是否值得买。" },
    { title: "观察建议", text: "建议继续观察关键触发条件，不输出确定性买卖建议。若证据过期，系统应重新生成模型推断。" }
  ],
  agentWorkflow: [
    { role: "行情与资讯收集 Agent", kind: "Agent", status: "fallback", output: "行情、资讯和公告入口进入证据链。" },
    { role: "财务数据分析 Skill", kind: "Skill", status: "needs filing", output: "等待真实财报/公告上传。" },
    { role: "策略回测 Skill", kind: "Skill", status: "demo scenario", output: "历史情景按 asOfDate 截断并提示样本外风险。" },
    { role: "Time-Series Feature Builder Skill", kind: "Skill", status: "missing model", output: "等待结构化行情窗口生成点时特征快照。" },
    { role: "CNN Local Signal Skill", kind: "Skill", status: "not inferred", output: "短期价格/成交量局部形态尚未经过模型推断。" },
    { role: "Transformer Scenario Encoder Skill", kind: "Skill", status: "not inferred", output: "长窗口相似情景向量尚未生成。" },
    { role: "Calibration Validator Skill", kind: "Skill", status: "needs validation", output: "模型校准和样本外验证未完成，结论降级为缺失。" },
    { role: "观察池管理 Agent", kind: "Agent", status: "active", output: "维护观察项、证据有效期和经验历史池。" },
    { role: "信号提醒 Agent", kind: "Agent", status: "armed", output: "监听行情过期、财报窗口、负面新闻和回撤触发器。" },
    { role: "研究报告生成 Agent", kind: "Agent", status: "drafted", output: "生成多模态投研卡片和观察清单。" },
    { role: "LLM Judge 审稿 Agent", kind: "Agent", status: "reviewed", output: "只审研究质量，不判断买卖价值。" }
  ],
  toolCalls: [
    {
      id: 1,
      runId: "fallback-run",
      toolId: "market_snapshot",
      name: "实时行情快照",
      category: "market_data",
      description: "拉取最新价格、涨跌幅和观察时间。",
      freshnessRule: "1 trading day",
      outputContract: "price, day_change, observed_at, source_name, evidence_id",
      symbol: "NVDA",
      input: { symbol: "NVDA", market: "us" },
      outputSummary: "fallback 行情证据槽位已创建，但不能作为最新市场事实。",
      sourceName: "frontend fallback placeholder",
      observedAt: "2026-07-02T00:00:00Z",
      status: "degraded",
      failureReason: "API 不可用时使用前端占位。",
      evidenceId: 1
    },
    {
      id: 2,
      runId: "fallback-run",
      toolId: "research_quality_judge",
      name: "Research Quality Judge",
      category: "judge",
      description: "只审研究严谨性。",
      freshnessRule: "per report run",
      outputContract: "score, verdict, failed_dimensions",
      symbol: "NVDA",
      input: { claimCount: 5 },
      outputSummary: "质量分 49；fallback 证据不足。",
      sourceName: "Research Quality Judge",
      observedAt: "2026-07-02T00:00:00Z",
      status: "success",
      evidenceId: 3
    }
  ],
  documentAnalysis: {
    documentId: "fallback-doc",
    filename: "NVDA-demo-filing.pdf",
    uploadedAt: "2026-07-02T00:00:00Z",
    sourceType: "fallback",
    summary: "多模态解析样例: 文本、表格、图表分离处理，表格指标进入结构化库。",
    blocks: [
      { type: "text", label: "文本块", count: 12, status: "样例" },
      { type: "table", label: "表格块", count: 4, status: "样例" },
      { type: "chart", label: "图表块", count: 3, status: "样例" },
      { type: "footnote", label: "脚注块", count: 2, status: "样例" }
    ],
    metrics: [
      { metric_name: "Revenue growth", metric_value: "demo placeholder", period: "not factual", source_block: "demo table" },
      { metric_name: "Gross margin", metric_value: "demo placeholder", period: "not factual", source_block: "demo table" }
    ],
    chartSummary: "图表摘要占位样例: 上传真实财报前，不生成任何关于收入、利润率或现金流的事实判断。",
    blockPreviews: [
      { block_type: "text", label: "demo text block", locator: "demo:paragraph:1", content_preview: "上传真实财报后展示文本块定位。" },
      { block_type: "table", label: "demo table block", locator: "demo:table:1", content_preview: "上传真实 CSV/PDF/TXT 后展示表格候选定位。" },
      { block_type: "footnote", label: "demo footnote block", locator: "demo:footnote:1", content_preview: "脚注会单独拆出，供 Judge 检查引用是否支撑结论。" }
    ]
  },
  evidenceAudit: {
    score: 49,
    judgeVersion: "v2",
    verdict: "研究质量不足，先补证据",
    scope: "Research Quality Judge 只评价研究是否严谨、证据是否支撑结论，不评价这只股票是否值得买。",
    dimensions: [
      { key: "evidence_sufficiency", label: "证据是否充分", passed: false, severity: "high", detail: "fallback 证据仍包含占位数据，不能作为完整研究证据。" },
      { key: "freshness", label: "信息是否过期", passed: true, severity: "high", detail: "fallback 时间戳仍在演示有效期内。" },
      { key: "financial_metric_sources", label: "财务指标是否有来源", passed: false, severity: "medium", detail: "财务指标来自 demo table，不是上传财报/公告的结构化来源。" },
      { key: "backtest_out_of_sample_warning", label: "策略回测是否有样本外风险提示", passed: true, severity: "medium", detail: "历史类比说明非预测和 asOfDate 截断。" },
      { key: "fact_inference_boundary", label: "结论是否混淆事实和推断", passed: true, severity: "high", detail: "事实和模型推断已分开记录。" },
      { key: "bear_case", label: "是否缺少反方观点", passed: true, severity: "medium", detail: "报告包含反方观点和推翻条件。" },
      { key: "claim_level_support", label: "结论是否有 claim 级证据图谱", passed: false, severity: "high", detail: "2 条 claim 被 fallback 证据反驳，报告必须降级。" },
      { key: "ml_model_quality", label: "时序模型是否样本外验证与校准", passed: false, severity: "medium", detail: "fallback 状态下没有可用 modelId 和 valid calibration。" },
      { key: "pit_feature_store", label: "是否通过 Point-in-Time Feature Store 检查", passed: false, severity: "high", detail: "fallback 没有字段级 PIT 元数据。" },
      { key: "risk_distribution_engine", label: "是否输出风险分布而非涨跌预测", passed: false, severity: "high", detail: "fallback 没有风险分布引擎输出。" },
      { key: "calibration_backtest_validator", label: "是否完成校准与回测验证", passed: false, severity: "high", detail: "fallback 没有校准/回测指标。" },
      { key: "token_compression_report", label: "是否量化 Agent token 压缩", passed: false, severity: "medium", detail: "fallback 没有 token 压缩报告。" },
      { key: "source_attribution_v2", label: "Judge v2 是否检查引用来源", passed: true, severity: "high", detail: "fallback evidence 仍保留来源字段。" },
      { key: "probabilistic_language_v2", label: "Judge v2 是否禁止确定性预测表达", passed: true, severity: "high", detail: "fallback 未输出确定性涨跌。" }
    ],
    findings: [
      { severity: "high", title: "证据是否充分", detail: "fallback 证据仍包含占位数据，不能作为完整研究证据。" },
      { severity: "medium", title: "财务指标是否有来源", detail: "财务指标来自 demo table，不是上传财报/公告的结构化来源。" }
    ],
    authoritySources: [
      { name: "SEC EDGAR", url: "https://www.sec.gov/edgar/search/", authority: "regulator", status: "权威检索入口" },
      { name: "Company IR", url: "https://www.google.com/search?q=NVDA+investor+relations", authority: "company_ir", status: "公司 IR 检索" }
    ],
    checks: [
      { name: "证据是否充分", passed: false },
      { name: "信息是否过期", passed: true },
      { name: "财务指标是否有来源", passed: false },
      { name: "策略回测是否有样本外风险提示", passed: true },
      { name: "结论是否混淆事实和推断", passed: true },
      { name: "是否缺少反方观点", passed: true },
      { name: "结论是否有 claim 级证据图谱", passed: false },
      { name: "时序模型是否样本外验证与校准", passed: false }
    ],
    v2Checks: {
      noFutureData: false,
      outOfSampleValidation: false,
      calibration: false,
      sourceAttribution: true,
      probabilisticLanguage: true,
      bearCase: true
    }
  },
  evidenceGraph: {
    summary: "5 条核心 claim，3 条需要补证据或降级。",
    claims: [
      {
        id: "market_today_pnl",
        title: "今日收益口径",
        claim: "今日收益只能由有效行情快照和持仓份额计算得出。",
        status: "contested",
        supportingEvidenceIds: [],
        rebuttingEvidenceIds: [1],
        derivedMetrics: ["marketValue", "dayChange", "todayPnl"],
        dependsOnExpiredEvidenceIds: [],
        judgeNote: "fallback 行情不能当作实时价格事实。"
      },
      {
        id: "financial_quality",
        title: "财务指标来源",
        claim: "财务指标必须来自上传财报/公告中的结构化表格块。",
        status: "contested",
        supportingEvidenceIds: [],
        rebuttingEvidenceIds: [2],
        derivedMetrics: ["metrics_pending"],
        dependsOnExpiredEvidenceIds: [],
        judgeNote: "demo table 不能作为事实来源。"
      },
      {
        id: "report_conclusion_boundary",
        title: "报告结论边界",
        claim: "报告只能给研究质量和观察建议，不能输出确定性买卖结论。",
        status: "supported",
        supportingEvidenceIds: [3],
        rebuttingEvidenceIds: [],
        derivedMetrics: ["judgeScore", "riskScore", "verdict"],
        dependsOnExpiredEvidenceIds: [],
        judgeNote: "结论边界清晰。"
      }
    ],
    edges: [
      { from: "evidence:1", to: "claim:market_today_pnl", relation: "rebuts", label: "反驳/降级" },
      { from: "metric:todayPnl", to: "claim:market_today_pnl", relation: "derived", label: "计算派生" },
      { from: "evidence:3", to: "claim:report_conclusion_boundary", relation: "supports", label: "支持" }
    ],
    expiredEvidenceIds: []
  },
  reportRevisionLoop: {
    draftStatus: "initial_report_generated",
    judgeVerdict: "研究质量不足，先补证据",
    toolBackfillActions: ["补证据或降级: 证据是否充分", "补证据或降级: 财务指标是否有来源"],
    degradedClaims: ["market_today_pnl", "financial_quality"],
    finalStatus: "data_insufficient",
    revisedSummary: "审计未通过，修订稿降级为数据不足说明，只保留观察项和补证据任务。",
    blockedBy: ["证据是否充分", "结论是否有 claim 级证据图谱"]
  },
  mlRiskSummary: {
    modelStatus: "missing",
    calibrationStatus: "missing",
    summary: "时序模型尚未生成有效推断，Research Quality Judge 必须降级模型结论。",
    featureStoreAudit: { ok: false, status: "missing", checkedFieldCount: 0, futureLeakageCount: 0, violations: ["no point-in-time features"] },
    validationMetrics: {},
    similarScenarios: []
  },
  tokenCompressionReport: {
    symbol: "NVDA",
    rawTokenEstimate: 0,
    structuredTokenEstimate: 0,
    tokenReductionPercent: 0,
    rawBreakdown: {},
    structuredBreakdown: {},
    conclusionConsistency: 0,
    consistencyChecks: [{ name: "fallback_missing", passed: false, detail: "等待后端生成 token 压缩报告。" }],
    method: "fallback",
    summary: "尚未生成 Agent token 压缩报告。"
  },
  conditionAlignment: {
    summary: "历史类比从价格形态升级为条件对齐。",
    matchedScenarioCount: 2,
    factors: [
      { factor: "20日涨幅", current: "高", historical: "高", matched: true },
      { factor: "估值分位", current: "高位", historical: "高位", matched: true },
      { factor: "市场状态", current: "震荡偏强", historical: "利率敏感阶段", matched: false }
    ]
  },
  preferenceWeights: [
    { factor: "证据质量", weight: 22 },
    { factor: "回撤", weight: 18 },
    { factor: "集中度", weight: 16 }
  ],
  reportSettings: { frequency: "weekly", updatedAt: "2026-07-02T00:00:00Z", description: "每周生成一次投研巡检报告" },
  reportVersions: {
    delta: { hasPrevious: false, riskScoreDelta: 0, summary: "暂无上一版报告。" },
    recentRuns: []
  },
  debate: {
    bull: ["行业叙事和历史类比支持继续观察。"],
    bear: ["估值和财报指引变化可能推翻当前判断。"],
    judge: { stance: "中立观察", detail: "Research Quality Judge 只审研究严谨性，不判断买卖价值；保留反方触发条件，证据过期后重新生成。" },
    invalidators: ["财报指引低于预期", "权威公告与模型解释冲突"]
  },
  observationChecklist: [
    { item: "刷新行情数据", trigger: "行情证据超过 1 个交易日", frequency: "daily", status: "自动巡检" },
    { item: "复核财报/公告", trigger: "财报窗口前后 7-14 天", frequency: "event", status: "待观察" }
  ],
  evidence: fallbackEvidence,
  historicalAnalogies: [
    { asOfDate: "2024-03-01", pattern: "估值高位 + 财报前窗口 + 新闻热度升温 + 价格快速上涨", similarity: 0.86, return1w: -2.4, return1m: 6.8, return3m: 18.2, maxDrawdown: -11.6, note: "按 asOfDate 截断，仅使用当时已公开的信息。" },
    { asOfDate: "2025-02-14", pattern: "价格加速上涨 + 行业叙事拥挤", similarity: 0.79, return1w: 3.1, return1m: -4.9, return3m: 9.4, maxDrawdown: -13.2, note: "历史类比仅用于风险分布，不构成预测。" }
  ],
  priceSeries: Array.from({ length: 24 }, (_, index) => ({ date: `M${index + 1}`, close: 100 + index * 2 + Math.sin(index / 2) * 8, volume: 1000000 + index * 12000 })),
  experienceHistory: [
    { id: 1, symbol: "NVDA", archived_claim: "旧模型推断因行情证据过期归档。", source_type: "model_inference", observed_at: "2026-06-30T00:00:00Z", archived_at: "2026-07-01T00:00:00Z", reason: "valid_until elapsed" }
  ]
};
