/**
 * Phase 8 — one fused workspace module (no view tabs, no separate professional
 * section).  选股 (left) → 仪表盘 snapshot tiles (center) → AI 多轮 (right)
 * share each column with the professional panels that used to live in a second
 * shell: portfolio + research sidebar on the left, research / short-term /
 * knowledge / history in the center, the audit hub on the right.  One header,
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
import { ResearchUserSidebar } from "../features/research/ResearchUserSidebar";
import { PortfolioPanel } from "../features/overview/PortfolioPanel";
import { InlineNotice } from "../components/InlineNotice";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { Panel } from "../components/Panel";
import {
  useAgentExplanationQuery,
  useAssetSnapshotQuery,
  useAssetsQuery,
  useCreateConversationMutation,
  usePostConversationMessageMutation
} from "../hooks/useWorkbenchQueries";
import { useI18n } from "../i18n";
import { useWorkbenchStore } from "../state/workbenchStore";
import type { AssetSnapshot, PlainAnswer } from "../api/types";
import { LLMApiKeyButton } from "./WorkbenchPage";

const DEMO_TICKERS = ["600519", "300750", "000858"];

const EXAMPLE_QUESTIONS = (l: (a: string, b: string) => string) => [
  l("请解释这家公司最近经营发生了什么变化", "Explain what changed recently in this company's operations"),
  l("如果我长期关注这家公司，主要风险是什么", "If I follow this company long-term, what are the main risks"),
  l("基本面看起来不错，但不同观察周期结果不一致，为什么", "Fundamentals look fine but the horizons disagree — why"),
];

export function StockWorkspacePage() {
  const { l, t } = useI18n();
  const mode = useWorkbenchStore((state) => state.mode);
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const assets = useAssetsQuery();
  const asOf = useMemo(() => new Date().toISOString(), []);
  const snapshot = useAssetSnapshotQuery(selectedAssetId, asOf);

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
          <span className="system-status"><ShieldCheck size={14} aria-hidden="true" /> {l("研究观察 · 非投资建议", "Research observation · not investment advice")}</span>
          <LanguageSwitch />
          <LLMApiKeyButton />
        </div>
      </header>

      <div className="research-mode-banner" role="status">
        {l("基于免费公开数据，结果仅作研究观察，不输出买卖、加仓、减仓、目标价或收益承诺。", "Built on free public data; results are research observations only — no buy/sell/position/target-price/return promises.")}
      </div>

      <main className="stock-workspace__main">
        {/* Left column: asset picker (retail) + portfolio + research sidebar (professional) */}
        <aside className="stock-workspace__picker">
          <section className="stock-workspace__picker-intro">
            <span className="eyebrow">{l("选股", "Pick")}</span>
            <strong>{l("选择研究对象", "Choose a research subject")}</strong>
            <small>{orderedAssets.length ? l("从已添加公司中切换查看。", "Switch between your added companies.") : l("先在下方研究范围中添加公司。", "Add a company in the research range below.")}</small>
          </section>
          {orderedAssets.length ? <Panel eyebrow={l("选股", "Pick")} title={l("研究对象", "Subject")}>
            <ul className="stock-workspace__asset-list">
              {orderedAssets.map((asset) => (
                <li key={asset.id}>
                  <button
                    type="button"
                    className={asset.id === selectedAssetId ? "stock-workspace__asset is-active" : "stock-workspace__asset"}
                    onClick={() => setSelectedAssetId(asset.id)}
                  >
                    <strong>{asset.ticker}</strong>
                    <span>{asset.name}</span>
                  </button>
                </li>
              ))}
            </ul>
            {mode !== "research" && mode !== "real" && (
              <InlineNotice tone="warn" title={l("演示模式", "Demo mode")} body={l("切换到研究模式以读取真实快照。", "Switch to research mode to read the real snapshot.")} />
            )}
          </Panel> : null}
          <PortfolioPanel />
          <ResearchUserSidebar section="assistant" />
        </aside>

        {/* Center column: dashboard tiles (retail) + research / short-term / knowledge / history (professional) */}
        <section className="stock-workspace__dashboard">
          <div className="stock-workspace__tiles">
            <DashboardTiles snapshot={snapshot.data ?? null} busy={snapshot.isLoading} assetLabel={selectedAsset ? `${selectedAsset.ticker} · ${selectedAsset.name}` : l("未选择", "None")} />
          </div>
          <ResearchPanel />
          <details className="short-term-market-observation" data-testid="short-term-market-observation">
            <summary>
              <span>{l("短期市场观察", "Short-term market observation")}</span>
              <small>{l("1/5/20 日读数仅用于观察近期波动，不是长期结论或买卖建议", "1/5/20-day readings describe near-term volatility only; they are not a long-term view or trading advice")}</small>
            </summary>
            <AgentExecutionPanel />
          </details>
          <FinancialKnowledgePanel />
          <HistoricalAnalogyPanel />
        </section>

        {/* Right column: AI multi-turn (retail) + audit hub (professional) */}
        <section className="stock-workspace__ai">
          <AiConversationPanel assetId={selectedAssetId} asOf={asOf} assetLabel={selectedAsset ? selectedAsset.ticker : null} />
          <details className="technical-drawer">
            <summary>
              <span>{l("技术与审计详情", "Technical and audit details")}</span>
              <small>{l("供模型研究、数据核验和历史回放使用，普通使用无需查看", "For model research, data verification and historical replay; not required for normal use")}</small>
            </summary>
            <TechnicalAuditHub />
          </details>
        </section>
      </main>

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
  return (
    <>
      <Panel eyebrow={l("行情", "Market")} title={`${assetLabel} · ${l("收盘后研究观察", "post-close research observation")}`}>
        <dl className="stock-workspace__metrics">
          <Metric label={l("最新收盘", "Latest close")} value={mo.latest_close != null ? String(mo.latest_close) : l("无数据", "n/a")} />
          <Metric label={l("交易日", "Trade date")} value={mo.trade_date ?? l("未知", "unknown")} />
          <Metric label={l("近20日回报", "20d return")} value={mo.return_20d != null ? `${(mo.return_20d * 100).toFixed(2)}%` : l("无数据", "n/a")} />
          <Metric label={l("样本数", "Sessions")} value={String(mo.sessions)} />
        </dl>
      </Panel>
      <Panel eyebrow={l("涨跌方向", "Direction")} title={l("研究框架表述（非买卖建议）", "Framed as research (not a trade suggestion)")}>
        {fc && fc.available ? (
          <p className="stock-workspace__forecast">{fc.tile_text}</p>
        ) : (
          <p className="stock-workspace__empty">{l("尚无合规框架下的方向读数。", "No framed direction reading yet.")}</p>
        )}
      </Panel>
      <Panel eyebrow={l("证据", "Evidence")} title={l("事实卡 / 财务科目", "Fact cards / line items")}>
        <dl className="stock-workspace__metrics">
          <Metric label={l("事实卡", "Fact cards")} value={String(snapshot.fact_cards.length)} />
          <Metric label={l("财务科目", "Line items")} value={String(snapshot.line_items.length)} />
          <Metric label={l("长期模型", "Long-term model")} value={snapshot.long_term_status === "available" ? l("可用", "available") : l("不可用", "unavailable")} />
          <Metric label={l("数据截止", "Data as-of")} value={snapshot.data_as_of ?? l("未知", "unknown")} />
        </dl>
      </Panel>
    </>
  );
}

function AiConversationPanel({ assetId, asOf, assetLabel }: { assetId: string | null; asOf: string; assetLabel: string | null }) {
  const { l } = useI18n();
  const createConv = useCreateConversationMutation();
  const postMsg = usePostConversationMessageMutation(assetId);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const explanation = useAgentExplanationQuery(runId);
  const examples = EXAMPLE_QUESTIONS(l);

  // Ensure a conversation exists for the selected asset.
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

  const plain = explanation.data?.plain_answer ?? null;
  const busy = postMsg.isPending || (runId != null && explanation.isLoading && !plain);

  return (
    <Panel
      eyebrow={l("AI 多轮", "AI multi-turn")}
      title={l("向研究助手提问", "Ask the research assistant")}
      actions={busy ? <span className="stock-workspace__progress"><Activity size={14} aria-hidden="true" /> {l("正在检索知识库…", "Searching the knowledge base…")}</span> : undefined}
    >
      <div className="ai-question-chips">
        {examples.map((item) => (
          <button key={item} type="button" onClick={() => setDraft(item)}><Sparkles size={13} aria-hidden="true" />{item}</button>
        ))}
      </div>
      <form
        className="stock-workspace__compose"
        onSubmit={(e) => { e.preventDefault(); submit(draft); }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={l("展开刚才的盈利拐点…（Enter 发送）", "Expand on the earnings inflection… (Enter to send)")}
          aria-label={l("提问", "Ask")}
        />
        <button type="submit" disabled={!sessionId || postMsg.isPending}>
          <Send size={14} aria-hidden="true" /> {l("提问", "Ask")}
        </button>
      </form>
      <ul className="stock-workspace__messages">
        {messages.map((m, i) => (
          <li key={i} className={m.role === "user" ? "stock-workspace__msg is-user" : "stock-workspace__msg is-assistant"}>
            <Bot size={14} aria-hidden="true" /> <span>{m.content}</span>
          </li>
        ))}
      </ul>
      {plain ? <PlainAnswerView plain={plain} /> : <PlainAnswerPlaceholder />}
    </Panel>
  );
}

function PlainAnswerView({ plain }: { plain: PlainAnswer }) {
  const { l } = useI18n();
  return (
    <div className="stock-workspace__plain">
      <Section title={l("经营情况", "Business condition")} text={plain.business_condition} />
      <Section title={l("长期变化", "Long-term changes")} text={plain.long_term_changes} />
      <Section title={l("可能的风险", "Possible risks")} text={plain.possible_risks} />
      <Section title={l("还缺什么证据", "Evidence still missing")} text={plain.missing_evidence} />
      <Section title={l("依据和更新时间", "Basis & update time")} text={plain.sources_summary} />
    </div>
  );
}

function PlainAnswerPlaceholder() {
  const { l } = useI18n();
  // Introduce the five-section structure before any run (so users know what to
  // expect) — mirrors the pre-run layout of the former homepage.
  return (
    <div className="stock-workspace__plain stock-workspace__plain--placeholder">
      <Section title={l("经营情况", "Business condition")} text={l("提问后这里给出经营层面的通俗说明。", "After you ask, the business-condition summary appears here.")} />
      <Section title={l("长期变化", "Long-term changes")} text={l("长期趋势与周期分歧的观察。", "Long-term trend and horizon-disagreement observations.")} />
      <Section title={l("可能的风险", "Possible risks")} text={l("主要风险与仍需补的证据。", "Main risks and evidence still needed.")} />
      <Section title={l("还缺什么证据", "Evidence still missing")} text={l("缺口与下一步观察条件。", "Gaps and next-step observation conditions.")} />
      <Section title={l("依据和更新时间", "Basis & update time")} text={l("来源、资料日期与更新时间。", "Sources, data dates and update time.")} />
    </div>
  );
}

function Section({ title, text }: { title: string; text: string }) {
  return (
    <div className="stock-workspace__section">
      <h4>{title}</h4>
      <p>{text}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="stock-workspace__metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
