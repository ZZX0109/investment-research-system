import { Ban, BrainCircuit, CheckCircle2, FileCheck2, Play, ScanSearch, ShieldAlert, Sparkles } from "lucide-react";
import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { useAssetsQuery, useCreateAgentRunMutation, useLatestResearchPredictionQuery, usePriceSeriesQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";
import type { AgentRun, LatestResearchPrediction, LLMProviderProfile, LLMCredentialSummary, PriceSeries } from "../../api/types";

const nodes = [
  "task_intake", "task_classification", "plan_generation", "tool_selection",
  "evidence_collection", "structured_feature_build", "model_inference",
  "counter_evidence_search", "self_audit", "repair_or_abstain", "report_generation"
];

export function AgentExecutionPanel() {
  const { l, term } = useI18n();
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const mode = useWorkbenchStore((state) => state.mode);
  const assets = useAssetsQuery();
  const run = useCreateAgentRunMutation();
  const selectedAsset = assets.data?.find((asset) => asset.id === assetId);
  const priceSeries = usePriceSeriesQuery(assetId);
  const latestResearch = useLatestResearchPredictionQuery(selectedAsset?.ticker, "drawdown_20d");
  const taskResults = {
    direction_1d: useLatestResearchPredictionQuery(selectedAsset?.ticker, "direction_1d"),
    direction_5d: useLatestResearchPredictionQuery(selectedAsset?.ticker, "direction_5d"),
    return_20d: useLatestResearchPredictionQuery(selectedAsset?.ticker, "return_20d"),
  };
  const agentResult = run.data;
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const isAnyResearchFetching = latestResearch.isFetching || Object.values(taskResults).some((query) => query.isFetching);
  const activeIndex = agentResult?.current_node ? nodes.indexOf(agentResult.current_node) : -1;

  return (
    <Panel
      eyebrow={l("研究结果", "Research result")}
      title={l("今日研究概览", "Today's research overview")}
      actions={(
        <div className="panel-actions">
        <button
          className="icon-button icon-button--primary"
          type="button"
          disabled={!assetId || run.isPending || isAnyResearchFetching}
          onClick={() => {
            setRefreshMessage(l("正在读取四项最新研究结果…", "Refreshing the four research tasks..."));
            void Promise.all([
              latestResearch.refetch(),
              ...Object.values(taskResults).map((query) => query.refetch()),
            ]).then(() => setRefreshMessage(l("研究结果已更新。参考读数会同时显示数据质量和模型分歧。", "Research results updated. Reference readings include data quality and model disagreement."))).catch(() => setRefreshMessage(l("刷新失败，请稍后重试", "Refresh failed; try again later.")));
          }}
        >
          <Play size={16} aria-hidden="true" />
          <span>
            {isAnyResearchFetching ? l("正在读取…", "Loading...") : l("刷新今日研究", "Refresh today's research")}
          </span>
        </button>
        <button
          className="ghost-button"
          type="button"
          disabled={!assetId}
          onClick={() => document.getElementById("research-assistant")?.scrollIntoView({ behavior: "smooth", block: "start" })}
        ><Sparkles size={15} aria-hidden="true" /> {l("AI 解读当前结果", "Explain with AI")}</button>
        </div>
      )}
    >
      <div className="research-dashboard-intro">
        <div className="research-dashboard-intro__status">
          <span className="eyebrow">{l("当前研究结论", "Current research conclusion")}</span>
          <strong>{!selectedAsset ? l("请选择一个研究对象", "Select a research asset") : latestResearch.data?.status === "abstain" && latestResearch.data.diagnostic_output ? l("谨慎观察", "Observe cautiously") : latestResearch.data?.status === "abstain" ? l("等待足够研究数据", "Awaiting enough research data") : latestResearch.data?.status === "research_only" ? l("研究参考已就绪", "Research reference available") : l("尚无可用结果", "No usable result")}</strong>
        </div>
        <p>{!selectedAsset ? l("在左侧选择股票或 ETF，仪表盘会显示该标的的收盘后研究结果。", "Select a stock or ETF on the left to view its post-close research result.") : latestResearch.data?.status === "abstain" ? l(`参考读数仍会完整展示；当前模型意见存在分歧，请把它作为观察线索，而不是单一结论。`, `Reference readings remain visible; model views differ, so use them as observation cues rather than one definitive conclusion.`) : l("这里先用通俗语言说明近期风险和需要观察的证据；专业数值可在卡片内展开。", "This view first explains near-term risk and evidence to watch in plain language; expand each card for technical values.")}</p>
      </div>
      {refreshMessage ? <p className="research-refresh-feedback" role="status">{refreshMessage}</p> : null}
      <ResearchTaskGrid results={{ ...taskResults, drawdown_20d: latestResearch }} />
      <ResearchPriceChart series={priceSeries.data} />
      <details className="research-technical-details">
        <summary>{l("查看研究流程和技术说明", "View research workflow and technical details")}</summary>
        <div className="agent-purpose">
          <p>{l("系统读取每日收盘后冻结的数据，分别计算方向、收益与回撤，并保留每个读数的来源和质量说明。", "The system reads data frozen after each close, calculates direction, return and drawdown separately, and retains source and quality context for every reading.")}</p>
          <div className="agent-purpose__steps">
          <div>
            <ScanSearch size={17} aria-hidden="true" />
            <span><strong>{l("核验证据", "Verify evidence")}</strong>{l("冻结数据时间，收集当时可见的行情与证据。", "Freeze the cutoff and collect evidence visible at that time.")}</span>
          </div>
          <div>
            <ShieldAlert size={17} aria-hidden="true" />
            <span><strong>{l("评估风险", "Assess risk")}</strong>{l("构建特征、运行风险模型，并寻找相反证据。", "Build features, run the risk model, and search for contrary evidence.")}</span>
          </div>
          <div>
            <FileCheck2 size={17} aria-hidden="true" />
            <span><strong>{l("呈现参考", "Present references")}</strong>{l("展示读数和区间，同时说明数据日期与仍需观察的条件。", "Show readings and ranges, alongside data dates and conditions that still need monitoring.")}</span>
          </div>
          </div>
        </div>
      </details>
      <ResearchRiskInputOutput
        result={latestResearch.data}
        isLoading={latestResearch.isFetching}
        ticker={selectedAsset?.ticker}
      />
      {/* Legacy non-research run rendering is retained below for backwards-compatible routes. */}
      {false && (
        <>
      {!["research", "real"].includes(mode) ? <InlineNotice tone="warn" title={l("非权威模式", "Non-authoritative mode")} body={l("本次固定数据运行与正式研究证据隔离。", "This seeded run remains isolated from research evidence.")} /> : null}
      {run.error ? <InlineNotice tone="error" title={l("智能研究失败", "Agent failed")} body={run.error.message} /> : null}
      {agentResult ? (
        <>
          <div className="metric-strip">
            <Metric label={l("状态", "State")} value={term(agentResult.state)} />
            <Metric label={l("门禁", "Gate")} value={term(agentResult.verdict ?? "pending")} />
            <Metric label={l("模型调用", "LLM")} value={`${agentResult.budget.llm_calls_used}/${agentResult.budget.max_llm_calls}`} />
            <Metric label={l("工具调用", "Tools")} value={`${agentResult.budget.tool_calls_used}/${agentResult.budget.max_tool_calls}`} />
          </div>
          <details className="agent-technical-details">
            <summary>{l("查看执行步骤与技术状态", "View execution steps and technical status")}</summary>
            <div className="agent-node-grid" aria-label={l("智能研究执行步骤", "Agent execution nodes")}>
              {nodes.map((node, index) => {
                const completed = agentResult.state === "completed" || agentResult.state === "abstained" || index < activeIndex;
                const stopped = agentResult.state === "abstained" && index > activeIndex;
                return (
                  <div className={`agent-node agent-node--${stopped ? "stopped" : completed ? "complete" : index === activeIndex ? "active" : "pending"}`} key={node}>
                    {stopped ? <Ban size={14} /> : completed ? <CheckCircle2 size={14} /> : index === activeIndex ? <BrainCircuit size={14} /> : <span className="status-dot" />}
                    <span>{term(node)}</span>
                  </div>
                );
              })}
            </div>
          </details>
          {agentResult.abstain_reason ? (
            <InlineNotice tone="warn" title={l("证据不足，暂不生成结论", "Insufficient evidence; no conclusion generated")} body={agentResult.abstain_reason} />
          ) : agentResult.report_id ? (
            <InlineNotice tone="info" title={l("固定报告已生成", "Fixed report created")} body={l(`报告 ${agentResult.report_id} 已绑定研究运行 ${agentResult.research_run_id}。`, `Report ${agentResult.report_id} is bound to research run ${agentResult.research_run_id}.`)} />
          ) : null}
          <div className="agent-run-footer"><ShieldAlert size={14} /> {l("关联标识", "Correlation")} {agentResult.correlation_id}</div>
        </>
      ) : <p className="muted">{l("先在左侧选择研究对象，再点击“生成风险研究”。结果会显示风险状态、门禁结论、固定报告或拒答原因。", "Select an asset on the left, then choose “Generate risk research”. The result will show risk status, gate outcome, a fixed report, or the abstain reason.")}</p>}
        </>
      )}
    </Panel>
  );
}

type ResearchTaskKey = "direction_1d" | "direction_5d" | "return_20d" | "drawdown_20d";

function ResearchTaskGrid({ results }: { results: Record<ResearchTaskKey, ReturnType<typeof useLatestResearchPredictionQuery>> }) {
  const { l, term } = useI18n();
  const labels: Record<ResearchTaskKey, string> = {
    direction_1d: l("1 日方向", "1D direction"),
    direction_5d: l("5 日方向", "5D direction"),
    return_20d: l("20 日收益区间", "20D return range"),
    drawdown_20d: l("20 日回撤风险", "20D drawdown risk"),
  };
  return <div className="research-task-grid" aria-label={l("研究任务概览", "Research task overview")}>
    {(Object.keys(labels) as ResearchTaskKey[]).map((task) => {
      const query = results[task];
      const result = query.data;
      const output = result?.output ?? result?.diagnostic_output;
      const isDiagnostic = result?.status === "abstain";
      const direction = output?.calibrated_probability && typeof output.calibrated_probability === "object" ? output.calibrated_probability : undefined;
      const probability = typeof output?.calibrated_probability === "number" ? output.calibrated_probability : output?.raw_probability;
      const statusLabel = result?.status === "research_only" ? l("研究参考", "Research reference") : result?.status === "abstain" && result.diagnostic_output ? l("谨慎参考", "Cautious reference") : result?.status === "abstain" ? l("数据待补充", "Data pending") : l("暂不可用", "Unavailable");
      return <article className={`research-task-card research-task-card--${result?.status ?? "unavailable"}`} key={task}>
        <div className="research-task-card__head"><strong>{labels[task]}</strong><span className="tag">{statusLabel}</span></div>
        {task.startsWith("direction") && direction ? (
          <>
            <div className="research-task-card__plain"><b>{direction.up != null && direction.up > (direction.down ?? 0) ? l("近期走势偏强", "Near-term trend is firmer") : direction.down != null && direction.down > (direction.up ?? 0) ? l("近期走势偏弱", "Near-term trend is softer") : l("近期走势分歧较大", "Near-term views are mixed")}</b><span>{l("仅作短期观察，不代表长期上涨判断。", "For short-term observation only; not a long-term return view.")}</span></div>
            <details className="research-task-card__technical"><summary>{l("查看专业数值", "View technical values")}</summary><div className="research-task-card__value"><b>{l("上涨", "Up")} {Math.round((direction.up ?? 0) * 100)}%</b><span>{l("下跌", "Down")} {Math.round((direction.down ?? 0) * 100)}% · {l("横盘", "Flat")} {Math.round((direction.flat ?? 0) * 100)}%</span></div></details>
          </>
        ) : null}
        {task === "return_20d" && output?.p10 != null ? (
          <>
            <div className="research-task-card__plain"><b>{output.p50 != null && output.p50 >= 0 ? l("近期收益倾向偏正", "Near-term return tendency is positive") : l("近期收益倾向偏弱", "Near-term return tendency is softer")}</b><span>{l("这是超短期研究参考，不等于长期回报承诺。", "A short-horizon research reference, not a long-term return promise.")}</span></div>
            <details className="research-task-card__technical"><summary>{l("查看专业区间", "View technical range")}</summary><div className="research-task-card__value"><b>P50 {formatPercent(output.p50)}</b><span>P10 {formatPercent(output.p10)} · P90 {formatPercent(output.p90)}</span></div></details>
          </>
        ) : null}
        {task === "drawdown_20d" && probability != null ? (
          <>
            <div className="research-task-card__plain"><b>{probability >= 0.65 ? l("近期波动风险偏高", "Near-term volatility risk is elevated") : probability >= 0.4 ? l("近期波动风险需要观察", "Near-term volatility risk needs watching") : l("近期波动风险暂未偏高", "Near-term volatility risk is not elevated")}</b><span>{l("请结合数据日期、模型分歧和后续公告理解。", "Consider the data date, model disagreement and later announcements.")}</span></div>
            <details className="research-task-card__technical"><summary>{l("查看专业概率", "View technical probability")}</summary><div className="research-task-card__value"><b>{Math.round(probability * 100)}%</b><span>{term(output?.risk_level ?? "unavailable")} {isDiagnostic ? l("候选值", "candidate") : ""}</span></div></details>
          </>
        ) : null}
        {!output || (isDiagnostic && !direction && probability == null && task !== "return_20d") ? <p className="research-task-card__reason">{result?.abstain_reasons?.[0] ? explainReason(result.abstain_reasons[0], l) : l("当前没有可展示的研究产物。", "No research artifact is available.")}</p> : null}
        {isDiagnostic ? <small>{l("数据质量或模型意见仍有差异；以上保留为可追溯的参考读数。", "Data quality or model views still differ; this remains a traceable reference reading.")}</small> : null}
        {result?.confidence_tier ? <small>{l("模型读数差异", "Model reading spread")}: {readingSpreadLabel(result.confidence_tier, l)}</small> : null}
      </article>;
    })}
  </div>;
}

function formatPercent(value?: number) {
  return value == null ? "n/a" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function explainReason(reason: string, l: (zh: string, en: string) => string) {
  if (reason.includes("disagreement")) return l("不同模型给出的结果差异过大", "Models disagree too much");
  if (reason.includes("roster")) return l("尚未生成对应任务的研究清单", "Task research roster is missing");
  return reason.replaceAll("_", " ");
}

function ResearchPriceChart({ series }: { series?: PriceSeries[] }) {
  const { l } = useI18n();
  const assetSeries = series?.find((item) => item.series_role === "asset") ?? series?.[0];
  const points = assetSeries?.points?.slice(-90) ?? [];
  if (!points.length) {
    return <InlineNotice title={l("暂无价格图表", "No price chart yet")} tone="warn" body={l("当前没有可用于绘图的带时间戳日线。请先刷新研究数据或选择研究池中的标的。", "No timestamped daily prices are available. Refresh research data or select an asset in the research cohort.")} />;
  }
  const start = points[0].close;
  let peak = start;
  const chart = points.map((point) => {
    peak = Math.max(peak, point.close);
    return {
      date: point.timestamp.slice(0, 10),
      returnPct: ((point.close / start) - 1) * 100,
      drawdownPct: ((point.close / peak) - 1) * 100,
    };
  });
  return <section className="research-price-chart" aria-label={l("价格与回撤图", "Price and drawdown chart")}>
    <div className="research-price-chart__head"><div><strong>{l("价格走势与回撤", "Price trend and drawdown")}</strong><span>{l("最近 90 个交易日", "Last 90 sessions")}</span></div><span className="tag">{assetSeries?.status ?? l("研究数据", "research data")}</span></div>
    <div className="research-price-chart__canvas">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chart} margin={{ top: 8, right: 10, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#e7edf6" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" minTickGap={32} tick={{ fontSize: 10, fill: "#7b8aa2" }} />
          <YAxis unit="%" width={42} tick={{ fontSize: 10, fill: "#7b8aa2" }} />
          <Tooltip formatter={(value) => [`${Number(value).toFixed(2)}%`]} />
          <Line type="monotone" dataKey="returnPct" name={l("累计收益", "Cumulative return")} stroke="#2563eb" dot={false} strokeWidth={2.4} />
          <Line type="monotone" dataKey="drawdownPct" name={l("回撤", "Drawdown")} stroke="#d97772" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  </section>;
}

function LLMProviderSettings({
  profiles,
  credentials,
  draft,
  setDraft,
  mutation,
  assistantRun,
  toolCalls,
  assistantBusy,
  onRunAssistant,
}: {
  profiles: LLMProviderProfile[];
  credentials: LLMCredentialSummary[];
  draft: { name: string; protocol: "openai_compatible"; endpoint: string; model: string; credentialId: string; secret: string };
  setDraft: Dispatch<SetStateAction<typeof draft>>;
  mutation: { isPending: boolean; isSuccess: boolean; error: Error | null; mutate: (payload: { profile: Omit<LLMProviderProfile, "id" | "owner_user_id" | "created_at" | "updated_at">; profileId?: string; credential?: { id: string; label: string; secret: string } }) => void };
  assistantRun?: AgentRun;
  toolCalls: Array<{ tool_id: string; state: "completed" | "failed"; input_hash: string }>;
  assistantBusy: boolean;
  onRunAssistant: (() => void) | null;
}) {
  const { l } = useI18n();
  return <details className="llm-provider-settings">
    <summary>{l("配置研究助手大模型（可选）", "Configure research assistant LLM (optional)")}</summary>
    <p className="muted">{l("大模型只负责证据整理和报告叙述，不替代数值风险模型。Key 会保存到加密凭证库，页面只显示末四位。", "The LLM organizes evidence and narrative; it does not replace numerical risk models. Keys are stored in the encrypted vault and only the last four characters are shown.")}</p>
    <div className="llm-provider-settings__current">
      <span>{l("当前配置", "Current")}</span>
      <strong>{profiles.find((profile) => profile.enabled)?.name ?? l("未配置，使用本地确定性模式", "Not configured; deterministic local mode")}</strong>
      <span className="tag">{credentials.length} {l("个已保存 Key", "saved keys")}</span>
    </div>
    <div className="llm-provider-settings__assist">
      <div>
        <strong>{l("AI 辅助解读", "AI-assisted explanation")}</strong>
        <p>{l("让你配置的大模型调用受控投研函数，整理冻结证据、模型输出和质量门禁。它不能访问任意网址、修改数据或给出买卖指令。", "Your configured model calls constrained research functions to organize frozen evidence, model output, and quality gates. It cannot browse arbitrary URLs, alter data, or issue trading instructions.")}</p>
      </div>
      <button className="ghost-button" type="button" disabled={assistantBusy || !onRunAssistant} onClick={onRunAssistant}>
        {assistantBusy ? l("正在调用研究工具…", "Calling research tools...") : l("生成 AI 研究解读", "Generate AI research explanation")}
      </button>
    </div>
    {!onRunAssistant ? <p className="muted">{l("请先保存并启用一个兼容 Function Calling 的模型配置，再选择研究对象。", "Save and enable a function-calling-compatible model, then select a research asset.")}</p> : null}
    {assistantRun ? <p className="llm-provider-settings__success">{l("最近一次 AI 解读", "Latest AI explanation")}: {assistantRun.state} · {l("模型调用", "LLM calls")} {assistantRun.budget.llm_calls_used}/{assistantRun.budget.max_llm_calls} · {l("工具调用", "Tool calls")} {assistantRun.budget.tool_calls_used}/{assistantRun.budget.max_tool_calls}{assistantRun.abstain_reason ? ` · ${assistantRun.abstain_reason}` : ""}</p> : null}
    {toolCalls.length ? <div className="llm-tool-trace" aria-label={l("投研函数调用记录", "Research function-call trace")}>
      <strong>{l("本次调用的投研函数", "Research functions called")}</strong>
      {toolCalls.map((call) => <span className={`tag llm-tool-trace__item llm-tool-trace__item--${call.state}`} key={call.input_hash + call.tool_id}>{call.tool_id} · {call.state}</span>)}
    </div> : null}
    <div className="llm-provider-settings__form">
      <label><span>{l("名称", "Name")}</span><input value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
      <label><span>{l("协议", "Protocol")}</span><select value={draft.protocol} onChange={(event) => setDraft((current) => ({ ...current, protocol: event.target.value as "openai_compatible" }))}><option value="openai_compatible">OpenAI 兼容</option></select></label>
      <label><span>Endpoint</span><input value={draft.endpoint} onChange={(event) => setDraft((current) => ({ ...current, endpoint: event.target.value }))} /></label>
      <label><span>Model</span><input value={draft.model} onChange={(event) => setDraft((current) => ({ ...current, model: event.target.value }))} /></label>
      <label><span>Key ID</span><input value={draft.credentialId} onChange={(event) => setDraft((current) => ({ ...current, credentialId: event.target.value }))} /></label>
      <label><span>API Key</span><input type="password" value={draft.secret} placeholder={l("输入后保存，页面不会回显完整 Key", "Enter to save; the full key is never shown")} onChange={(event) => setDraft((current) => ({ ...current, secret: event.target.value }))} /></label>
    </div>
    <button className="ghost-button" type="button" disabled={mutation.isPending || !draft.secret || !draft.endpoint || !draft.model} onClick={() => mutation.mutate({ profile: { name: draft.name, protocol: draft.protocol, endpoint: draft.endpoint, model: draft.model, credential_ref: draft.credentialId, timeout_seconds: 20, context_limit: 32000, fallback_profile_id: null, enabled: true }, profileId: profiles.find((profile) => profile.enabled)?.id, credential: { id: draft.credentialId, label: draft.name, secret: draft.secret } })}>{mutation.isPending ? l("保存中…", "Saving...") : l("保存并启用研究助手", "Save and enable research assistant")}</button>
    {mutation.isSuccess ? <p className="llm-provider-settings__success">{l("配置已保存。下一次智能研究将使用该 Provider。", "Saved. The next agent run will use this provider.")}</p> : null}
    {mutation.error ? <p className="llm-provider-settings__error">{mutation.error.message}</p> : null}
  </details>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><div className="eyebrow">{label}</div><div className="metric-card__value">{value}</div></div>;
}

function ResearchRiskInputOutput({
  result,
  isLoading,
  ticker
}: {
  result?: LatestResearchPrediction;
  isLoading: boolean;
  ticker?: string;
}) {
  const { l, term } = useI18n();
  if (!ticker) {
    return <InlineNotice title={l("尚未选择研究对象", "No research asset selected")} body={l("请先在左侧选择一个研究对象。", "Select a research asset on the left first.")} />;
  }
  if (isLoading && !result) {
    return <p className="muted">{l("正在读取冻结的 Research PIT 结果…", "Loading the frozen Research PIT result...")}</p>;
  }
  if (!result) {
    return <InlineNotice title={l("尚无研究结果", "No research result yet")} body={l("点击“查看最新研究结果”读取该标的的冻结结果。", "Choose “View latest research result” to load the frozen result for this asset.")} />;
  }
  if (!result.input) {
    return (
      <InlineNotice
        tone="warn"
        title={l("当前标的不在冻结研究池中", "Asset is outside the frozen research cohort")}
        body={l(
          `当前选择 ${ticker}，本次冻结结果支持：${result.supported_symbols.join("、") || "无"}。系统没有为当前标的伪造输入或预测。`,
          `Selected: ${ticker}. This frozen run supports: ${result.supported_symbols.join(", ") || "none"}. No input or prediction was fabricated for this asset.`
        )}
      />
    );
  }
  const probability = result.output?.calibrated_probability ?? result.output?.raw_probability;
  const candidate = result.diagnostic_output ?? result.output;
  const candidateProbability = typeof candidate?.calibrated_probability === "number"
    ? candidate.calibrated_probability
    : candidate?.raw_probability;
  const publishedProbability = typeof probability === "number" ? probability : undefined;
  const displayProbability = candidateProbability ?? publishedProbability;
  const disagreement = result.model?.model_disagreement;
  const riskTendency = displayProbability == null
    ? l("暂无法评估", "Not enough data")
    : displayProbability >= 0.65
      ? l("风险偏高", "Elevated risk")
      : displayProbability >= 0.4
        ? l("风险中等", "Moderate risk")
        : l("风险相对较低", "Relatively lower risk");
  const readingSpread = disagreement == null
    ? l("待确认", "Pending")
    : disagreement >= 0.35
      ? l("差异较大", "Wide spread")
      : disagreement >= 0.2
        ? l("差异中等", "Moderate spread")
        : l("差异较小", "Narrow spread");
  const abstainExplanation = explainResearchAbstention(
    [...result.abstain_reasons, ...result.blocking_reasons],
    result.model?.model_disagreement,
    l,
  );
  return (
    <div className="research-risk-io" data-testid="research-risk-input-output">
      <details className="research-input-details">
        <summary>{l("查看本次计算使用的数据", "View data used in this calculation")}</summary>
        <section>
          <div className="story-card__header">
            <strong>{l("数据来源与完整度", "Data source and completeness")}</strong>
            <span className="tag">{result.input.trade_date ?? l("未知日期", "unknown date")}</span>
          </div>
          <div className="metric-strip">
            <Metric label={l("标的", "Symbol")} value={result.symbol} />
            <Metric label={l("收盘价", "Close")} value={result.input.prediction_price?.toFixed(2) ?? "n/a"} />
            <Metric label={l("核心数据完整度", "Core coverage")} value={`${Math.round((result.input.core_feature_coverage ?? 0) * 100)}%`} />
            <Metric label={l("事件信息", "Events")} value={term(result.input.event_coverage_status ?? "unsupported")} />
          </div>
          <p className="muted">
            {l("数据源", "Provider")}: {result.input.provider_chain.join(" → ") || term("unavailable")} ·
            {l(" 缓存", " cache")}: {term(result.input.cache_state ?? "unavailable")} ·
            {l(" 数据状态", " data status")}: {term(result.input.data_status ?? "unavailable")}
          </p>
        </section>
      </details>
      <section>
        <div className="story-card__header">
          <strong>{l("研究参考与观察建议", "Research reference and what to watch")}</strong>
          <span className="tag">{result.status === "research_only" ? l("研究参考", "Research reference") : l("谨慎参考", "Cautious reference")}</span>
        </div>
        {displayProbability != null ? (
          <>
            <div className="research-result-summary">
              <span>{l("未来 20 个交易日", "Next 20 trading days")}</span>
              <strong>{riskTendency}</strong>
              <p>
                {l(
                  `${riskTendency}。${
                    disagreement != null && disagreement >= 0.25
                      ? "不同模型读数差异较大，建议结合下一次收盘数据继续观察。"
                      : "当前模型读数相对接近，但仍应结合价格走势、数据日期和后续信息观察。"
                  }这只是未来 20 个交易日的风险参考，不代表长期经营或收益结论。`,
                  `${riskTendency}. ${
                    disagreement != null && disagreement >= 0.25
                      ? "Models differ materially; review again after the next close."
                      : "Models are relatively aligned, but monitor subsequent prices, data dates and evidence."
                  } This is a next-20-session risk reference, not a long-term business or return conclusion.`,
                )}
              </p>
            </div>
            <details className="research-technical-details">
              <summary>{l("查看专业数值与模型分歧", "View technical value and model disagreement")}</summary>
              <div className="research-result-metrics">
                <Metric label={l("参考概率", "Reference probability")} value={`${Math.round(displayProbability * 100)}%`} />
                <Metric label={l("风险倾向", "Risk tendency")} value={riskTendency} />
                <Metric label={l("模型读数差异", "Model reading spread")} value={readingSpread} />
              </div>
            </details>
            <div className="research-scenario-grid">
              <div className="research-scenario research-scenario--optimistic">
                <span>{l("较乐观情景", "More optimistic scenario")}</span>
                <strong>{l("波动回落，风险可能改善", "Risk may improve if volatility eases")}</strong>
                <small>{l("若价格企稳、成交波动收敛，回撤风险可能低于当前参考值。", "If price stabilizes and trading volatility contracts, drawdown risk may fall below the current reading.")}</small>
              </div>
              <div className="research-scenario research-scenario--pessimistic">
                <span>{l("较悲观情景", "More pessimistic scenario")}</span>
                <strong>{l("高波动延续，回撤风险可能上升", "Persistent volatility may raise drawdown risk")}</strong>
                <small>{l("若价格继续走弱或出现负面信息，明显回撤的概率可能高于当前参考值。", "If price weakens further or negative information emerges, the probability of a material drawdown may rise.")}</small>
              </div>
            </div>
            {result.influence_facts.length > 0 ? (
              <p className="research-influence-facts">
                <strong>{l("主要观察因素", "What to watch")}</strong>
                {result.influence_facts.join("；")}
              </p>
            ) : null}
            <p className="research-reference-disclaimer">
              {l("基于免费公开数据生成，仅供研究参考，不构成投资建议或交易指令。", "Generated from free public data for research reference only; not investment advice or a trading instruction.")}
            </p>
            <div className="research-next-actions" aria-label={l("下一步建议", "Suggested next actions")}>
              <strong>{l("接下来可以怎么做", "What you can do next")}</strong>
              <span>{l("下一个交易日收盘后刷新结果", "Refresh after the next trading-day close")}</span>
              <span>{l("在右侧查看前向验证与同池标的", "Review forward validation and comparable research assets on the right")}</span>
              <span>{l("若仍有疑问，可让 AI 助手解释数据与模型差异", "Ask the AI assistant to explain the data and model differences")}</span>
            </div>
            {result.status !== "research_only" ? (
              <details className="research-gate-details">
                <summary>{l("为什么本次需要继续观察？", "Why does this reading need more observation?")}</summary>
                <p><strong>{abstainExplanation.title}</strong></p>
                <p>{abstainExplanation.body}</p>
                <p>{l(
                  `技术状态：${term(result.status)}；模型分歧：${disagreement == null ? "暂无" : `${Math.round(disagreement * 100)}%`}。`,
                  `Technical status: ${term(result.status)}; model disagreement: ${disagreement == null ? "n/a" : `${Math.round(disagreement * 100)}%`}.`,
                )}</p>
              </details>
            ) : null}
          </>
        ) : (
          <InlineNotice tone="warn" title={l("当前无法计算风险参考值", "No risk reference is available")} body={abstainExplanation.body} />
        )}
      </section>
    </div>
  );
}

function readingSpreadLabel(
  tier: string,
  l: (zh: string, en: string) => string,
) {
  if (tier === "high") return l("差异较小", "Narrow spread");
  if (tier === "medium") return l("差异中等", "Moderate spread");
  if (tier === "low") return l("差异较大", "Wide spread");
  return l("待确认", "Pending");
}

function explainResearchAbstention(
  reasons: string[],
  disagreement: number | undefined,
  l: (zh: string, en: string) => string,
) {
  const uniqueReasons = [...new Set(reasons)];
  if (uniqueReasons.includes("risk_probability_disagreement_above_0.25")) {
    const difference = disagreement == null ? "" : l(`当前模型分歧为 ${(disagreement * 100).toFixed(1)}%，`, ` Current model disagreement is ${(disagreement * 100).toFixed(1)}%,`);
    return {
      title: l("模型读数差异较大，请继续观察", "Model readings differ; continue observing"),
      body: l(
        `${difference}超过研究模式 25% 的参考阈值。页面仍展示风险读数，但建议结合下一次收盘数据和价格走势观察。`,
        `${difference}This exceeds the 25% research reference threshold. The page still shows the risk reading, but it should be reviewed with the next close and price trend.`,
      ),
    };
  }
  if (uniqueReasons.includes("research_roster_missing")) {
    return {
      title: l("该标的尚未生成完整模型结果", "No complete model result exists for this asset"),
      body: l(
        "当前运行缺少对应任务的研究模型清单。系统将保留数据状态和风险提示，待下一次研究更新后补充完整读数。",
        "This run lacks the task's research model roster. The system keeps its data status and risk note, then supplements the reading after the next research update.",
      ),
    };
  }
  return {
    title: l("数据完整度有限，结果仅作风险提示", "Data completeness is limited; use this as a risk note only"),
    body: uniqueReasons.map((reason) => reason.replaceAll("_", " ")).join("；") || l("当前读数需要结合后续数据观察。", "The current reading should be reviewed with subsequent data."),
  };
}
