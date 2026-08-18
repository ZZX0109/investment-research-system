/**
 * Phase 8 — StockWorkspacePage: 选股 → 仪表盘(snapshot tiles) → 左侧 AI 多轮.
 *
 * One shared single-source snapshot drives both the dashboard tiles and the AI
 * answer (the conversation route feeds the snapshot to the run), so the user
 * never sees two different numbers.  All wording stays in the compliance-safe
 * "research observation" register; the forecast tile reuses the backend's
 * framed tile_text (no buy/sell/target-price/return promises).
 */
import { Activity, Bot, Database, Send, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { InlineNotice } from "../components/InlineNotice";
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

const DEMO_TICKERS = ["600519", "300750", "000858"];

export function StockWorkspacePage() {
  const { l } = useI18n();
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
            <h1>{l("选股 · 仪表盘 · AI 研究", "Pick · Dashboard · AI research")}</h1>
            <span>{l("同一份快照驱动仪表盘与 AI 回答", "One snapshot drives the dashboard and the AI answer")}</span>
          </div>
        </div>
        <span className="system-status"><ShieldCheck size={14} aria-hidden="true" /> {l("研究观察 · 非投资建议", "Research observation · not investment advice")}</span>
      </header>

      <div className="research-mode-banner" role="status">
        {l("基于免费公开数据，结果仅作研究观察，不输出买卖、加仓、减仓、目标价或收益承诺。", "Built on free public data; results are research observations only — no buy/sell/position/target-price/return promises.")}
      </div>

      <main className="stock-workspace__main">
        {/* Left: asset picker */}
        <aside className="stock-workspace__picker">
          <Panel eyebrow={l("选股", "Pick")} title={l("研究对象", "Subject")}>
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
          </Panel>
        </aside>

        {/* Center: dashboard tiles from the single-source snapshot */}
        <section className="stock-workspace__dashboard">
          <DashboardTiles snapshot={snapshot.data ?? null} busy={snapshot.isLoading} assetLabel={selectedAsset ? `${selectedAsset.ticker} · ${selectedAsset.name}` : l("未选择", "None")} />
        </section>

        {/* Right: multi-turn AI panel */}
        <section className="stock-workspace__ai">
          <AiConversationPanel assetId={selectedAssetId} asOf={asOf} assetLabel={selectedAsset ? selectedAsset.ticker : null} />
        </section>
      </main>
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
      title={l("研究助手", "Research assistant")}
      actions={busy ? <span className="stock-workspace__progress"><Activity size={14} aria-hidden="true" /> {l("正在检索知识库…", "Searching the knowledge base…")}</span> : undefined}
    >
      <ul className="stock-workspace__messages">
        {messages.map((m, i) => (
          <li key={i} className={m.role === "user" ? "stock-workspace__msg is-user" : "stock-workspace__msg is-assistant"}>
            <Bot size={14} aria-hidden="true" /> <span>{m.content}</span>
          </li>
        ))}
      </ul>
      {plain && <PlainAnswerView plain={plain} />}
      <form
        className="stock-workspace__compose"
        onSubmit={(e) => { e.preventDefault(); submit(draft); }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={l("展开刚才的盈利拐点…", "Expand on the earnings inflection…")}
          aria-label={l("提问", "Ask")}
        />
        <button type="submit" disabled={!sessionId || postMsg.isPending}>
          <Send size={14} aria-hidden="true" /> {l("提问", "Ask")}
        </button>
      </form>
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
