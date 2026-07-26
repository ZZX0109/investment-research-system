import { AlertTriangle, Bot, ExternalLink, FileDown, RefreshCw, Send, Telescope } from "lucide-react";
import { useState } from "react";
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

export function ResearchUserSidebar() {
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
  const explanation = useAgentExplanationQuery(assistant.data?.id ?? null);
  const toolCalls = useAgentToolCallsQuery(assistant.data?.id ?? null);
  const activeProfile = profiles.data?.find((profile) => profile.enabled);
  const prediction = drawdown.data;
  const candidate = prediction?.diagnostic_output ?? prediction?.output;
  const probability = typeof candidate?.calibrated_probability === "number"
    ? candidate.calibrated_probability
    : candidate?.raw_probability;
  const disagreement = prediction?.model?.model_disagreement;
  const confidence = disagreement == null
    ? l("待确认", "Pending")
    : disagreement >= 0.35
      ? l("较低", "Low")
      : disagreement >= 0.2
        ? l("中等", "Moderate")
        : l("较高", "Higher");
  const riskLabel = probability == null
    ? l("等待研究结果", "Waiting for result")
    : probability >= 0.65
      ? l("回撤风险偏高", "Elevated drawdown risk")
      : probability >= 0.4
        ? l("回撤风险中等", "Moderate drawdown risk")
        : l("回撤风险相对较低", "Relatively lower risk");
  const queries = [drawdown, direction1d, direction5d, returns];
  const refreshing = queries.some((query) => query.isFetching);

  const refreshAll = () => {
    void Promise.all(queries.map((query) => query.refetch()));
  };

  return (
    <div className="research-user-sidebar">
      <Panel eyebrow={l("今日研究", "Today")} title={asset ? `${asset.ticker} ${asset.name}` : l("当前研究状态", "Current research status")}>
        {!asset ? (
          <div className="user-sidebar-empty">
            <Telescope size={22} aria-hidden="true" />
            <strong>{l("请先选择研究对象", "Choose a research asset")}</strong>
            <p>{l("选择股票或 ETF 后，这里会告诉你当前风险、结果可信度和下一步应该观察什么。", "Select a stock or ETF to see its current risk, confidence and what to watch next.")}</p>
          </div>
        ) : (
          <>
            <div className="user-research-verdict">
              <span>{l("当前观察结论", "Current observation")}</span>
              <strong>{riskLabel}</strong>
              <p>
                {probability == null
                  ? l("当前还没有可展示的参考概率，请刷新研究结果。", "No reference probability is available yet. Refresh the research result.")
                  : l(`未来 20 个交易日出现超过 8% 回撤的参考概率为 ${Math.round(probability * 100)}%。`, `Reference probability of a drawdown above 8% in the next 20 sessions: ${Math.round(probability * 100)}%.`)}
              </p>
            </div>
            <div className="user-status-list">
              <StatusRow label={l("结果可信度", "Confidence")} value={confidence} />
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
      </Panel>

      {asset ? (
        <Panel eyebrow="AI" title={l("研究助手", "Research assistant")}>
          <div className="ai-assistant-card">
            <div className="ai-assistant-card__intro">
              <Bot size={20} aria-hidden="true" />
              <p>{l("让大模型读取本平台的价格、模型和数据质量工具，再用通俗语言解释当前结果。", "Let the model read this platform's price, model and data-quality tools, then explain the result in plain language.")}</p>
            </div>
            <div className="ai-question-chips">
              {[
                l("为什么当前风险是这个水平？", "Why is risk at this level?"),
                l("接下来最值得观察什么？", "What should I watch next?"),
                l("数据有哪些不足？", "What data is missing?"),
              ].map((item) => (
                <button key={item} type="button" onClick={() => setQuestion(item)}>{item}</button>
              ))}
            </div>
            <div className="ai-question-box">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder={l("例如：为什么1日和5日方向不一致？", "For example: why do the 1-day and 5-day directions differ?")}
                rows={3}
              />
              <button
                className="primary-button"
                type="button"
                disabled={!activeProfile || !question.trim() || assistant.isPending}
                onClick={() => assistant.mutate({
                  asset_id: asset.id,
                  task_text: `${question.trim()} 请使用平台提供的只读研究工具回答，说明数据来源、可信度和限制，不提供买卖指令。`,
                  as_of: new Date().toISOString(),
                  provider_profile_id: activeProfile?.id,
                  user_preference: "conservative",
                })}
              >
                <Send size={14} aria-hidden="true" />
                {assistant.isPending ? l("正在查阅数据…", "Reading data...") : l("开始解读", "Explain")}
              </button>
            </div>
            {!activeProfile ? (
              <p className="ai-assistant-card__setup">{l("请先点击页面顶部“API Key”配置大模型。", "Configure a model using “API Key” at the top of the page first.")}</p>
            ) : null}
            {assistant.error ? <p className="ai-assistant-card__error">{assistant.error.message}</p> : null}
            {assistant.data ? (
              <div className="ai-answer">
                <span>{l("AI研究解读", "AI research explanation")}</span>
                {explanation.isLoading ? <p>{l("正在整理工具返回的信息…", "Organizing tool results...")}</p> : null}
                {explanation.data ? (
                  <>
                    <span className={`ai-answer__status ai-answer__status--${explanation.data.status ?? "research_only"}`}>
                      {explanation.data.status === "abstain"
                        ? l("模型结论暂缓 · 仍可解释现有事实", "Model conclusion withheld · available facts explained")
                        : l("研究级解读", "Research-only explanation")}
                    </span>
                    <strong>{explanation.data.summary}</strong>
                    <p>{explanation.data.supporting_view}</p>
                    <p>{explanation.data.contrary_view}</p>
                    {explanation.data.observation_conditions.length ? (
                      <ul>{explanation.data.observation_conditions.map((item) => <li key={item}>{item}</li>)}</ul>
                    ) : null}
                    {explanation.data.sources?.length ? (
                      <div className="ai-answer__sources">
                        <span>{l("引用来源", "Cited sources")}</span>
                        {explanation.data.sources.map((source) => (
                          <a key={source.url} href={source.url} target="_blank" rel="noreferrer">
                            <span>
                              <strong>{source.title}</strong>
                              <small>{source.source}{source.published_at ? ` · ${source.published_at.slice(0, 10)}` : ""}</small>
                            </span>
                            <ExternalLink size={13} aria-hidden="true" />
                          </a>
                        ))}
                      </div>
                    ) : (
                      <p className="ai-answer__no-source">
                        {l("本次没有可引用的公告或知识库条目；回答仅整理平台中的结构化研究数据。", "No citable announcement or knowledge entry was available; this answer only organizes structured platform data.")}
                      </p>
                    )}
                  </>
                ) : !explanation.isLoading ? (
                  <p>{assistant.data.abstain_reason ?? l("本次运行未生成可引用的AI解读。", "This run did not produce a citable AI explanation.")}</p>
                ) : null}
                {(toolCalls.data ?? []).length ? (
                  <details>
                    <summary>{l(`本次解读依据（${toolCalls.data?.length ?? 0}项）`, `Sources used (${toolCalls.data?.length ?? 0})`)}</summary>
                    <ul>
                      {toolCalls.data?.map((call) => <li key={call.id}>{humanToolName(call.tool_id, l)} · {call.state === "completed" ? l("已完成", "completed") : l("失败", "failed")}</li>)}
                    </ul>
                  </details>
                ) : null}
              </div>
            ) : null}
          </div>
        </Panel>
      ) : null}

      {asset ? (
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

      {asset ? <p className="user-action-note user-action-note--standalone">{l("结果来自免费公开数据，仅供研究参考，不构成投资建议。", "Results use free public data for research reference only and are not investment advice.")}</p> : null}
    </div>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function humanToolName(toolId: string, l: (zh: string, en: string) => string) {
  const labels: Record<string, string> = {
    collect_pit_evidence: l("读取当时可见的研究证据", "Read point-in-time evidence"),
    build_29_features: l("整理模型输入特征", "Build model input features"),
    approved_model_inference: l("读取风险模型结果", "Read risk-model output"),
    historical_analogy: l("查找历史相似情境", "Find historical analogies"),
    quality_gate: l("检查数据与结论可靠性", "Check data and conclusion quality"),
    get_price_trend: l("读取价格走势与波动", "Read price trend and volatility"),
    get_four_task_forecasts: l("读取四项研究模型结果", "Read four research-task outputs"),
    get_company_announcements: l("读取当时可见的公司公告", "Read available company announcements"),
    get_shadow_performance: l("读取前向验证记录", "Read forward-validation records"),
    search_financial_knowledge: l("检索金融知识库", "Search financial knowledge"),
  };
  return labels[toolId] ?? l("读取研究数据", "Read research data");
}
