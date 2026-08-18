import { AlertTriangle, Bot, ExternalLink, FileDown, RefreshCw, Send, Telescope, Trash2, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AgentExplanation } from "../../api/types";
import { Panel } from "../../components/Panel";
import {
  useAssetsQuery,
  useAgentExplanationQuery,
  useAgentToolCallsQuery,
  useCreateAgentRunMutation,
  useLatestResearchPredictionQuery,
  useLLMProviderProfilesQuery,
} from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";

type ChatSource = NonNullable<AgentExplanation["sources"]>[number];
type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  runId?: string;
  sources?: ChatSource[];
  tools?: string[];
  fallback?: boolean;
};

export function ResearchUserSidebar({ section = "summary" }: { section?: "summary" | "assistant" }) {
  const { l, term } = useI18n();
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const assets = useAssetsQuery();
  const asset = assets.data?.find((item) => item.id === assetId);
  const drawdown = useLatestResearchPredictionQuery(asset?.ticker, "drawdown_20d");
  const direction1d = useLatestResearchPredictionQuery(asset?.ticker, "direction_1d");
  const direction5d = useLatestResearchPredictionQuery(asset?.ticker, "direction_5d");
  const returns = useLatestResearchPredictionQuery(asset?.ticker, "return_20d");
  const profiles = useLLMProviderProfilesQuery();
  const assistant = useCreateAgentRunMutation();
  const [question, setQuestion] = useState("");
  const [assistantNotice, setAssistantNotice] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadedConversationKey, setLoadedConversationKey] = useState<string | null>(null);
  const chatLogRef = useRef<HTMLDivElement>(null);
  const explanation = useAgentExplanationQuery(assistant.data?.id ?? null);
  const toolCalls = useAgentToolCallsQuery(assistant.data?.id ?? null);
  const activeProfile = profiles.data?.find((profile) => profile.enabled);
  const prediction = drawdown.data;
  const candidate = prediction?.diagnostic_output ?? prediction?.output;
  const probability = typeof candidate?.calibrated_probability === "number"
    ? candidate.calibrated_probability
    : candidate?.raw_probability;
  const disagreement = prediction?.model?.model_disagreement;
  const readingSpread = disagreement == null
    ? l("待确认", "Pending")
    : disagreement >= 0.35
      ? l("差异较大", "Wide spread")
      : disagreement >= 0.2
        ? l("差异中等", "Moderate spread")
        : l("差异较小", "Narrow spread");
  const riskLabel = probability == null
    ? l("等待研究结果", "Waiting for result")
    : probability >= 0.65
      ? l("回撤风险偏高", "Elevated drawdown risk")
      : probability >= 0.4
        ? l("回撤风险中等", "Moderate drawdown risk")
        : l("回撤风险相对较低", "Relatively lower risk");
  const queries = [drawdown, direction1d, direction5d, returns];
  const refreshing = queries.some((query) => query.isFetching);
  const explanationData = explanation.data;
  const citedSources = Array.isArray(explanationData?.sources)
    ? explanationData.sources.filter((source) => source && typeof source === "object" && typeof source.url === "string")
    : [];
  const toolCallItems = Array.isArray(toolCalls.data) ? toolCalls.data : [];
  const aiNarrativeGenerated = explanationData?.generated_by === "llm" && explanationData.llm_status === "completed";
  const referenceSummary = probability == null
    ? l("当前暂无可用风险读数，先查看数据状态和下一次更新。", "No risk reading is available yet; review data status and the next update.")
    : probability >= 0.65
      ? l("近期波动风险高于这个标的自己的历史常态，主要需要留意价格走弱、波动放大和负面信息；这不是长期收益判断。", "Near-term volatility is above this asset's own historical norm. Watch for weakening prices, expanding volatility and negative information; this is not a long-term return view.")
      : probability >= 0.4
        ? l("近期波动风险处在需要观察的区间，模型证据还不能说明长期经营会怎样。", "Near-term volatility is in a watch zone; the model evidence does not establish a long-term business outlook.")
        : l("近期波动风险暂未高于自身历史常态，但仍需结合数据日期和后续公告观察。", "Near-term volatility is not above its own historical norm, but the data date and subsequent announcements still matter.");
  const conversationKey = asset ? `research-assistant-conversation:${asset.id}` : null;

  useEffect(() => {
    if (!conversationKey) {
      setMessages([]);
      setLoadedConversationKey(null);
      return;
    }
    try {
      const saved = window.localStorage.getItem(conversationKey);
      setMessages(saved ? JSON.parse(saved) as ChatMessage[] : []);
    } catch {
      setMessages([]);
    }
    setLoadedConversationKey(conversationKey);
  }, [conversationKey]);

  useEffect(() => {
    if (!conversationKey || loadedConversationKey !== conversationKey) return;
    window.localStorage.setItem(conversationKey, JSON.stringify(messages.slice(-40)));
    requestAnimationFrame(() => chatLogRef.current?.scrollTo({ top: chatLogRef.current.scrollHeight, behavior: "smooth" }));
  }, [conversationKey, loadedConversationKey, messages]);

  useEffect(() => {
    const runId = assistant.data?.id;
    if (!runId || messages.some((message) => message.runId === runId && message.role === "assistant")) return;
    if (explanationData) {
      const content = composeAssistantReply(explanationData, referenceSummary, l);
      setMessages((current) => [...current, {
        id: `assistant-${runId}`, role: "assistant", runId,
        content, createdAt: new Date().toISOString(),
        sources: citedSources, tools: toolCallItems.map((item) => item.tool_id),
        fallback: !aiNarrativeGenerated,
      }]);
      return;
    }
    if (explanation.isError) {
      setMessages((current) => [...current, {
        id: `assistant-${runId}`, role: "assistant", runId,
        content: `${referenceSummary}\n\n${l("AI 服务本次没有返回完整叙述，以上为平台根据冻结研究数据生成的风险提示。", "The AI service did not return a complete narrative. The note above is generated from frozen platform research data.")}`,
        createdAt: new Date().toISOString(), fallback: true,
      }]);
    }
  }, [aiNarrativeGenerated, assistant.data?.id, citedSources, explanation.isError, explanationData, l, messages, referenceSummary, toolCallItems]);

  const refreshAll = () => {
    void Promise.all(queries.map((query) => query.refetch()));
  };

  const submitQuestion = () => {
    const value = question.trim();
    if (!value || !asset || assistant.isPending) return;
    if (!activeProfile) {
      setAssistantNotice(l("还没有读取到已启用的模型配置，请先打开顶部“API Key”配置。", "No enabled model profile is available. Open the “API Key” configuration first."));
      window.dispatchEvent(new Event("open-llm-config"));
      return;
    }
    const recentContext = messages.slice(-6).map((message) =>
      `${message.role === "user" ? "用户" : "助手"}: ${message.content.slice(0, 600)}`
    ).join("\n");
    setAssistantNotice(null);
    setMessages((current) => [...current, {
      id: `user-${Date.now()}`, role: "user", content: value,
      createdAt: new Date().toISOString(),
    }]);
    setQuestion("");
    assistant.mutate({
      asset_id: asset.id,
      task_text: `${value}\n\n${recentContext ? `最近对话上下文：\n${recentContext}\n\n` : ""}请使用平台提供的只读研究工具回答，说明数据来源、日期和限制，不提供买卖指令。`.slice(0, 4000),
      as_of: new Date().toISOString(),
      provider_profile_id: activeProfile.id,
      user_preference: "conservative",
    });
  };

  return (
    <div className="research-user-sidebar">
      {section !== "assistant" ? <Panel eyebrow={l("今日研究", "Today")} title={asset ? `${asset.ticker} ${asset.name}` : l("当前研究状态", "Current research status")}>
        {!asset ? (
          <div className="user-sidebar-empty">
            <Telescope size={22} aria-hidden="true" />
            <strong>{l("请先选择研究对象", "Choose a research asset")}</strong>
            <p>{l("选择股票或 ETF 后，这里会告诉你当前风险、模型读数和下一步应该观察什么。", "Select a stock or ETF to see its current risk, model readings and what to watch next.")}</p>
          </div>
        ) : (
          <>
            <div className="user-research-verdict">
              <span>{l("当前观察结论", "Current observation")}</span>
              <strong>{riskLabel}</strong>
              <p>{referenceSummary}</p>
            </div>
            <div className="user-status-list">
              <StatusRow label={l("模型读数差异", "Model reading spread")} value={readingSpread} />
              <StatusRow label={l("适用期限", "Applicable horizon")} value={l("未来 20 个交易日的波动观察", "Near-term volatility over the next 20 sessions")} />
              <StatusRow label={l("数据日期", "Data date")} value={prediction?.input?.trade_date ?? l("待更新", "Pending")} />
              <StatusRow label={l("数据来源", "Data source")} value={prediction?.input?.provider_chain.join(" → ") || l("暂无", "n/a")} />
              <StatusRow label={l("数据状态", "Data status")} value={term(prediction?.input?.data_status ?? "unavailable")} />
            </div>
            <div className="user-action-stack user-action-stack--summary">
              <button className="primary-button" type="button" disabled={refreshing} onClick={refreshAll}>
                <RefreshCw size={15} aria-hidden="true" />
                {refreshing ? l("正在更新…", "Updating...") : l("更新今日研究", "Update today's research")}
              </button>
              <button className="ghost-button" type="button" onClick={() => window.print()}>
                <FileDown size={15} aria-hidden="true" />
                {l("导出当前页面", "Export current page")}
              </button>
            </div>
          </>
        )}
      </Panel> : null}

      {section !== "summary" && asset ? (
        <Panel eyebrow="AI" title={l("研究解读助手", "Research explanation assistant")}>
          <div className="ai-assistant-card" id="research-assistant">
            <div className="ai-assistant-card__intro">
              <Bot size={20} aria-hidden="true" />
              <p>{l("它不会替你做交易决定。它只读取平台已冻结的价格走势、四项研究读数、数据质量和 Shadow 记录，把“为什么会这样、接下来观察什么”翻译成通俗语言。", "It does not make trading decisions. It only reads this platform's frozen price trend, four research readings, data quality and Shadow records, then explains why and what to watch next in plain language.")}</p>
            </div>
            <div className="ai-assistant-card__capabilities" aria-label={l("AI 助手可读取的内容", "What the AI assistant can read")}>
              <span>{l("价格与波动", "Price & volatility")}</span>
              <span>{l("四项研究结果", "Four task results")}</span>
              <span>{l("数据质量", "Data quality")}</span>
              <span>Shadow</span>
            </div>
            <div className="ai-conversation__header">
              <span>{l(`与 ${asset.name} 的研究对话`, `Research chat about ${asset.name}`)}</span>
              {messages.length ? (
                <button type="button" onClick={() => setMessages([])} title={l("清空当前标的对话", "Clear this asset conversation")}>
                  <Trash2 size={13} aria-hidden="true" /> {l("清空", "Clear")}
                </button>
              ) : null}
            </div>
            <div className="ai-conversation" ref={chatLogRef} role="log" aria-live="polite" aria-label={l("研究助手对话记录", "Research assistant conversation")}>
              {!messages.length ? (
                <div className="ai-conversation__welcome">
                  <Bot size={20} aria-hidden="true" />
                  <strong>{l("可以连续追问，不必每次重新描述背景", "Ask follow-up questions without repeating the context")}</strong>
                  <p>{l("对话会按当前研究对象保存在本机浏览器中。每次回答仍会重新调用只读研究工具核验最新数据。", "The conversation is stored in this browser for the selected asset. Every answer still re-checks current data through read-only research tools.")}</p>
                </div>
              ) : messages.map((message) => (
                <article className={`ai-message ai-message--${message.role}`} key={message.id}>
                  <div className="ai-message__avatar">{message.role === "assistant" ? <Bot size={14} /> : <UserRound size={14} />}</div>
                  <div className="ai-message__body">
                    <span>{message.role === "assistant" ? l(message.fallback ? "平台风险提示" : "AI 研究解读", message.fallback ? "Platform risk note" : "AI research explanation") : l("你", "You")}</span>
                    {message.content.split("\n").filter(Boolean).map((paragraph, index) => <p key={`${message.id}-${index}`}>{paragraph}</p>)}
                    {message.sources?.length ? (
                      <details className="ai-message__evidence">
                        <summary>{l(`查看引用来源（${message.sources.length}）`, `View cited sources (${message.sources.length})`)}</summary>
                        {message.sources.map((source) => (
                          <a key={`${source.citation_id ?? source.url}-${source.title}`} href={source.url} target="_blank" rel="noreferrer">
                            <span><strong>{source.title}</strong><small>{source.source}{source.published_at ? ` · ${source.published_at.slice(0, 10)}` : ""}{source.page_or_section ? ` · ${source.page_or_section}` : ""}</small></span>
                            <ExternalLink size={12} aria-hidden="true" />
                          </a>
                        ))}
                      </details>
                    ) : null}
                    {message.tools?.length ? <small className="ai-message__tools">{l("已核验", "Verified with")}: {[...new Set(message.tools)].map((tool) => humanToolName(tool, l)).join("、")}</small> : null}
                  </div>
                </article>
              ))}
              {assistant.isPending || explanation.isLoading ? (
                <article className="ai-message ai-message--assistant ai-message--loading">
                  <div className="ai-message__avatar"><Bot size={14} /></div>
                  <div className="ai-message__body"><span>{l("研究助手", "Research assistant")}</span><p>{l("正在查阅价格、四项模型、数据质量和知识库…", "Checking prices, four model tasks, data quality and the knowledge base...")}</p></div>
                </article>
              ) : null}
            </div>
            <div className="ai-question-chips">
              {[
                l("请解释这家公司最近经营发生了什么变化", "Explain what changed recently in this company's operations"),
                l("如果我长期关注这家公司，主要风险是什么", "If I follow this company long-term, what are the main risks"),
                l("基本面看起来不错，但不同观察周期结果不一致，为什么", "Fundamentals look fine but the horizons disagree — why"),
              ].map((item) => (
                <button key={item} type="button" onClick={() => setQuestion(item)}>{item}</button>
              ))}
            </div>
            <div className="ai-question-box ai-question-box--conversation">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submitQuestion();
                  }
                }}
                placeholder={messages.length ? l("继续追问…（Enter 发送，Shift+Enter 换行）", "Ask a follow-up… (Enter to send, Shift+Enter for a new line)") : l("例如：为什么 1 日和 5 日方向不一致？", "For example: why do the 1-day and 5-day directions differ?")}
                rows={2}
              />
              <button className="primary-button" type="button" disabled={!question.trim() || assistant.isPending} onClick={submitQuestion} aria-label={l("发送问题", "Send question")}>
                <Send size={15} aria-hidden="true" />
              </button>
            </div>
            {!activeProfile ? (
              <p className="ai-assistant-card__setup">{l("需要先点击页面顶部“API Key”配置你自己的模型。配置后，助手仍只能调用本平台的只读研究工具。", "First configure your own model via “API Key” at the top. After that, the assistant can still call only this platform's read-only research tools.")}</p>
            ) : null}
            {profiles.isError ? <p className="ai-assistant-card__error">{l("当前登录会话无法读取模型配置，请重新登录后再试。", "The current session could not read the model configuration. Sign in again and retry.")}</p> : null}
            {assistantNotice ? <p className="ai-assistant-card__setup" role="status">{assistantNotice}</p> : null}
            {assistant.error ? <p className="ai-assistant-card__error">{assistant.error.message}</p> : null}
          </div>
        </Panel>
      ) : null}

      {section !== "assistant" && asset ? (
        <Panel eyebrow={l("下一步", "Next")} title={l("接下来观察什么", "What to watch next")}>
          <div className="watch-list">
            <div><span className="watch-dot watch-dot--good" /><p><strong>{l("风险改善信号", "Improvement signal")}</strong>{l("价格企稳、波动率回落，模型分歧下降。", "Price stabilizes, volatility eases and model disagreement falls.")}</p></div>
            <div><span className="watch-dot watch-dot--warn" /><p><strong>{l("风险上升信号", "Risk warning")}</strong>{l("价格继续走弱、波动放大或出现负面信息。", "Price weakens further, volatility expands or negative information appears.")}</p></div>
            <div><span className="watch-dot" /><p><strong>{l("下次更新", "Next update")}</strong>{l("下一个交易日收盘后重新计算。", "Recalculate after the next trading-day close.")}</p></div>
          </div>
          {disagreement != null && disagreement >= 0.25 ? (
            <div className="plain-warning">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>{l("不同模型看法差异较大，本次结果只适合谨慎参考。", "Models disagree materially; use this result cautiously.")}</span>
            </div>
          ) : null}
        </Panel>
      ) : null}

      {section !== "assistant" && asset ? <p className="user-action-note user-action-note--standalone">{l("结果来自免费公开数据，仅供研究参考，不构成投资建议。", "Results use free public data for research reference only and are not investment advice.")}</p> : null}
    </div>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function composeAssistantReply(
  explanation: AgentExplanation,
  referenceSummary: string,
  l: (zh: string, en: string) => string,
) {
  const paragraphs: string[] = [];
  if (explanation.summary?.trim()) {
    paragraphs.push(explanation.summary.trim());
  } else {
    paragraphs.push(referenceSummary);
  }
  if (explanation.supporting_view?.trim()) paragraphs.push(explanation.supporting_view.trim());
  if (explanation.contrary_view?.trim()) paragraphs.push(explanation.contrary_view.trim());
  if (explanation.observation_conditions?.length) {
    paragraphs.push(`${l("接下来可观察：", "What to watch next:")} ${explanation.observation_conditions.join("；")}`);
  }
  if (explanation.generated_by !== "llm" && explanation.llm_error) {
    paragraphs.push(l("本次大模型服务未返回完整回答，以上内容由平台根据冻结研究数据整理。", "The model service did not return a complete answer; the platform assembled the note above from frozen research data."));
  }
  return paragraphs.filter(Boolean).join("\n\n");
}

function humanToolName(toolId: string, l: (zh: string, en: string) => string) {
  const labels: Record<string, string> = {
    collect_pit_evidence: l("读取当时可见的研究证据", "Read point-in-time evidence"),
    build_29_features: l("整理模型输入特征", "Build model input features"),
    approved_model_inference: l("读取风险模型结果", "Read risk-model output"),
    historical_analogy: l("查找历史相似情境", "Find historical analogies"),
    quality_gate: l("检查数据与结论状态", "Check data and conclusion status"),
    get_price_trend: l("读取价格走势与波动", "Read price trend and volatility"),
    get_four_task_forecasts: l("读取四项研究模型结果", "Read four research-task outputs"),
    get_company_announcements: l("读取当时可见的公司公告", "Read available company announcements"),
    get_shadow_performance: l("读取前向验证记录", "Read forward-validation records"),
    search_financial_knowledge: l("检索金融知识库", "Search financial knowledge"),
  };
  return labels[toolId] ?? l("读取研究数据", "Read research data");
}
