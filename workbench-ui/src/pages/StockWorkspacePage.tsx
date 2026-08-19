/**
 * Phase 8 — one fused workspace module (no view tabs, no separate professional
 * section).  选股 (left) → 仪表盘 snapshot tiles (center) → one AI research
 * explanation assistant (right). The assistant is the single user-facing
 * conversation entry; research, tools and audit details remain behind it.
 * One header,
 * one language switch. One shared
 * single-source snapshot drives both the dashboard tiles and the AI answer, so
 * the user never sees two different numbers.  All wording stays in the
 * compliance-safe "research observation" register; the forecast tile reuses
 * the backend's framed tile_text (no buy/sell/target-price/return promises).
 */
import { Activity, Bot, Database, Send, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AgentExecutionPanel } from "../features/agent/AgentExecutionPanel";
import { TechnicalAuditHub } from "../features/governance/TechnicalAuditHub";
import { HistoricalAnalogyPanel } from "../features/history/HistoricalAnalogyPanel";
import { FinancialKnowledgePanel } from "../features/research/FinancialKnowledgePanel";
import { ResearchPanel } from "../features/research/ResearchPanel";
import { PortfolioPanel } from "../features/overview/PortfolioPanel";
import { PriceTrendChart } from "../features/overview/PriceTrendChart";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { Panel } from "../components/Panel";
import {
  useAssetSnapshotQuery,
  useAssetsQuery,
  useAgentExplanationQuery,
  useCreateConversationMutation,
  usePostConversationMessageMutation,
  usePriceSeriesQuery
} from "../hooks/useWorkbenchQueries";
import { useI18n } from "../i18n";
import { useWorkbenchStore } from "../state/workbenchStore";
import type { AssetSnapshot, PlainAnswer } from "../api/types";
import { LLMApiKeyButton } from "./WorkbenchPage";
import { InvestmentPersonalityLab } from "../features/personality/InvestmentPersonalityLab";

const DEMO_TICKERS = ["600519", "300750", "000858"];

const EXAMPLE_QUESTIONS = (l: (a: string, b: string) => string) => [
  l("请解释这家公司最近经营发生了什么变化", "Explain what changed recently in this company's operations"),
  l("如果我长期关注这家公司，主要风险是什么", "If I follow this company long-term, what are the main risks"),
  l("基本面看起来不错，但不同观察周期结果不一致，为什么", "Fundamentals look fine but the horizons disagree — why"),
];

export function StockWorkspacePage() {
  const { l, t } = useI18n();
  const [workspaceMode, setWorkspaceMode] = useState<"research" | "personality">("research");
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const assets = useAssetsQuery();
  const asOf = useMemo(() => new Date().toISOString(), []);
  const snapshot = useAssetSnapshotQuery(selectedAssetId, asOf);
  const priceSeries = usePriceSeriesQuery(selectedAssetId);
  const assetPriceSeries = useMemo(
    () => priceSeries.data?.find((series) => series.series_role === "asset") ?? priceSeries.data?.[0] ?? null,
    [priceSeries.data]
  );

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

  const selectedAsset = orderedAssets.find((asset) => asset.id === selectedAssetId) ?? null;

  return (
    <div className="workbench-shell stock-workspace">
      <header className="app-header">
        <div className="brand-lockup">
          <Sparkles size={22} aria-hidden="true" />
          <div>
            <h1>{l("长期投资 AI 研究助手", "Long-term investment AI research assistant")}</h1>
            <span>{l("选股 · 仪表盘 · AI 多轮 · 同源快照（研究观察，非投资建议）", "Pick · dashboard · AI multi-turn · one snapshot (research observation, not advice)")}</span>
          </div>
        </div>
        <div className="app-header__status">
          <button
            type="button"
            className="system-status system-status--mode-toggle"
            onClick={() => setWorkspaceMode((mode) => mode === "research" ? "personality" : "research")}
            aria-pressed={workspaceMode === "personality"}
          >
            {workspaceMode === "research" ? <ShieldCheck size={14} aria-hidden="true" /> : <Sparkles size={14} aria-hidden="true" />}
            {workspaceMode === "research" ? l("研究观察 · 非投资建议", "Research observation · not investment advice") : l("返回长期研究", "Back to long-term research")}
          </button>
          <LanguageSwitch />
          <LLMApiKeyButton />
        </div>
      </header>

      {workspaceMode === "research" && <div className="research-mode-banner" role="status">
        {l("基于免费公开数据，结果仅作研究观察，不输出买卖、加仓、减仓、目标价或收益承诺。", "Built on free public data; results are research observations only — no buy/sell/position/target-price/return promises.")}
      </div>}

      {workspaceMode === "personality" ? <InvestmentPersonalityLab onExit={() => setWorkspaceMode("research")} /> : <main className="stock-workspace__main">
        {/* Left column: one asset selector + current research status */}
        <aside className="stock-workspace__picker">
          <PortfolioPanel />
        </aside>

        {/* Center column: dashboard tiles (retail) + research / short-term / knowledge / history (professional) */}
        <section className="stock-workspace__dashboard">
          <div className="stock-workspace__tiles">
            <DashboardTiles snapshot={snapshot.data ?? null} busy={snapshot.isLoading} assetLabel={selectedAsset ? `${selectedAsset.ticker} · ${selectedAsset.name}` : l("未选择", "None")} />
          </div>
          <div className="stock-workspace__trend-panel">
            <PriceTrendChart series={assetPriceSeries} modelReadings={snapshot.data?.model_readings} loading={priceSeries.isLoading} error={priceSeries.isError} />
          </div>
          <ResearchPanel />
          <EvidencePanel snapshot={snapshot.data ?? null} />
          <details className="short-term-market-observation" data-testid="short-term-market-observation">
            <summary>
              <span>{l("短期市场观察 · 近期波动（辅助信息）", "Short-term market · near-term volatility (supporting view)")}</span>
              <small>{l("展开后查看 1 日、5 日、20 日方向、收益区间和回撤风险；只解释近期波动，不代表长期结论。", "Expand to see 1-day, 5-day and 20-day direction, return range and drawdown risk; this explains recent volatility only, not the long-term view.")}</small>
            </summary>
            <AgentExecutionPanel />
          </details>
          <HistoricalAnalogyPanel />
        </section>

        {/* Right column: AI multi-turn (retail) + audit hub (professional) */}
        <section className="stock-workspace__ai">
          <AiConversationPanel assetId={selectedAssetId} asOf={asOf} assetLabel={selectedAsset ? selectedAsset.ticker : null} />
          <details className="knowledge-drawer">
            <summary>
              <span>{l("知识库依据", "Knowledge-base sources")}</span>
              <small>{l("需要时查看公告、规则、财务概念和原始引用；平时不打断对话。", "Open when you need disclosures, rules, financial concepts and source citations; otherwise it stays out of the way.")}</small>
            </summary>
            <FinancialKnowledgePanel />
          </details>
          <details className="technical-drawer">
            <summary>
              <span>{l("技术与审计详情", "Technical and audit details")}</span>
              <small>{l("供模型研究、数据核验和历史回放使用，普通使用无需查看", "For model research, data verification and historical replay; not required for normal use")}</small>
            </summary>
            <TechnicalAuditHub />
          </details>
        </section>
      </main>}

      <p className="competition-home__footer">{t("banner.research")}</p>
    </div>
  );
}

function DashboardTiles({ snapshot, busy, assetLabel }: { snapshot: AssetSnapshot | null; busy: boolean; assetLabel: string }) {
  const { l } = useI18n();
  if (busy) {
    return <Panel eyebrow={l("仪表盘", "Dashboard")} title={l("读取同一份快照…", "Reading the shared snapshot…")}><div className="stock-workspace__loading"><Database size={20} aria-hidden="true" /> <span>{l("正在聚合行情、模型读数、事实卡…", "Aggregating prices, model readings, fact cards…")}</span></div></Panel>;
  }
  if (!snapshot) {
    return <Panel eyebrow={l("仪表盘", "Dashboard")} title={l("选择标的后显示快照", "Select a subject to see the snapshot")}><p className="stock-workspace__empty">{l("左侧选择股票或 ETF 后，这里显示同源快照。", "Pick a stock or ETF on the left to see the shared snapshot.")}</p></Panel>;
  }
  const mo = snapshot.market_observation;
  const fc = snapshot.directional_forecast;
  const scorecard = snapshot.scorecard ?? {};
  const score = (key: string) => {
    const value = scorecard[key];
    return typeof value === "number" ? `${Math.round(value)}/100` : l("未形成", "not available");
  };
  const modelSummary = snapshot.long_term_status === "available"
    ? l(`长期模型显示：经营质量 ${score("long_term_quality")}，成长稳定性 ${score("growth_stability")}，主要风险 ${score("long_term_risk")}。它解释经营和长期变化，不是短期涨跌结论。`, `The long-term models show business quality ${score("long_term_quality")}, growth stability ${score("growth_stability")}, and long-term risk ${score("long_term_risk")}. They describe business and durable change, not short-term price direction.`)
    : l("长期模型还在等待完整结果；可以先向右侧 AI 助手提问经营情况和风险。", "The long-term models are still waiting for a complete result. Ask the AI assistant about business conditions and risks in the meantime.");
  return (
    <Panel eyebrow={l("研究导语", "Research lead")} title={`${assetLabel} · ${l("经营情况与长期变化", "Business condition and long-term change")}`}>
        <dl className="stock-workspace__metrics">
          <Metric label={l("最新收盘", "Latest close")} value={mo.latest_close != null ? String(mo.latest_close) : l("无数据", "n/a")} />
          <Metric label={l("交易日", "Trade date")} value={mo.trade_date ?? l("未知", "unknown")} />
          <Metric label={l("近20日回报", "20d return")} value={mo.return_20d != null ? `${(mo.return_20d * 100).toFixed(2)}%` : l("无数据", "n/a")} />
          <Metric label={l("样本数", "Sessions")} value={String(mo.sessions)} />
        </dl>
        <p className="stock-workspace__forecast stock-workspace__forecast--plain">{modelSummary}</p>
        {fc && fc.available ? (
          <p className="stock-workspace__forecast"><span className="stock-workspace__forecast-label">{l("近期市场观察", "Near-term market observation")}：</span>{fc.tile_text}</p>
        ) : (
          <p className="stock-workspace__empty">{l("近期涨跌读数尚未形成；它不会替代长期模型。", "No near-term direction reading is available yet; it does not replace the long-term models.")}</p>
        )}
    </Panel>
  );
}

function EvidencePanel({ snapshot }: { snapshot: AssetSnapshot | null }) {
  const { l } = useI18n();
  if (!snapshot) return null;
  const askAssistant = () => {
    window.dispatchEvent(new CustomEvent("research-assistant-prompt", { detail: { question: l("请结合经营事实、财务数据和长期模型，解释当前判断的依据、反方证据以及还缺什么证据。", "Combine the business facts, financial data and long-term models to explain the basis, contrary evidence and remaining gaps behind the current view.") } }));
    document.getElementById("research-assistant")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <Panel eyebrow={l("依据与证据", "Basis & evidence")} title={l("为什么这样说", "Why this view")} actions={<button type="button" className="ghost-button" onClick={askAssistant}>{l("让 AI 结合依据解释", "Ask AI to explain the basis")}</button>}>
      <dl className="stock-workspace__metrics">
        <Metric label={l("经营事实", "Business facts")} value={String(snapshot.fact_cards.length)} />
        <Metric label={l("财务数据", "Financial data")} value={String(snapshot.line_items.length)} />
        <Metric label={l("长期模型", "Long-term model")} value={snapshot.long_term_status === "available" ? l("可用", "available") : l("未形成", "not available")} />
        <Metric label={l("数据日期", "Data date")} value={snapshot.data_as_of ?? l("未知", "unknown")} />
      </dl>
      <p className="stock-workspace__evidence-note">{l(`这里汇总 ${snapshot.fact_cards.length} 条经营事实和 ${snapshot.line_items.length} 项财务数据。点击“让 AI 结合依据解释”，右侧助手会调用已配置的大模型，整理支持证据、反方证据和仍需观察的内容。`, `This section summarizes ${snapshot.fact_cards.length} business facts and ${snapshot.line_items.length} financial data points. Ask AI to explain the basis and the configured model will organize supporting evidence, contrary evidence and what remains to be observed.`)}</p>
    </Panel>
  );
}

function AiConversationPanel({ assetId, asOf, assetLabel }: { assetId: string | null; asOf: string; assetLabel: string | null }) {
  const { l } = useI18n();
  const createConv = useCreateConversationMutation();
  const postMsg = usePostConversationMessageMutation(assetId);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const explanation = useAgentExplanationQuery(runId);
  const examples = EXAMPLE_QUESTIONS(l);

  useEffect(() => {
    const handlePrompt = (event: Event) => {
      const question = (event as CustomEvent<{ question?: string }>).detail?.question;
      if (question) {
        setDraft(question);
        setPendingPrompt(question);
      }
    };
    window.addEventListener("research-assistant-prompt", handlePrompt);
    return () => window.removeEventListener("research-assistant-prompt", handlePrompt);
  }, []);

  useEffect(() => {
    setSessionId(null);
    setMessages([]);
    setRunId(null);
    setPendingPrompt(null);
  }, [assetId]);

  useEffect(() => {
    if (!assetId || sessionId) return;
    createConv.mutate(
      { asset_id: assetId, as_of: asOf, title: assetLabel ?? undefined },
      { onSuccess: (session) => setSessionId(session.id) }
    );
  }, [assetId, sessionId, asOf, assetLabel, createConv]);

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || !sessionId || postMsg.isPending) return;
    setMessages((prev) => [...prev, { role: "user", content: value }]);
    setDraft("");
    postMsg.mutate(
      { content: value, user_preference: "conservative" },
      {
        onSuccess: (resp) => {
          setRunId(resp.run_id);
          setMessages((prev) => [...prev, { role: "assistant", content: resp.conversation.messages.at(-1)?.content ?? "" }]);
        }
      }
    );
  };

  useEffect(() => {
    if (!pendingPrompt || !sessionId || postMsg.isPending) return;
    submit(pendingPrompt);
    setPendingPrompt(null);
  }, [pendingPrompt, sessionId, postMsg.isPending]);

  const plain = explanation.data?.plain_answer ?? null;
  const busy = postMsg.isPending || (runId != null && explanation.isLoading && !plain);

  return (
    <div id="research-assistant">
    <Panel
      eyebrow={l("研究解读助手", "Research assistant")}
      title={l("向研究助手提问", "Ask the research assistant")}
      actions={busy ? <span className="stock-workspace__progress"><Activity size={14} aria-hidden="true" /> {l("正在整理模型、证据和知识库…", "Organizing models, evidence and knowledge…")}</span> : undefined}
    >
      <p className="stock-workspace__assistant-intro">{l("这是右侧唯一的研究对话入口。它会把长期模型、经营事实、财务数据和知识库内容串起来，用通俗语言回答你的问题。", "This is the single research conversation entry. It connects long-term models, business facts, financial data and the knowledge base, then explains the result in plain language.")}</p>
      <div className="ai-question-chips">
        {examples.map((item) => (
          <button key={item} type="button" onClick={() => setDraft(item)}><Sparkles size={13} aria-hidden="true" />{item}</button>
        ))}
      </div>
      <form className="stock-workspace__compose" onSubmit={(e) => { e.preventDefault(); submit(draft); }}>
        <input type="text" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={l("例如：这家公司长期经营情况怎么样？", "For example: how is this company's long-term business condition?")} aria-label={l("提问", "Ask")} />
        <button type="submit" disabled={!sessionId || postMsg.isPending}><Send size={14} aria-hidden="true" /> {l("提问", "Ask")}</button>
      </form>
      <ul className="stock-workspace__messages">
        {messages.map((m, i) => <li key={i} className={m.role === "user" ? "stock-workspace__msg is-user" : "stock-workspace__msg is-assistant"}><Bot size={14} aria-hidden="true" /> <span>{m.content}</span></li>)}
      </ul>
      {plain ? <PlainAnswerView plain={plain} /> : <PlainAnswerPlaceholder />}
    </Panel>
    </div>
  );
}

function PlainAnswerView({ plain }: { plain: PlainAnswer }) {
  const { l } = useI18n();
  return <div className="stock-workspace__plain"><Section title={l("经营情况", "Business condition")} text={plain.business_condition} /><Section title={l("长期变化", "Long-term changes")} text={plain.long_term_changes} /><Section title={l("可能的风险", "Possible risks")} text={plain.possible_risks} /><Section title={l("还缺什么证据", "Evidence still missing")} text={plain.missing_evidence} /><Section title={l("依据和更新时间", "Basis & update time")} text={plain.sources_summary} /></div>;
}

function PlainAnswerPlaceholder() {
  const { l } = useI18n();
  return <div className="stock-workspace__plain stock-workspace__plain--placeholder"><Section title={l("经营情况", "Business condition")} text={l("提问后这里给出经营层面的通俗说明。", "After you ask, the business-condition summary appears here.")} /><Section title={l("长期变化", "Long-term changes")} text={l("长期趋势与周期分歧的观察。", "Long-term trend and horizon-disagreement observations.")} /><Section title={l("可能的风险", "Possible risks")} text={l("主要风险与仍需补的证据。", "Main risks and evidence still needed.")} /><Section title={l("还缺什么证据", "Evidence still missing")} text={l("缺口与下一步观察条件。", "Gaps and next-step observation conditions.")} /><Section title={l("依据和更新时间", "Basis & update time")} text={l("来源、资料日期与更新时间。", "Sources, data dates and update time.")} /></div>;
}

function Section({ title, text }: { title: string; text: string }) {
  return <div className="stock-workspace__section"><h4>{title}</h4><p>{text}</p></div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="stock-workspace__metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
