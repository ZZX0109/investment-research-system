/**
 * Phase 8 — one fused workspace module (no view tabs, no separate professional
 * section).  选股 (left) → 仪表盘 snapshot tiles (center) → one AI research
 * explanation assistant (right). The assistant is the single user-facing
 * conversation entry; supporting research stays in the dashboard column.
 * One header,
 * one language switch. One shared
 * single-source snapshot drives both the dashboard tiles and the AI answer, so
 * the user never sees two different numbers.  All wording stays in the
 * compliance-safe "research observation" register; the forecast tile reuses
 * the backend's framed tile_text (no buy/sell/target-price/return promises).
 */
import {
  Activity,
  Bot,
  Database,
  ExternalLink,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AgentExecutionPanel } from "../features/agent/AgentExecutionPanel";
import { HistoricalAnalogyPanel } from "../features/history/HistoricalAnalogyPanel";
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
  useLLMProviderProfilesQuery,
  usePostConversationMessageMutation,
  usePriceSeriesQuery,
} from "../hooks/useWorkbenchQueries";
import { useI18n } from "../i18n";
import { useWorkbenchStore } from "../state/workbenchStore";
import type { AssetSnapshot, PlainAnswer, PlainSource, ResearchDiscoverySymbol } from "../api/types";
import { LLMApiKeyButton } from "./WorkbenchPage";
import { InvestmentPersonalityLab } from "../features/personality/InvestmentPersonalityLab";
import {
  ResearchDataCenter,
  ResearchDataReadinessBanner,
  ResearchSectionIntro,
  ResearchStatusStrip,
  ResearchTrustCenter,
  ResearchSettingsCenter,
  ResearchWorkspaceNav,
  type ResearchWorkspaceSection,
} from "../components/ResearchControlCenter";
import { ResearchModulePanels } from "../components/ResearchModulePanels";
import {
  useResearchAcceptanceQuery,
  useResearchCompletionQuery,
  useResearchDataQualityQuery,
  useResearchDeliveryQuery,
  useResearchLifecycleStatusQuery,
  useResearchModelRostersQuery,
  useResearchShadowSummaryQuery,
  useCreateAssetMutation,
} from "../hooks/useWorkbenchQueries";

const DEMO_TICKERS = ["600519", "300750", "000858"];

const EXAMPLE_QUESTIONS = (l: (a: string, b: string) => string) => [
  l(
    "请解释这家公司最近经营发生了什么变化",
    "Explain what changed recently in this company's operations",
  ),
  l(
    "如果我长期关注这家公司，主要风险是什么",
    "If I follow this company long-term, what are the main risks",
  ),
  l(
    "基本面看起来不错，但不同观察周期结果不一致，为什么",
    "Fundamentals look fine but the horizons disagree — why",
  ),
];

export function StockWorkspacePage() {
  const { l } = useI18n();
  const [workspaceMode, setWorkspaceMode] = useState<
    "research" | "personality"
  >("research");
  const [activeSection, setActiveSection] =
    useState<ResearchWorkspaceSection>("today");
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const researchAssetIds = useWorkbenchStore((state) => state.researchAssetIds);
  const setSelectedAssetId = useWorkbenchStore(
    (state) => state.setSelectedAssetId,
  );
  const addResearchAsset = useWorkbenchStore((state) => state.addResearchAsset);
  const assets = useAssetsQuery();
  const createAsset = useCreateAssetMutation();
  const asOf = useMemo(() => new Date().toISOString(), []);
  const snapshot = useAssetSnapshotQuery(selectedAssetId, asOf);
  const acceptance = useResearchAcceptanceQuery();
  const completion = useResearchCompletionQuery();
  const dataQuality = useResearchDataQualityQuery();
  const delivery = useResearchDeliveryQuery();
  const lifecycle = useResearchLifecycleStatusQuery();
  const rosters = useResearchModelRostersQuery();
  const priceSeries = usePriceSeriesQuery(selectedAssetId);
  const assetPriceSeries = useMemo(
    () =>
      priceSeries.data?.find((series) => series.series_role === "asset") ??
      priceSeries.data?.[0] ??
      null,
    [priceSeries.data],
  );

  const orderedAssets = useMemo(() => {
    const list = (assets.data ?? []).filter((asset) =>
      researchAssetIds.includes(asset.id),
    );
    return [...list].sort((a, b) => {
      const ai = DEMO_TICKERS.indexOf(a.ticker);
      const bi = DEMO_TICKERS.indexOf(b.ticker);
      if (ai === -1 && bi === -1) return a.ticker.localeCompare(b.ticker);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }, [assets.data, researchAssetIds]);

  useEffect(() => {
    if (
      selectedAssetId &&
      !orderedAssets.some((asset) => asset.id === selectedAssetId)
    ) {
      setSelectedAssetId(null);
      return;
    }
    if (selectedAssetId || !orderedAssets.length) return;
    const demo =
      orderedAssets.find((asset) => DEMO_TICKERS.includes(asset.ticker)) ??
      orderedAssets[0];
    setSelectedAssetId(demo.id);
  }, [orderedAssets, selectedAssetId, setSelectedAssetId]);

  const selectedAsset =
    orderedAssets.find((asset) => asset.id === selectedAssetId) ?? null;
  const openDiscoveredAsset = async (candidate: ResearchDiscoverySymbol) => {
    const existing = (assets.data ?? []).find(
      (asset) => asset.ticker.toUpperCase() === candidate.symbol && (asset.exchange ?? "") === candidate.exchange,
    );
    if (existing) {
      addResearchAsset(existing.id);
      setSelectedAssetId(existing.id);
      setActiveSection("company");
      return;
    }
    const asset = await createAsset.mutateAsync({
      ticker: candidate.symbol,
      name: candidate.name,
      asset_type: candidate.asset_type,
      currency: "CNY",
      exchange: candidate.exchange,
      data_mode: "real",
      source_type: "backfilled",
      source_name: "cn-current-public-enumeration",
      observed_at: new Date().toISOString(),
      confidence: 0.8,
    });
    addResearchAsset(asset.id);
    setSelectedAssetId(asset.id);
    setActiveSection("company");
  };
  const shadow = useResearchShadowSummaryQuery(selectedAsset?.ticker ?? null);
  const askAssistantForEvidence = () => {
    window.dispatchEvent(
      new CustomEvent("research-assistant-prompt", {
        detail: {
          question: l(
            "请结合经营事实、财务数据、长期模型和已有依据，解释当前判断的依据、反方证据以及还需观察什么。",
            "Use the business facts, financial data, long-term models and available evidence to explain the basis, contrary evidence and what to watch next.",
          ),
        },
      }),
    );
    document
      .getElementById("research-assistant")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="workbench-shell stock-workspace">
      <header className="app-header">
        <div className="brand-lockup">
          <Sparkles size={22} aria-hidden="true" />
          <div>
            <h1>
              {l(
                "长期投资 AI 研究助手",
                "Long-term investment AI research assistant",
              )}
            </h1>
            <span>
              {l(
                "选股 · 仪表盘 · AI 多轮 · 同源快照（研究观察，非投资建议）",
                "Pick · dashboard · AI multi-turn · one snapshot (research observation, not advice)",
              )}
            </span>
          </div>
        </div>
        <div className="app-header__status">
          <button
            type="button"
            className="system-status system-status--mode-toggle"
            onClick={() =>
              setWorkspaceMode((mode) =>
                mode === "research" ? "personality" : "research",
              )
            }
            aria-pressed={workspaceMode === "personality"}
          >
            {workspaceMode === "research" ? (
              <ShieldCheck size={14} aria-hidden="true" />
            ) : (
              <Sparkles size={14} aria-hidden="true" />
            )}
            {workspaceMode === "research"
              ? l(
                  "研究观察 · 非投资建议",
                  "Research observation · not investment advice",
                )
              : l("返回长期研究", "Back to long-term research")}
          </button>
          <LanguageSwitch />
          <LLMApiKeyButton />
        </div>
      </header>

      {workspaceMode === "research" && (
        <div className="research-mode-banner" role="status">
          {l(
            "基于免费公开数据，结果仅作研究观察，不输出买卖、加仓、减仓、目标价或收益承诺。",
            "Built on free public data; results are research observations only — no buy/sell/position/target-price/return promises.",
          )}
        </div>
      )}

      {workspaceMode === "personality" ? (
        <InvestmentPersonalityLab onExit={() => setWorkspaceMode("research")} />
      ) : (
        <>
          <ResearchWorkspaceNav
            active={activeSection}
            onChange={setActiveSection}
          />
          <ResearchStatusStrip
            snapshot={snapshot.data ?? null}
            acceptance={acceptance.data ?? null}
            lifecycle={lifecycle.data ?? null}
            shadow={shadow.data ?? null}
            dataQuality={dataQuality.data ?? null}
          />
          {activeSection === "data" ? (
            <ResearchDataCenter
              snapshot={snapshot.data ?? null}
              acceptance={acceptance.data ?? null}
              lifecycle={lifecycle.data ?? null}
              completion={completion.data ?? null}
              quality={dataQuality.data ?? null}
            />
          ) : activeSection === "trust" ? (
            <ResearchTrustCenter
              snapshot={snapshot.data ?? null}
              acceptance={acceptance.data ?? null}
              lifecycle={lifecycle.data ?? null}
              rosters={rosters.data ?? []}
              shadow={shadow.data ?? null}
              delivery={delivery.data ?? null}
            />
          ) : activeSection === "settings" ? (
            <ResearchSettingsCenter
              acceptance={acceptance.data ?? null}
              lifecycle={lifecycle.data ?? null}
            />
          ) : (
            <>
              {activeSection !== "company" && activeSection !== "today" ? (
                <ResearchModulePanels
                  section={activeSection}
                  assets={orderedAssets}
                  selectedAsset={selectedAsset}
                  snapshot={snapshot.data ?? null}
                  acceptance={acceptance.data ?? null}
                  lifecycle={lifecycle.data ?? null}
                  rosters={rosters.data ?? []}
                  shadow={shadow.data ?? null}
                  onOpenDiscoveredAsset={(candidate) => void openDiscoveredAsset(candidate)}
                />
              ) : (
                <>
                  {activeSection === "today" && (
                    <>
                      <ResearchDataReadinessBanner
                        quality={dataQuality.data ?? null}
                        onOpenData={() => setActiveSection("data")}
                      />
                      <ResearchModulePanels
                        section={activeSection}
                        assets={orderedAssets}
                        selectedAsset={selectedAsset}
                        snapshot={snapshot.data ?? null}
                        acceptance={acceptance.data ?? null}
                        lifecycle={lifecycle.data ?? null}
                        rosters={rosters.data ?? []}
                        shadow={shadow.data ?? null}
                        onOpenDiscoveredAsset={(candidate) => void openDiscoveredAsset(candidate)}
                      />
                    </>
                  )}
                  <ResearchSectionIntro
                    section={activeSection}
                    selectedLabel={selectedAsset ? `${selectedAsset.ticker} · ${selectedAsset.name}` : l("未选择", "None")}
                    assetCount={orderedAssets.length}
                  />
                  <main className="stock-workspace__main">
          {/* Left column: one asset selector + current research status */}
          <aside className="stock-workspace__picker">
            <PortfolioPanel />
            <IntradayNewsPanel
              snapshot={snapshot.data ?? null}
              loading={snapshot.isLoading && Boolean(selectedAssetId)}
            />
          </aside>

          {/* Center column: dashboard tiles (retail) + research / short-term / knowledge / history (professional) */}
          <section className="stock-workspace__dashboard">
            <div className="stock-workspace__tiles">
              <DashboardTiles
                snapshot={snapshot.data ?? null}
                busy={snapshot.isLoading}
                assetLabel={
                  selectedAsset
                    ? `${selectedAsset.ticker} · ${selectedAsset.name}`
                    : l("未选择", "None")
                }
              />
            </div>
            <div className="stock-workspace__trend-panel">
              <PriceTrendChart
                series={assetPriceSeries}
                modelReadings={snapshot.data?.model_readings}
                pricePathForecast={snapshot.data?.price_path_forecast ?? null}
                loading={priceSeries.isLoading}
                error={priceSeries.isError}
              />
            </div>
            <ResearchPanel onAskAssistant={askAssistantForEvidence} />
            <details
              className="short-term-market-observation"
              data-testid="short-term-market-observation"
            >
              <summary>
                <span>
                  {l(
                    "短期市场观察 · 近期波动（辅助信息）",
                    "Short-term market · near-term volatility (supporting view)",
                  )}
                </span>
                <small>
                  {l(
                    "展开后查看 1 日、5 日、20 日方向、收益区间和回撤风险；只解释近期波动，不代表长期结论。",
                    "Expand to see 1-day, 5-day and 20-day direction, return range and drawdown risk; this explains recent volatility only, not the long-term view.",
                  )}
                </small>
              </summary>
              <AgentExecutionPanel />
            </details>
            <HistoricalAnalogyPanel />
          </section>

          {/* Right column: the focused AI conversation surface. */}
          <section className="stock-workspace__ai">
            <AiConversationPanel
              assetId={selectedAssetId}
              asOf={asOf}
              assetLabel={selectedAsset ? selectedAsset.ticker : null}
            />
          </section>
                  </main>
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

function DashboardTiles({
  snapshot,
  busy,
  assetLabel,
}: {
  snapshot: AssetSnapshot | null;
  busy: boolean;
  assetLabel: string;
}) {
  const { l } = useI18n();
  if (busy) {
    return (
      <Panel
        eyebrow={l("仪表盘", "Dashboard")}
        title={l("读取同一份快照…", "Reading the shared snapshot…")}
      >
        <div className="stock-workspace__loading">
          <Database size={20} aria-hidden="true" />{" "}
          <span>
            {l(
              "正在聚合行情、模型读数、事实卡…",
              "Aggregating prices, model readings, fact cards…",
            )}
          </span>
        </div>
      </Panel>
    );
  }
  if (!snapshot) {
    return (
      <Panel
        eyebrow={l("仪表盘", "Dashboard")}
        title={l("选择标的后显示快照", "Select a subject to see the snapshot")}
      >
        <p className="stock-workspace__empty">
          {l(
            "左侧选择股票或 ETF 后，这里显示同源快照。",
            "Pick a stock or ETF on the left to see the shared snapshot.",
          )}
        </p>
      </Panel>
    );
  }
  const mo = snapshot.market_observation;
  const fc = snapshot.directional_forecast;
  const scorecard = snapshot.scorecard ?? {};
  const value = (key: string) =>
    typeof scorecard[key] === "number" ? Number(scorecard[key]) : null;
  const qualityConclusion = (score: number | null) =>
    score == null
      ? l("暂未形成", "not available")
      : score < 45
        ? l("偏弱", "weak")
        : score < 70
          ? l("尚可但不够稳定", "adequate but uneven")
          : l("相对稳健", "relatively sound");
  const growthConclusion = (score: number | null) =>
    score == null
      ? l("暂未形成", "not available")
      : score < 45
        ? l("偏弱", "weak")
        : score < 70
          ? l("暂未形成持续改善", "not yet consistently improving")
          : l("改善较稳定", "consistently improving");
  const riskConclusion = (score: number | null) =>
    score == null
      ? l("暂未形成", "not available")
      : score <= 30
        ? l("较少", "limited")
        : score < 55
          ? l("需要持续关注", "needs continued monitoring")
          : l("较多", "elevated");
  const return20d = mo.return_20d == null ? null : mo.return_20d * 100;
  const trendSummary =
    return20d == null
      ? l(
          "近20日走势：暂无足够的收盘数据。",
          "20-day trend: insufficient close data.",
        )
      : Math.abs(return20d) < 1
        ? l(
            `近20日走势：股价整体横盘，累计变化 ${return20d.toFixed(2)}%。`,
            `20-day trend: broadly flat, changing ${return20d.toFixed(2)}%.`,
          )
        : l(
            `近20日走势：股价累计${return20d >= 0 ? "上涨" : "下跌"} ${Math.abs(return20d).toFixed(2)}%。`,
            `20-day trend: shares ${return20d >= 0 ? "rose" : "fell"} ${Math.abs(return20d).toFixed(2)}%.`,
          );
  const metricName = (metric: string) =>
    ({
      revenue: l("营收", "revenue"),
      net_profit: l("净利润", "net profit"),
      gross_margin: l("毛利率", "gross margin"),
      operating_profit: l("营业利润", "operating profit"),
      roe: "ROE",
      roa: "ROA",
    })[metric] ?? metric;
  const missingFundamentals = snapshot.fundamental_coverage?.missing ?? [];
  const negativeYoYMetrics = snapshot.line_items
    .filter((item) => typeof item.yoy_pct === "number" && item.yoy_pct <= 0)
    .map((item) => String(item.metric_label ?? item.metric ?? ""))
    .filter(Boolean);
  const businessSummary =
    snapshot.long_term_status !== "available"
      ? l(
          "经营结论：长期经营资料暂未形成完整判断，可先向右侧 AI 助手追问现有事实。",
          "Business conclusion: the long-term record is not ready for a full assessment.",
        )
      : value("long_term_quality") != null &&
          value("long_term_quality")! < 45 &&
          missingFundamentals.length
        ? l(
            `经营结论：暂不能证明经营基础稳健，原因是${missingFundamentals.slice(0, 3).map(metricName).join("、")}等关键财务信息尚未完整提供；需等下一份财报补齐后确认。`,
            `Business conclusion: key financial evidence is incomplete and needs the next report to confirm.`,
          )
        : value("long_term_quality") != null &&
            value("long_term_quality")! < 45 &&
            negativeYoYMetrics.length
          ? l(
              `经营结论：经营基础偏弱，${negativeYoYMetrics.slice(0, 2).join("、")}未显示同比改善；需观察后续财报能否扭转。`,
              `Business conclusion: fundamentals are weak because key metrics have not improved year over year.`,
            )
          : l(
              `经营结论：经营基础${qualityConclusion(value("long_term_quality"))}，增长${growthConclusion(value("growth_stability"))}；下一步重点看盈利与现金流能否持续改善。`,
              `Business conclusion: fundamentals are ${qualityConclusion(value("long_term_quality"))} and growth is ${growthConclusion(value("growth_stability"))}.`,
            );
  const riskScore = value("long_term_risk");
  const riskSummary =
    riskScore != null && riskScore > 30
      ? l(
          `风险提示：当前风险线索${riskConclusion(riskScore)}，需结合行业变化和后续披露继续观察。`,
          `Risk note: current risk signals ${riskConclusion(riskScore)} and require monitoring.`,
        )
      : null;
  return (
    <Panel
      eyebrow={l("研究导语", "Research lead")}
      title={`${assetLabel} · ${l("经营情况与长期变化", "Business condition and long-term change")}`}
    >
      <dl className="stock-workspace__metrics">
        <Metric
          label={l("最新收盘", "Latest close")}
          value={
            mo.latest_close != null
              ? String(mo.latest_close)
              : l("无数据", "n/a")
          }
        />
        <Metric
          label={l("交易日", "Trade date")}
          value={mo.trade_date ?? l("未知", "unknown")}
        />
        <Metric
          label={l("近20日回报", "20d return")}
          value={
            mo.return_20d != null
              ? `${(mo.return_20d * 100).toFixed(2)}%`
              : l("无数据", "n/a")
          }
        />
        {(() => {
          // Round 34 — intraday quote (盘中实时) so the user sees today's
          // move when picking a stock. 盘中价为实时快照、非收盘确认。
          const iq = snapshot.intraday_quote;
          if (!iq || iq.latest_price == null) return null;
          const chg =
            iq.change_pct != null
              ? `${iq.change_pct >= 0 ? "+" : ""}${(iq.change_pct as number).toFixed(2)}%`
              : "";
          return (
            <Metric
              label={l("盘中价", "Intraday")}
              value={`${iq.latest_price}${chg ? ` · ${chg}` : ""}`}
            />
          );
        })()}
      </dl>
      <p className="stock-workspace__forecast stock-workspace__forecast--plain">
        {trendSummary}
      </p>
      <p className="stock-workspace__forecast stock-workspace__forecast--plain">
        {businessSummary}
      </p>
      {riskSummary ? (
        <p className="stock-workspace__forecast stock-workspace__forecast--plain">
          {riskSummary}
        </p>
      ) : null}
      {fc && fc.available ? (
        <p className="stock-workspace__forecast">
          <span className="stock-workspace__forecast-label">
            {l("近期市场观察", "Near-term market observation")}：
          </span>
          {fc.tile_text}
        </p>
      ) : (
        <p className="stock-workspace__empty">
          {l(
            "近期涨跌读数尚未形成；它不会替代长期模型。",
            "No near-term direction reading is available yet; it does not replace the long-term models.",
          )}
        </p>
      )}
    </Panel>
  );
}

function AiConversationPanel({
  assetId,
  asOf,
  assetLabel,
}: {
  assetId: string | null;
  asOf: string;
  assetLabel: string | null;
}) {
  const { l } = useI18n();
  const createConv = useCreateConversationMutation();
  const providerProfiles = useLLMProviderProfilesQuery();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const postMsg = usePostConversationMessageMutation(sessionId);
  const [draft, setDraft] = useState("");
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const [messages, setMessages] = useState<{ role: string; content: string }[]>(
    [],
  );
  const [runId, setRunId] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(
    null,
  );
  const [workingSeconds, setWorkingSeconds] = useState(0);
  const creatingSession = useRef(false);
  const chatHistoryRef = useRef<HTMLDivElement>(null);
  const activeProviderProfileId = providerProfiles.data?.find(
    (profile) => profile.enabled,
  )?.id;
  const explanation = useAgentExplanationQuery(runId);
  const examples = EXAMPLE_QUESTIONS(l);

  useEffect(() => {
    const handlePrompt = (event: Event) => {
      const question = (event as CustomEvent<{ question?: string }>).detail
        ?.question;
      if (question) {
        setDraft(question);
        setPendingPrompt(question);
        setConversationError(null);
      }
    };
    window.addEventListener("research-assistant-prompt", handlePrompt);
    return () =>
      window.removeEventListener("research-assistant-prompt", handlePrompt);
  }, []);

  useEffect(() => {
    setSessionId(null);
    setMessages([]);
    setRunId(null);
    setPendingPrompt(null);
    setConversationError(null);
    creatingSession.current = false;
  }, [assetId]);

  useEffect(() => {
    if (
      !assetId ||
      sessionId ||
      creatingSession.current ||
      createConv.isPending
    )
      return;
    creatingSession.current = true;
    createConv.mutate(
      { asset_id: assetId, as_of: asOf, title: assetLabel ?? undefined },
      {
        onSuccess: (session) => setSessionId(session.id),
        onError: () =>
          setConversationError(
            l(
              "暂时无法建立 AI 对话，请稍后重试。",
              "The AI conversation could not be created. Please try again.",
            ),
          ),
        onSettled: () => {
          creatingSession.current = false;
        },
      },
    );
  }, [assetId, sessionId, asOf, assetLabel, createConv]);

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || !sessionId || postMsg.isPending) return;
    setConversationError(null);
    setMessages((prev) => [...prev, { role: "user", content: value }]);
    setDraft("");
    postMsg.mutate(
      {
        content: value,
        provider_profile_id: activeProviderProfileId,
        user_preference: "conservative",
      },
      {
        onSuccess: (resp) => {
          setRunId(resp.run_id);
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: resp.conversation.messages.at(-1)?.content ?? "",
            },
          ]);
        },
        onError: () =>
          setConversationError(
            l(
              "AI 解读暂时没有返回。请确认项目 AI 设置已保存并稍后重试。",
              "The AI explanation did not return. Confirm the project AI settings are saved and try again.",
            ),
          ),
      },
    );
  };

  useEffect(() => {
    if (!pendingPrompt || !sessionId || postMsg.isPending) return;
    submit(pendingPrompt);
    setPendingPrompt(null);
  }, [pendingPrompt, sessionId, postMsg.isPending]);

  const plain = explanation.data?.plain_answer ?? null;
  const busy =
    postMsg.isPending || (runId != null && explanation.isLoading && !plain);

  useEffect(() => {
    if (!busy) {
      setWorkingSeconds(0);
      return;
    }
    setWorkingSeconds(0);
    const startedAt = Date.now();
    const timer = window.setInterval(
      () => setWorkingSeconds(Math.floor((Date.now() - startedAt) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!messages.length && !busy) return;
    const history = chatHistoryRef.current;
    if (!history) return;
    history.scrollTo({ top: history.scrollHeight, behavior: "smooth" });
  }, [messages.length, plain, busy]);

  return (
    <div id="research-assistant" className="stock-workspace__assistant-shell">
      <Panel
        eyebrow={l("研究解读助手", "Research assistant")}
        title={l("向研究助手提问", "Ask the research assistant")}
        actions={
          busy ? (
            <span className="stock-workspace__progress">
              <Activity size={14} aria-hidden="true" />{" "}
              {l(
                "正在联网检索并整理研究内容…",
                "Searching the web and organizing research context…",
              )}
            </span>
          ) : undefined
        }
      >
        <div className="stock-workspace__chat">
          <div className="stock-workspace__chat-history" ref={chatHistoryRef}>
            <p className="stock-workspace__assistant-intro">
              {l(
                "这是右侧唯一的研究对话入口。每次提问都会联网查找最新公开信息，再结合长期模型、经营事实和知识库，用通俗语言回答。",
                "This is the single research conversation entry. Every question checks the latest public web sources and combines them with long-term models, business facts and the knowledge base.",
              )}
            </p>
            <div className="ai-question-chips">
              {examples.map((item) => (
                <button key={item} type="button" onClick={() => setDraft(item)}>
                  <Sparkles size={13} aria-hidden="true" />
                  {item}
                </button>
              ))}
            </div>
            {conversationError ? (
              <p className="stock-workspace__assistant-error" role="alert">
                {conversationError}
              </p>
            ) : null}
            <ul className="stock-workspace__messages">
              {messages.map((m, i) => (
                <li
                  key={i}
                  className={
                    m.role === "user"
                      ? "stock-workspace__msg is-user"
                      : "stock-workspace__msg is-assistant"
                  }
                >
                  <Bot size={14} aria-hidden="true" /> <span>{m.content}</span>
                </li>
              ))}
              {busy ? (
                <AssistantWorkingStatus elapsedSeconds={workingSeconds} />
              ) : null}
            </ul>
            {plain ? (
              plain.generated_by === "llm" ? (
                <AnswerSources sources={plain.sources ?? []} />
              ) : (
                <PlainAnswerView plain={plain} />
              )
            ) : (
              <PlainAnswerPlaceholder />
            )}
          </div>
          <form
            className="stock-workspace__compose"
            onSubmit={(e) => {
              e.preventDefault();
              submit(draft);
            }}
          >
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={l(
                "例如：这家公司长期经营情况怎么样？",
                "For example: how is this company's long-term business condition?",
              )}
              aria-label={l("提问", "Ask")}
            />
            <button type="submit" disabled={!sessionId || postMsg.isPending}>
              <Send size={14} aria-hidden="true" /> {l("提问", "Ask")}
            </button>
          </form>
        </div>
      </Panel>
    </div>
  );
}

function AssistantWorkingStatus({
  elapsedSeconds,
}: {
  elapsedSeconds: number;
}) {
  const { l } = useI18n();
  const stage =
    elapsedSeconds < 3
      ? l(
          "正在读取长期研究快照与当前行情…",
          "Reading the long-term snapshot and current market data…",
        )
      : elapsedSeconds < 8
        ? l(
            "正在联网查找最新公告、新闻和行业变化…",
            "Searching current announcements, news and industry developments…",
          )
        : elapsedSeconds < 20
          ? l(
              "正在调用已配置的大模型生成通俗解读…",
              "Calling the configured model to prepare a plain-language explanation…",
            )
          : l(
              "正在核对引用与生成最终回答…",
              "Checking sources and preparing the final answer…",
            );
  return (
    <li
      className="stock-workspace__msg is-assistant is-working"
      aria-live="polite"
    >
      <Bot size={14} aria-hidden="true" />
      <span>
        <strong>{l("AI 正在工作", "AI is working")}</strong>
        {stage}
        <small>
          {l(
            "展示执行阶段，不展示模型原始思维过程",
            "Execution stages only; raw model reasoning is not shown",
          )}
        </small>
      </span>
    </li>
  );
}

function PlainAnswerView({ plain }: { plain: PlainAnswer }) {
  const { l } = useI18n();
  return (
    <details className="stock-workspace__plain">
      <summary>
        {l(
          "平台基础说明（模型未完整返回时可展开）",
          "Platform research note (expand when the model response is unavailable)",
        )}
      </summary>
      <div className="stock-workspace__plain-content">
        {plain.generated_by === "deterministic_fallback" ? (
          <p className="stock-workspace__assistant-error">
            {l(
              "本次模型未返回可用的完整回答，以下为基于研究资料的基础说明。",
              "The model did not return a usable complete answer; the following is a research-material fallback.",
            )}
          </p>
        ) : null}
        <Section
          title={l("经营情况", "Business condition")}
          text={plain.business_condition}
        />
        <Section
          title={l("长期变化", "Long-term changes")}
          text={plain.long_term_changes}
        />
        <Section
          title={l("近期市场观察", "Recent market observation")}
          text={
            plain.recent_market_observation ??
            l(
              "近期市场信息暂未获取，不能据此判断。",
              "Recent market information is unavailable.",
            )
          }
        />
        <Section
          title={l("可能的风险", "Possible risks")}
          text={plain.possible_risks}
        />
        <Section
          title={l("还需观察", "What to watch")}
          text={plain.missing_evidence}
        />
        <Section
          title={l("依据和更新时间", "Basis & update time")}
          text={plain.sources_summary}
        />
        <AnswerSources sources={plain.sources ?? []} />
      </div>
    </details>
  );
}

function AnswerSources({ sources }: { sources: PlainSource[] }) {
  const { l } = useI18n();
  if (!sources.length) return null;
  return (
    <details className="stock-workspace__answer-sources">
      <summary>
        {l(`本次参考（${sources.length}）`, `Sources used (${sources.length})`)}
      </summary>
      <ul>
        {sources.map((source, index) => (
          <li key={`${source.citation_id ?? source.title}-${index}`}>
            <strong>{source.title}</strong>
            <span>
              {source.source}
              {source.published_at
                ? ` · ${source.published_at.slice(0, 10)}`
                : ""}
            </span>
            {source.url ? (
              <a href={source.url} target="_blank" rel="noreferrer">
                {l("查看来源", "Open source")}
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

function PlainAnswerPlaceholder() {
  const { l } = useI18n();
  return (
    <div className="stock-workspace__plain stock-workspace__plain--placeholder">
      <Section
        title={l("经营情况", "Business condition")}
        text={l(
          "提问后这里给出经营层面的通俗说明。",
          "After you ask, the business-condition summary appears here.",
        )}
      />
      <Section
        title={l("长期变化", "Long-term changes")}
        text={l(
          "长期趋势与周期分歧的观察。",
          "Long-term trend and horizon-disagreement observations.",
        )}
      />
      <Section
        title={l("近期市场观察", "Recent market observation")}
        text={l(
          "资金、行业和异常变化会在提问后更新。",
          "Funds, industry and anomaly observations refresh after you ask.",
        )}
      />
      <Section
        title={l("可能的风险", "Possible risks")}
        text={l(
          "主要风险与仍需补的证据。",
          "Main risks and evidence still needed.",
        )}
      />
      <Section
        title={l("还需观察", "What to watch")}
        text={l(
          "缺口与下一步观察条件。",
          "Gaps and next-step observation conditions.",
        )}
      />
      <Section
        title={l("依据和更新时间", "Basis & update time")}
        text={l(
          "来源、资料日期与更新时间。",
          "Sources, data dates and update time.",
        )}
      />
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

function IntradayNewsPanel({
  snapshot,
  loading,
}: {
  snapshot: AssetSnapshot | null;
  loading: boolean;
}) {
  const { l } = useI18n();
  if (!snapshot && !loading) return null;
  if (!snapshot) {
    return (
      <Panel
        eyebrow={l("盘中行情", "Intraday market")}
        title={l("当日实时与新闻公告", "Same-day quote & news")}
      >
        <p className="stock-workspace__empty">
          {l(
            "正在抓取当前股票的实时行情与新闻公告…",
            "Fetching the selected stock's live quote and news…",
          )}
        </p>
      </Panel>
    );
  }
  const iq = snapshot.intraday_quote;
  const news = snapshot.market_news ?? [];
  return (
    <Panel
      eyebrow={l("盘中行情", "Intraday market")}
      title={l("当日实时与新闻公告", "Same-day quote & news")}
    >
      {iq && iq.latest_price != null ? (
        <p className="stock-workspace__forecast">
          <span className="stock-workspace__forecast-label">
            {l("盘中价", "Intraday price")}：
          </span>
          {iq.latest_price}
          {iq.change_pct != null
            ? `（${l("当日涨跌", "chg")} ${(iq.change_pct as number).toFixed(2)}%）`
            : ""}
          <small>
            {" "}
            ·{" "}
            {l(
              "盘中价为实时快照、非收盘确认",
              "intraday snapshot, not the confirmed close",
            )}
          </small>
        </p>
      ) : null}
      {news.length > 0 ? (
        <ul className="stock-workspace__news-list">
          {news.slice(0, 8).map((n, i) => (
            <li key={i}>
              <span className="stock-workspace__news-kind">
                {n.kind === "notice" ? l("公告", "notice") : l("新闻", "news")}
              </span>
              {n.url ? (
                <a
                  className="stock-workspace__news-title"
                  data-testid={`market-news-link-${i}`}
                  href={n.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={l(
                    `打开原文：${n.title ?? "新闻"}`,
                    `Open source: ${n.title ?? "news"}`,
                  )}
                >
                  <span>{n.title ?? ""}</span>
                  <ExternalLink size={12} aria-hidden="true" />
                </a>
              ) : (
                <span className="stock-workspace__news-title">
                  {n.title ?? ""}
                </span>
              )}
              <small className="stock-workspace__news-date">
                {(n.published_at ?? n.date ?? "").slice(0, 16)}
              </small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="stock-workspace__empty">
          {l("暂未抓取到新闻或公告。", "No news or notices were fetched yet.")}
        </p>
      )}
    </Panel>
  );
}
