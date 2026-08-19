import { Bot, BrainCircuit, Clock3, Database, ExternalLink, Globe2, Send, ShieldCheck, Sparkles, Telescope } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { InlineNotice } from "../components/InlineNotice";
import { Panel } from "../components/Panel";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { useAssetsQuery, useAgentExplanationQuery, useCreateAgentRunMutation, useAgentToolCallsQuery } from "../hooks/useWorkbenchQueries";
import { useI18n } from "../i18n";
import { useWorkbenchStore } from "../state/workbenchStore";
import { CN_RESEARCH_UNIVERSE } from "../features/overview/cnResearchUniverse";
import type { AgentExplanation, PlainAnswer, PlainSource } from "../api/types";
import { LLMApiKeyButton } from "./WorkbenchPage";

const DEMO_TICKERS = ["600519", "300750", "000858"];

export function CompetitionHome() {
  const { l, t } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const assets = useAssetsQuery();
  const assistant = useCreateAgentRunMutation();
  const [question, setQuestion] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  // Prefer the demo companies when the DB exposes them, but keep any other
  // asset selectable so the homepage works with whatever the platform seeds.
  const orderedAssets = useMemo(() => {
    const list = assets.data ?? [];
    return [...list].sort((a, b) => {
      const ai = DEMO_TICKERS.indexOf(a.ticker);
      const bi = DEMO_TICKERS.indexOf(b.ticker);
      if (ai === -1 && bi === -1) return a.ticker.localeCompare(b.ticker);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }, [assets.data]);

  useEffect(() => {
    if (selectedAssetId || !orderedAssets.length) return;
    const demo = orderedAssets.find((asset) => DEMO_TICKERS.includes(asset.ticker)) ?? orderedAssets[0];
    setSelectedAssetId(demo.id);
  }, [orderedAssets, selectedAssetId, setSelectedAssetId]);

  const selectedAsset = orderedAssets.find((asset) => asset.id === selectedAssetId);
  const runId = assistant.data?.id ?? null;
  const explanation = useAgentExplanationQuery(runId);
  const toolCalls = useAgentToolCallsQuery(runId);
  const plain = explanation.data?.plain_answer;

  const exampleQuestions = [
    l("请解释这家公司最近经营发生了什么变化", "Explain what changed recently in this company's operations"),
    l("如果我长期关注这家公司，主要风险是什么", "If I follow this company long-term, what are the main risks"),
    l("基本面看起来不错，但不同观察周期结果不一致，为什么", "Fundamentals look fine but the horizons disagree — why"),
  ];

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || !selectedAsset || assistant.isPending) return;
    if (mode !== "research" && mode !== "real") {
      setNotice(l("请在 A 股研究模式下提问。", "Ask in A-share research mode."));
      return;
    }
    setNotice(null);
    assistant.mutate({
      asset_id: selectedAsset.id,
      task_text: `${value}\n\n请使用平台只读研究工具（知识库、联网搜索、行情财务计算、长期模型、组合风险）回答，说明数据来源、日期和限制，不提供买卖或仓位指令。`.slice(0, 4000),
      as_of: new Date().toISOString(),
      user_preference: "conservative",
    });
  };

  return (
    <div className="workbench-shell competition-home">
      <header className="app-header">
        <div className="brand-lockup">
          <BrainCircuit size={24} aria-hidden="true" />
          <div>
            <h1>{l("长期投资 AI 研究助手", "Long-term investment AI research assistant")}</h1>
            <span>{l("面向长期投资者 · 查资料 · 算结果 · 解释证据 · 说明风险与缺口", "For long-term investors · research · calculate · explain evidence, risks and gaps")}</span>
          </div>
        </div>
        <div className="app-header__status">
          <span className="system-status"><Database size={14} aria-hidden="true" /> {l("研究观察 · 非投资建议", "Research observation · not investment advice")}</span>
          <LanguageSwitch />
          <LLMApiKeyButton />
        </div>
      </header>

      <div className="research-mode-banner" role="status">
        {l("基于免费公开数据，结果仅作研究观察，不输出买卖、加仓、减仓、目标价或收益承诺。", "Built on free public data; results are research observations only — no buy/sell/position/target-price/return promises.")}
      </div>

      <main className="competition-home__main">
        <section className="competition-home__hero">
          <Panel
            eyebrow={l("提问", "Ask")}
            title={l("向研究助手提问", "Ask the research assistant")}
            actions={(
              <div className="panel-actions">
                <select
                  className="asset-select"
                  value={selectedAssetId ?? ""}
                  onChange={(event) => setSelectedAssetId(event.target.value || null)}
                  aria-label={l("选择研究对象", "Select research subject")}
                >
                  <option value="">{l("请选择公司…", "Choose a company…")}</option>
                  {orderedAssets.map((asset) => (
                    <option key={asset.id} value={asset.id}>{asset.ticker} · {asset.name}</option>
                  ))}
                </select>
              </div>
            )}
          >
            <div className="competition-home__intro">
              <Bot size={18} aria-hidden="true" />
              <p>{l("助手会先判断你的问题类型，再按需调用知识库、联网搜索、行情财务计算、长期模型和组合风险工具，然后把多来源结果整理成通俗回答，并保留来源、日期和证据缺口。", "The assistant classifies your question, then calls knowledge base, web search, market/finance calculation, long-term models and portfolio risk tools as needed, and turns the results into a plain answer with sources, dates and evidence gaps.")}</p>
            </div>
            <div className="ai-question-chips">
              {exampleQuestions.map((item) => (
                <button key={item} type="button" onClick={() => { setQuestion(item); }}>{Sparkles ? <Sparkles size={13} aria-hidden="true" /> : null}{item}</button>
              ))}
            </div>
            <div className="ai-question-box ai-question-box--conversation">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(question); } }}
                placeholder={l("例如：这家公司最近经营发生了什么变化？主要风险是什么？（Enter 发送，Shift+Enter 换行）", "e.g. what changed in operations? main risks? (Enter to send, Shift+Enter for new line)")}
                rows={3}
              />
              <button className="primary-button" type="button" disabled={!question.trim() || assistant.isPending || !selectedAssetId} onClick={() => submit(question)} aria-label={l("发送问题", "Send question")}>
                <Send size={15} aria-hidden="true" /> {assistant.isPending ? l("研究中…", "Researching…") : l("提问", "Ask")}
              </button>
            </div>
            <p className="muted">{l("研究助手使用平台预置的研究能力整理证据和通俗说明，不提供买卖或仓位指令。", "The research assistant uses the platform's configured research capability to organize evidence and plain explanations; it never provides trading or position instructions.")}</p>
            {notice ? <p className="ai-assistant-card__setup" role="status">{notice}</p> : null}
            {assistant.error ? <InlineNotice tone="error" title={l("提问失败", "Question failed")} body={assistant.error.message} /> : null}
          </Panel>

          <PlainAnswerCard explanation={explanation.data} plain={plain} busy={assistant.isPending || explanation.isLoading} hasRun={Boolean(runId)} />

          {(explanation.data?.tools_used?.length || toolCalls.data?.length) ? (
            <Panel eyebrow={l("工具调用", "Tool calls")} title={l("本次调用的研究工具", "Research tools used this run")}>
              <ul className="competition-home__tools">
                {(explanation.data?.tools_used ?? []).map((tool) => <li key={tool}><ShieldCheck size={13} aria-hidden="true" /> {tool}</li>)}
              </ul>
              <p className="muted">{l("工具只读调用知识库、联网搜索、行情财务计算、长期模型与组合风险；不修改模型数值，不凭空补造区间，不把搜索摘要当作事实。", "Tools only read knowledge base, web search, market/finance calculation, long-term models and portfolio risk; they never alter model values, fabricate ranges, or treat search snippets as fact.")}</p>
            </Panel>
          ) : null}
        </section>

        <aside className="competition-home__sidebar">
          <Panel eyebrow={l("研究对象", "Subject")} title={selectedAsset ? `${selectedAsset.ticker} · ${selectedAsset.name}` : l("未选择", "None")}>
            {selectedAsset ? (
              <ul className="competition-home__universe">
                {CN_RESEARCH_UNIVERSE.filter((item) => item.assetType === "equity").slice(0, 12).map((item) => (
                  <li key={item.ticker} className={selectedAsset.ticker === item.ticker ? "is-active" : ""}>
                    <button type="button" onClick={() => { const match = orderedAssets.find((asset) => asset.ticker === item.ticker); if (match) setSelectedAssetId(match.id); }}>
                      <strong>{item.ticker}</strong> {item.name}
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="muted">{l("请在上方选择公司或从列表中点选。", "Pick a company above or from the list.")}</p>}
          </Panel>
          <NextObservationCard plain={plain} />
        </aside>
      </main>

      <details className="competition-home__professional">
        <summary>
          <span>{l("专业详情（四个长期任务、模型结构、训练范围、特征覆盖、评估指标、资料引用、运行状态）", "Professional details (four long-term tasks, model structure, training range, feature coverage, evaluation metrics, citations, run status)")}</span>
          <small>{l("供比赛评委与专业人员核对，普通用户无需查看。", "For judges and technical reviewers; not needed for normal use.")}</small>
        </summary>
        <ProfessionalDetails explanation={explanation.data} />
      </details>

      <p className="competition-home__footer">{t("banner.research")}</p>
    </div>
  );
}

function PlainAnswerCard({ explanation, plain, busy, hasRun }: { explanation?: AgentExplanation; plain?: PlainAnswer; busy: boolean; hasRun: boolean }) {
  const { l } = useI18n();
  if (busy && !plain) {
    return <Panel eyebrow={l("回答", "Answer")} title={l("正在整理通俗回答…", "Assembling the plain answer…")}><div className="competition-home__loading"><Bot size={20} /><span>{l("正在查资料、算结果、解释证据…", "Researching, calculating, explaining evidence…")}</span></div></Panel>;
  }
  if (!hasRun) {
    return <Panel eyebrow={l("回答", "Answer")} title={l("提出问题后，这里会显示通俗回答", "After you ask, the plain answer appears here")}>
      <div className="competition-home__empty"><Telescope size={22} aria-hidden="true" /><span>{l("回答会按经营情况、长期变化、可能的风险、还缺什么证据、依据和更新时间五部分呈现。", "Answers are organized into business condition, long-term changes, possible risks, missing evidence, and sources + data date.")}</span></div>
    </Panel>;
  }
  if (!plain) {
    const fallback = explanation ? composeFallback(explanation, l) : null;
    return <Panel eyebrow={l("回答", "Answer")} title={l("本次回答", "This answer")}>
      {fallback ? <p className="muted">{fallback}</p> : <InlineNotice tone="warn" title={l("暂无通俗回答", "No plain answer yet")} body={l("研究助手本次未返回通俗回答，请稍后重试。", "The assistant did not return a plain answer; retry shortly.")} />}
    </Panel>;
  }
  const statusLabel = plain.result_status === "research_observation" ? l("研究观察", "Research observation")
    : plain.result_status === "conflict_present" ? l("存在来源冲突", "Source conflict present")
    : l("证据不足", "Insufficient evidence");
  const observations = plain.long_term_observations ?? [];
  return (
    <Panel
      eyebrow={l("回答", "Answer")}
      title={l("长期投资研究通俗回答", "Plain long-term research answer")}
      actions={<span className={`tag ${plain.result_status === "research_observation" ? "" : "tag--warn"}`}>{statusLabel}</span>}
    >
      <div className="competition-home__answer">
        <AnswerSection icon={<Database size={15} />} title={l("经营情况", "Business condition")} text={plain.business_condition} />
        <AnswerSection icon={<Clock3 size={15} />} title={l("长期变化", "Long-term changes")} text={plain.long_term_changes} />
        {(plain.causal_observations ?? []).length ? (
          <div className="competition-home__causal">
            <strong>{l("因果观察", "Causal observations")}</strong>
            {(plain.causal_observations ?? []).map((item, index) => (
              <div className="competition-home__causal-item" key={`causal-${index}`}>
                <p>{item.observation}</p>
                {item.evidence_refs && item.evidence_refs.length ? (
                  <small className="muted">{l("证据线索", "Evidence")}: {item.evidence_refs.join("；")}</small>
                ) : null}
                {item.invalidation_refs && item.invalidation_refs.length ? (
                  <small className="muted">{l("证伪条件", "Invalidation")}: {item.invalidation_refs.join("；")}</small>
                ) : null}
              </div>
            ))}
            <p className="muted">{l("因果观察为研究展示推理，非验证结论，不构成操作建议。", "Causal observations are demonstration-grade reasoning, not validated conclusions or trading advice.")}</p>
          </div>
        ) : null}
        <AnswerSection icon={<ShieldCheck size={15} />} title={l("可能的风险", "Possible risks")} text={plain.possible_risks} />
        <AnswerSection icon={<Telescope size={15} />} title={l("还缺什么证据", "Missing evidence")} text={plain.missing_evidence} />
        <AnswerSection icon={<ExternalLink size={15} />} title={l("依据和更新时间", "Sources and data date")} text={plain.sources_summary} />
        {observations.length ? (
          <div className="competition-home__observations">
            <strong>{l("长期模型观察", "Long-term model observations")}</strong>
            {observations.map((item, index) => (
              <div className="competition-home__observation" key={`${item.label}-${index}`}>
                <span>{item.horizon} · {item.label}</span>
                <strong>{item.tendency}</strong>
                <small>{item.interpretation}</small>
              </div>
            ))}
            <p className="muted">{l("约 6 个月与约 12 个月读数解释为相对基准的长期表现观察；最大回撤解释为潜在下跌幅度观察，不是下跌预测或买卖信号。", "6-/12-month readings are relative-to-benchmark long-term performance observations; drawdown is a potential-decline observation, not a fall prediction or trading signal.")}</p>
          </div>
        ) : null}
        {plain.portfolio_note ? (
          <div className="competition-home__portfolio">
            <strong>{l("组合影响", "Portfolio impact")}</strong>
            <p>{plain.portfolio_note.concentration}</p>
            <p>{plain.portfolio_note.possible_impact}</p>
            <p className="muted">{plain.portfolio_note.missing_info}</p>
          </div>
        ) : null}
        {plain.sources?.length ? <SourceList sources={plain.sources} /> : null}
      </div>
    </Panel>
  );
}

function AnswerSection({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div className="competition-home__section">
      <div className="competition-home__section-head">{icon}<strong>{title}</strong></div>
      <p>{text}</p>
    </div>
  );
}

function SourceList({ sources }: { sources: PlainSource[] }) {
  const { l } = useI18n();
  return (
    <details className="competition-home__sources">
      <summary>{l(`引用来源（${sources.length}）`, `Cited sources (${sources.length})`)}</summary>
      <ul>
        {sources.map((source) => (
          <li key={`${source.url}-${source.title}`}>
            <a href={source.url} target="_blank" rel="noreferrer">
              <span><strong>{source.title}</strong><small>{source.source}{source.published_at ? ` · ${source.published_at}` : ""}{source.kind ? ` · ${source.kind}` : ""}</small></span>
              <ExternalLink size={12} aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}

function NextObservationCard({ plain }: { plain?: PlainAnswer }) {
  const { l } = useI18n();
  if (!plain) return null;
  const conditions = [...(plain.next_observation_conditions ?? []), ...(plain.invalidation_conditions ?? [])];
  if (!conditions.length) return null;
  return (
    <Panel eyebrow={l("下一步", "Next")} title={l("接下来观察什么", "What to watch next")}>
      <ul className="competition-home__watch">
        {conditions.map((item, index) => <li key={index}><span className="watch-dot" />{item}</li>)}
      </ul>
    </Panel>
  );
}

function ProfessionalDetails({ explanation }: { explanation?: AgentExplanation }) {
  const { l } = useI18n();
  if (!explanation) return <p className="muted">{l("提出问题后，这里会展示四个长期任务、模型结构、训练范围、特征覆盖、评估指标、资料引用和运行状态。", "After a question, this shows the four long-term tasks, model structure, training range, feature coverage, evaluation metrics, citations and run status.")}</p>;
  return (
    <div className="competition-home__professional-body">
      <div className="metric-strip">
        <Metric label={l("结果状态", "Result status")} value={explanation.status ?? "—"} />
        <Metric label={l("生成方式", "Generated by")} value={explanation.generated_by ?? "—"} />
        <Metric label={l("工具数", "Tools")} value={String(explanation.tools_used?.length ?? 0)} />
        <Metric label={l("来源数", "Sources")} value={String(explanation.sources?.length ?? 0)} />
      </div>
      {explanation.summary ? <AnswerSection icon={<Database size={15} />} title={l("专业摘要", "Professional summary")} text={explanation.summary} /> : null}
      {explanation.supporting_view ? <AnswerSection icon={<ShieldCheck size={15} />} title={l("支持视角", "Supporting view")} text={explanation.supporting_view} /> : null}
      {explanation.contrary_view ? <AnswerSection icon={<ShieldCheck size={15} />} title={l("反方视角", "Contrary view")} text={explanation.contrary_view} /> : null}
      <details>
        <summary>{l("四个长期任务与模型读数（专业数值）", "Four long-term tasks and model readings (technical)")}</summary>
        <p className="muted">{l("约 6 个月/约 12 个月超额表现、约 6 个月/约 12 个月潜在最大回撤。这些是后台理论证据，普通用户只看到综合后的通俗长期观察。", "6m/12m excess return, 6m/12m potential max drawdown. Backend evidence; ordinary users see only the consolidated plain observation.")}</p>
        {explanation.tools_used?.map((tool) => <span className="tag" key={tool}>{tool}</span>)}
      </details>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><div className="eyebrow">{label}</div><div className="metric-card__value">{value}</div></div>;
}

function composeFallback(explanation: AgentExplanation, l: (zh: string, en: string) => string): string | null {
  const parts = [explanation.summary, explanation.supporting_view, explanation.contrary_view].filter(Boolean);
  if (explanation.observation_conditions?.length) parts.push(`${l("接下来可观察：", "Watch next:")} ${explanation.observation_conditions.join("；")}`);
  return parts.length ? parts.join(" / ") : null;
}
