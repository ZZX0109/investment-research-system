import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { InlineNotice } from "../../components/InlineNotice";
import { EmptyState } from "../../components/EmptyState";
import { EvidenceHash } from "../../components/EvidenceHash";
import { MetricCard } from "../../components/MetricCard";
import { Panel } from "../../components/Panel";
import { ResearchHero } from "../../components/ResearchHero";
import { ShadowProgress } from "../../components/ShadowProgress";
import { StatusBadge } from "../../components/StatusBadge";
import { TaskForecastCard } from "../../components/TaskForecastCard";
import { SourceBadge } from "../../components/SourceBadge";
import { useI18n } from "../../i18n";
import { SelectedRunDossierCard } from "../dossier/SelectedRunDossierCard";
import { useResearchWorkspace } from "./useResearchWorkspace";
import { LongTermInvestorSummary } from "./LongTermInvestorSummary";
import { useDeploymentStatusQuery, useDirectionalForecastQuery, useLatestLongTermScorecardQuery, useMarketObservationQuery, useRefreshMarketObservationMutation, useResearchAcceptanceQuery, useResearchForecastQuery, useResearchLifecycleStatusQuery, useResearchModelRostersQuery, useResearchShadowSessionsQuery, useResearchShadowSummaryQuery } from "../../hooks/useWorkbenchQueries";

export function ResearchPanel() {
  const { formatDateTime, l, t, term, language } = useI18n();
  const workspace = useResearchWorkspace();
  const deployment = useDeploymentStatusQuery();
  const acceptance = useResearchAcceptanceQuery();
  const trustedCard = deployment.data?.trusted_risk_gate;
  const publicExperiment = deployment.data?.public_experiment;
  const marketObservation = useMarketObservationQuery(workspace.assetId);
  const outcome = marketObservation.data?.outcomes.find((item) => item.run_id === workspace.selectedRunId) ?? marketObservation.data?.outcomes[0];
  const direction = useDirectionalForecastQuery(workspace.selectedRunId);
  const forecast = useResearchForecastQuery(workspace.selectedRunId);
  const scorecard = useLatestLongTermScorecardQuery(workspace.assetTicker);
  const refreshObservation = useRefreshMarketObservationMutation(workspace.assetId);
  const shadow = useResearchShadowSessionsQuery(workspace.assetTicker);
  const shadowSummary = useResearchShadowSummaryQuery(workspace.assetTicker);
  const rosters = useResearchModelRostersQuery();
  const lifecycle = useResearchLifecycleStatusQuery();
  const acceptanceCoverage = acceptance.data?.data?.market_coverage?.[0];
  const acceptanceTasks = acceptance.data?.tasks ?? {};
  const taskStatus = (task: string) => {
    const forecastTask = forecast.data?.tasks.find((item) => item.task === task);
    const acceptanceTask = acceptance.data?.tasks?.[task];
    return forecastTask?.status
      ?? (acceptanceTask?.artifact_available ? acceptanceTask.research_status : acceptanceTask?.prediction_status)
      ?? acceptanceTask?.status
      ?? "unavailable";
  };
  const taskReasons = (task: string) => forecast.data?.tasks.find((item) => item.task === task)?.gating_reasons ?? [];

  return (
    <Panel eyebrow={t("research.eyebrow")} title={t("research.title")}>
      {workspace.assetId ? (
        <>
          <ResearchHero
            status={acceptance.data?.status ?? "blocked"}
            asOf={forecast.data?.data_status.as_of}
            decisionContext={forecast.data?.decision_context}
          />
          <article className="story-card" data-testid="cn-research-data-quality">
            <div className="story-card__header">
              <strong>{t("research.dataQuality")}</strong>
              <StatusBadge status={forecast.data?.data_status.quality_status ?? (acceptance.data?.evidence_status === "partial" ? "degraded" : "unavailable")} />
            </div>
            <p className="muted">
              {language === "zh-CN"
                ? <>免费公开数据固定为 research_pit；历史可见时间未完全证明，永不自动提升为正式 PIT。数据覆盖 {forecast.data ? `${Math.round(forecast.data.data_status.coverage_ratio * 100)}%` : acceptanceCoverage?.coverage_ratio != null ? `${Math.round(acceptanceCoverage.coverage_ratio * 100)}%` : t("hero.waiting")}，缓存 {term(forecast.data?.data_status.cache_state ?? "unavailable")}，事件 {term(forecast.data?.data_status.event_coverage_status ?? acceptanceCoverage?.event_coverage_status ?? "unsupported")}。</>
                : <>Public data remains research_pit. Historical visibility is not fully proven and is never promoted to formal PIT. Coverage: {forecast.data ? `${Math.round(forecast.data.data_status.coverage_ratio * 100)}%` : acceptanceCoverage?.coverage_ratio != null ? `${Math.round(acceptanceCoverage.coverage_ratio * 100)}%` : t("hero.waiting")}; cache: {forecast.data?.data_status.cache_state ?? "unavailable"}; events: {forecast.data?.data_status.event_coverage_status ?? acceptanceCoverage?.event_coverage_status ?? "unsupported"}.</>}
            </p>
            {forecast.data?.data_status.reasons.length ? <InlineNotice title={language === "zh-CN" ? "数据降级原因" : "Data degradation reasons"} tone="warn" body={forecast.data.data_status.reasons.map(term).join("；")} /> : null}
          </article>
          <LongTermInvestorSummary forecast={forecast.data} acceptance={acceptance.data} scorecard={scorecard.data} language={language} />
          <details className="research-supporting-details" data-testid="research-supporting-details">
            <summary>
              <span>{l("更多研究证据与运行详情", "More evidence and research details")}</span>
              <small>{l("包含短周期诊断、价格回放、模型状态和审计证据", "Includes short-horizon diagnostics, price replay, model status and audit evidence")}</small>
            </summary>
          <article className="story-card" data-testid="cn-research-backend-status">
            <div className="story-card__header">
              <strong>{t("research.backendStatus")}</strong>
              <span className="tag">{term(acceptance.data?.status ?? "blocked")}</span>
            </div>
            <div className="metric-strip">
              <MetricCard label={t("research.data")} value={term(forecast.data?.data_status.quality_status ?? acceptance.data?.evidence_status ?? "unavailable")} tone={forecast.data?.data_status.quality_status === "passed" ? "good" : "warn"} />
              <MetricCard label={t("research.training")} value={term(forecast.data?.training_status ?? "unavailable")} />
              <MetricCard label={t("research.prediction")} value={term(forecast.data?.prediction_status ?? "unavailable")} tone={forecast.data?.prediction_status === "research_only" ? "good" : "warn"} />
              <MetricCard label={t("research.evidence")} value={term(forecast.data?.evidence_status ?? "missing")} />
            </div>
            <p className="muted">{language === "zh-CN" ? "模型" : "Model"}: {term(forecast.data?.model_status ?? "unavailable")}; {l("部署就绪：否", "deployment_ready: false")}; {language === "zh-CN" ? "研究级公开数据，不构成投资建议。" : "public research data, not investment advice."}</p>
            <p className="muted">{t("research.provider")}: AKShare {t("research.success")} {acceptance.data?.data?.akshare_success_count ?? "n/a"}, Baostock {t("research.success")} {acceptance.data?.data?.baostock_success_count ?? "n/a"}, {t("research.failures")} {acceptance.data?.data?.failed_count ?? "n/a"}, {t("research.fallbacks")} {acceptance.data?.data?.fallback_count ?? "n/a"}，{l("冲突", "conflicts")} {acceptance.data?.data?.conflict_count ?? "n/a"}。</p>
            {(forecast.data?.blocking_reasons ?? acceptance.data?.blocking_reasons ?? []).length ? <InlineNotice title={t("research.blockingReasons")} tone="warn" body={(forecast.data?.blocking_reasons ?? acceptance.data?.blocking_reasons ?? []).map(term).join("；")} /> : null}
            {(forecast.data?.abstain_reasons ?? []).length ? <InlineNotice title={t("research.abstainReasons")} tone="warn" body={forecast.data?.abstain_reasons.map(term).join("；") ?? ""} /> : null}
          </article>
          <article className="story-card" data-testid="cn-research-acceptance-summary">
            <div className="story-card__header">
              <strong>{l("研究链路验收摘要", "Research acceptance summary")}</strong>
              <StatusBadge status={acceptance.data?.research_status ?? "unavailable"} />
            </div>
            <div className="metric-strip">
              <MetricCard label={l("模型产物", "Artifacts")} value={acceptance.data?.artifact_available ? l("已校验", "verified") : l("不可用", "unavailable")} />
              <MetricCard label={l("股票 / ETF", "Equity / ETF")} value={`${acceptance.data?.cohorts?.cn_equity_core?.member_count ?? "—"} / ${acceptance.data?.cohorts?.cn_etf_benchmark?.member_count ?? "—"}`} />
              <MetricCard label={l("降级记录", "Degraded records")} value={String(acceptance.data?.data?.quality_status_counts?.degraded ?? "—")} />
              <MetricCard label={l("Shadow 已冻结", "Shadow frozen")} value={String(acceptance.data?.shadow?.frozen_count ?? "—")} />
            </div>
            <p className="muted">
              {l("四项任务均为研究级 exploratory；有模型产物不代表已通过研究 Gate。正式模式仍然阻断，deployment_ready=false。", "All four tasks are research-only exploratory models; artifacts do not mean the research Gate passed. Formal mode remains blocked and deployment_ready=false.")}
            </p>
            <div className="stack-list">
              {(["direction_1d", "direction_5d", "return_20d", "drawdown_20d"] as const).map((task) => {
                const item = acceptanceTasks[task];
                return <p key={task}>{task}：{term(item?.research_status ?? item?.prediction_status ?? item?.status ?? "unavailable")} · {item?.artifact_available ? l("产物可用", "artifact available") : l("缺少产物", "artifact unavailable")}</p>;
              })}
            </div>
          </article>
          <article className="story-card" data-testid="cn-research-lifecycle-status">
            <div className="story-card__header">
              <strong>{language === "zh-CN" ? "研究自动更新" : "Research lifecycle"}</strong>
              <span className="tag">{lifecycle.data?.status ?? "research_only"}</span>
            </div>
            <div className="metric-strip">
              <MetricCard label={language === "zh-CN" ? "最近数据" : "Latest data"} value={lifecycle.data?.latest_trade_date ?? "—"} />
              <MetricCard label={language === "zh-CN" ? "下次训练" : "Next training"} value={lifecycle.data?.next_training ? formatDateTime(lifecycle.data.next_training) : "—"} />
              <MetricCard label={language === "zh-CN" ? "候选模型" : "Candidate"} value={lifecycle.data?.candidate ?? "—"} />
              <MetricCard label={language === "zh-CN" ? "自动替换" : "Promotion"} value={lifecycle.data?.promotion ?? "pending"} />
            </div>
            <p className="muted">
              {language === "zh-CN"
                ? "每日更新数据和 Shadow，每周监控漂移，每月训练候选模型；只有通过研究 Gate 和 Shadow 后才自动替换主模型。"
                : "Daily data and Shadow, weekly drift monitoring, monthly candidate training; the primary changes only after research gates and Shadow evidence pass."}
            </p>
            {lifecycle.data?.blocking_reasons.length ? <InlineNotice title={language === "zh-CN" ? "自动化阻断原因" : "Automation blockers"} tone="warn" body={lifecycle.data.blocking_reasons.map(term).join("；")} /> : null}
          </article>
          <article className="story-card" data-testid="cn-research-roster">
            <div className="story-card__header">
              <strong>{t("research.roster")}</strong>
              <span className="tag">{rosters.data?.length ?? 0} {l("个范围", "scopes")}</span>
            </div>
            {(rosters.data ?? []).length ? (
              <div className="stack-list">
                {rosters.data?.map((roster) => (
                  <p key={roster.roster_hash}>
                    {roster.cohort} · {roster.task}：{l("主模型", "primary")} {roster.primary.candidate_name} / {l("备用模型", "fallback")} {roster.fallback.candidate_name} · {l("仅供研究", "research_only")} · {l("部署就绪：否", "deployment_ready=false")} · {l("清单哈希", "roster hash")} {roster.roster_hash.slice(0, 12)}
                  </p>
                ))}
              </div>
            ) : <EmptyState title={t("research.rosterEmpty")} body={t("research.rosterEmptyBody")} />}
          </article>
          <article className="story-card" data-testid="cn-research-task-results">
            <div className="story-card__header"><strong>{language === "zh-CN" ? "短周期诊断（次要信息）" : "Short-horizon diagnostics (secondary)"}</strong><span className="tag">{t("research.notSignal")}</span></div>
            <p className="muted">{language === "zh-CN" ? "以下 1 日、5 日和 20 日读数只用于说明近期波动，不代表长期上涨胜率，也不构成买卖指令。长期结论须等待季度级 120/240 日标签和完整 PIT 数据；5/20 日超额收益只作为辅助横截面研究。" : "The 1-day, 5-day and 20-day readings below describe near-term volatility only. They are not long-term winning probabilities or trading instructions; durable views require mature quarterly 120/240-day labels and complete PIT data, while 5/20-day excess returns remain auxiliary cross-sectional research."}</p>
            {forecast.data && ["research_only", "approved", "fallback"].includes(forecast.data.prediction_status) && !forecast.data.abstained ? (
              <div className="task-forecast-grid">
                <TaskForecastCard task="01D" title={t("research.direction")} status={taskStatus("direction_1d")} model={forecast.data.tasks.find((item) => item.task === "direction_1d")?.model_version} value={forecast.data.direction_1d ? `${t("research.up")} ${Math.round(forecast.data.direction_1d.up * 100)}%` : term("unavailable")} detail={forecast.data.direction_1d ? <span>{t("research.down")} {Math.round(forecast.data.direction_1d.down * 100)}% · {t("research.flat")} {Math.round(forecast.data.direction_1d.flat * 100)}%</span> : null} />
                <TaskForecastCard task="05D" title={t("research.direction")} status={taskStatus("direction_5d")} model={forecast.data.tasks.find((item) => item.task === "direction_5d")?.model_version} value={forecast.data.direction_5d ? `${t("research.up")} ${Math.round(forecast.data.direction_5d.up * 100)}%` : term("unavailable")} detail={forecast.data.direction_5d ? <span>{t("research.down")} {Math.round(forecast.data.direction_5d.down * 100)}% · {t("research.flat")} {Math.round(forecast.data.direction_5d.flat * 100)}%</span> : null} />
                <TaskForecastCard task="20D" title={t("research.return")} status={taskStatus("return_20d")} model={forecast.data.tasks.find((item) => item.task === "return_20d")?.model_version} value={forecast.data.return_20d ? [forecast.data.return_20d.p10, forecast.data.return_20d.p50, forecast.data.return_20d.p90].map((value) => `${(value * 100).toFixed(1)}%`).join(" / ") : term("unavailable")} detail={<EvidenceHash label={l("快照", "snapshot")} value={forecast.data.market_snapshot_hash} />} />
                <TaskForecastCard task="DD20" title={t("research.drawdown")} status={taskStatus("drawdown_20d")} model={forecast.data.tasks.find((item) => item.task === "drawdown_20d")?.model_version} value={forecast.data.drawdown_20d ? `${Math.round(forecast.data.drawdown_20d.threshold_probability * 100)}%` : term("unavailable")} detail={<EvidenceHash label={l("快照", "snapshot")} value={forecast.data.market_snapshot_hash} />} />
              </div>
            ) : <InlineNotice title={forecast.data?.prediction_status === "unavailable" ? t("research.taskUnavailable") : t("research.insufficientEvidence")} tone="warn" body={forecast.data?.abstain_reasons.map(term).join("；") || forecast.data?.gating_reasons.map(term).join("；") || t("research.waitingEvidence")} />}
            {forecast.data?.influence_facts.length ? <p className="muted">{t("research.influence")}: {forecast.data.influence_facts.map(term).join("；")}。{t("research.nonCausal")}</p> : null}
            <div className="stack-list">
              {(["direction_1d", "direction_5d", "return_20d", "drawdown_20d"] as const).map((task) => (
                <p key={task}>{task}：{term(taskStatus(task))}{taskReasons(task).length ? ` · ${taskReasons(task).map(term).join("；")}` : ""}</p>
              ))}
            </div>
          </article>
          <article className="story-card" data-testid="research-shadow-summary">
            <div className="story-card__header"><strong>{t("research.shadow")}</strong><StatusBadge status={shadowSummary.data?.valid_session_count ? "partial" : "abstain"} /></div>
            {(shadow.data ?? []).length ? (
              <>
                <ShadowProgress sessionCount={shadowSummary.data?.session_count ?? shadow.data?.length ?? 0} validCount={shadowSummary.data?.valid_session_count ?? 0} abstainCount={shadowSummary.data?.abstained_count ?? 0} completed={shadowSummary.data?.completed_outcomes ?? {}} forwardStatus={shadowSummary.data?.forward_report_20_status ?? "pending"} primaryStatus={shadowSummary.data?.primary_change_60_status ?? "blocked"} />
                {(shadow.data ?? []).slice(0, 3).map((item) => (
                  <p key={item.id}>{item.trade_date} · {term(item.decision_context)} · {item.task} · {item.abstained ? `${l("拒答", "abstain")}: ${item.abstain_reasons.map(term).join(", ")}` : l("已冻结", "frozen")}</p>
                ))}
              </>
            ) : <EmptyState title={t("research.noShadow")} body={t("research.noShadowBody")} />}
          </article>
          <div className="metric-strip">
            <div className="metric-card">
              <div className="eyebrow">{l("最新收盘价", "Latest Close")}</div>
              <div className="metric-card__value">{workspace.latestCloseLabel}</div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">{l("证据", "Evidence")}</div>
              <div className="metric-card__value">
                {workspace.evidenceCount} / {workspace.totalEvidenceCount}
              </div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">{l("运行 / 报告", "Runs / Reports")}</div>
              <div className="metric-card__value">
                {workspace.runCount} / {workspace.filteredReportsCount}
              </div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">{l("已配置数据源", "Configured Providers")}</div>
              <div className="metric-card__value">{workspace.providerNamesLabel}</div>
            </div>
          </div>
          {trustedCard ? (
            <article className="story-card" data-testid="trusted-risk-gate-card">
              <div className="story-card__header">
                <strong>{l("研究治理门禁", "Research Governance Gate")}</strong>
                <span className="tag">{String(trustedCard.framework_version ?? "v1")}</span>
              </div>
              <p className="muted">
                Research PIT、事件覆盖、市场状态验证、拒答与固定回放共同约束研究输出；正式发布仍需授权数据。
              </p>
            </article>
          ) : null}
          {publicExperiment ? (
            <article className="story-card" data-testid="public-experiment-summary">
              <div className="story-card__header">
                <strong>{l("实验血缘", "Experiment Provenance")}</strong>
                <span className="tag">{String(publicExperiment.schema_version ?? "unavailable")}</span>
              </div>
              <p className="muted">
                {l("训练运行", "Training run")} {String((publicExperiment.identity as Record<string, unknown> | undefined)?.training_run_id ?? l("暂无", "n/a"))};
                &nbsp; {l("市场", "markets")}: {Array.isArray(publicExperiment.included_markets) ? publicExperiment.included_markets.join(", ") : l("暂无", "n/a")}。
              </p>
            </article>
          ) : null}
          {marketObservation.data ? (
            <article className="story-card" data-testid="market-observation-panel">
              <div className="story-card__header"><strong>{l("研究风险与后续价格", "Research risk and subsequent prices")}</strong><span className="tag">{term(marketObservation.data.market_status)}</span></div>
              <div className="metric-strip">
                <div className="metric-card"><div className="eyebrow">{l("风险预测", "Risk Forecast")}</div><div className="metric-card__value">{outcome?.predicted_risk == null ? l("暂无", "n/a") : `${Math.round(outcome.predicted_risk * 100)}%`}</div></div>
                <div className="metric-card"><div className="eyebrow">{l("预测时价格", "Predicted At")}</div><div className="metric-card__value">{outcome?.prediction_price?.toFixed(2) ?? l("暂无", "n/a")}</div></div>
                <div className="metric-card"><div className="eyebrow">{l("最新真实价格", "Latest Real")}</div><div className="metric-card__value">{marketObservation.data.latest_price?.toFixed(2) ?? l("暂无", "n/a")}</div></div>
                <div className="metric-card"><div className="eyebrow">{l("收益", "Return")}</div><div className="metric-card__value">{outcome?.cumulative_return == null ? l("暂无", "n/a") : `${(outcome.cumulative_return * 100).toFixed(2)}%`}</div></div>
              </div>
              <p className="muted">{l("延迟数据源", "Delayed provider")}: {marketObservation.data.provider}。{marketObservation.data.market_status === "closed" || marketObservation.data.market_status === "holiday" ? l("当前未开市；展示的是最近一次权威数据。", "Market is not open; latest displayed value is the most recent authoritative value.") : l("交易时段内报价刷新频率不高于每五分钟一次。", "Quote refreshes no more than once every five minutes during the session.")}</p>
              <p className="muted">{l("数据源状态", "Provider status")}: {term(marketObservation.data.provider_status)}；{l("最近成功时间", "last success")}: {marketObservation.data.last_success_at ? formatDateTime(marketObservation.data.last_success_at) : l("无", "none")}；{l("连续失败次数", "consecutive failures")}: {marketObservation.data.consecutive_failures}。</p>
              {outcome ? <p className="muted">{l("结果", "Outcome")}: {term(outcome.outcome)}；{l("已观察交易日", "observed trading days")} {outcome.observed_trading_days}/60；{l("分类", "classification")}: {term(outcome.error_category ?? "pending")}；{l("评审", "Judge")}: {term(outcome.judge_verdict)}；{l("实际回撤", "realized drawdown")}: {outcome.realized_max_drawdown == null ? term("pending") : `${(outcome.realized_max_drawdown * 100).toFixed(2)}%`}。</p> : <InlineNotice title={l("尚无预测观察记录", "No Prediction Observation")} body={l("请先生成真实分析运行，再比较风险预测与后续真实价格。", "Generate a real analysis run before comparing its risk forecast with real prices.")} />}
              {marketObservation.data.degraded_reasons.length ? <InlineNotice title={l("市场数据已降级", "Market Data Degraded")} tone="warn" body={marketObservation.data.degraded_reasons.map(term).join(", ")} /> : null}
              <div className="button-row"><button className="ghost-button" type="button" disabled={refreshObservation.isPending} onClick={() => refreshObservation.mutate()}>{refreshObservation.isPending ? l("刷新中…", "Refreshing...") : l("刷新延迟行情", "Refresh delayed quote")}</button></div>
            </article>
          ) : null}
          {workspace.selectedRunId ? (
            <article className="story-card" data-testid="trusted-close-research">
              <div className="story-card__header"><strong>{forecast.data?.decision_context === "pre_open" ? l("A股盘前研究", "A-share pre-open research") : l("A股收盘确认研究", "A-share close-confirmed research")}</strong><span className="tag">{term(forecast.data?.data_status.quality_status ?? "checking")}</span></div>
              {forecast.data ? <>
                <div className="metric-strip">
                  <div className="metric-card"><div className="eyebrow">{l("数据截至", "Data As Of")}</div><div className="metric-card__value">{formatDateTime(forecast.data.data_status.as_of)}</div></div>
                  <div className="metric-card"><div className="eyebrow">{l("数据覆盖率", "Data Coverage")}</div><div className="metric-card__value">{Math.round(forecast.data.data_status.coverage_ratio * 100)}%</div></div>
                  <div className="metric-card"><div className="eyebrow">{l("证据覆盖率", "Evidence Coverage")}</div><div className="metric-card__value">{Math.round(forecast.data.evidence_coverage * 100)}%</div></div>
                  <div className="metric-card"><div className="eyebrow">{l("20日回撤超过8%", "20D >8% Drawdown")}</div><div className="metric-card__value">{forecast.data.drawdown_20d ? `${Math.round(forecast.data.drawdown_20d.threshold_probability * 100)}%` : term("abstain")}</div></div>
                </div>
                <p className="muted">{l("数据等级", "Data tier")}：{forecast.data.data_tier}；{l("模型状态", "model status")}：{term("research_only")}；{forecast.data.decision_context === "pre_open" ? l("下一交易日盘前", "next-session pre-open") : l("收盘确认", "close-confirmed")}{l("研究，不是盘中交易信号。决策时间", " research, not an intraday signal. Decision time")}：{forecast.data.decision_time ? formatDateTime(forecast.data.decision_time) : term("unavailable")}；{l("缓存", "cache")}：{term(forecast.data.data_status.cache_state)}；{l("事件", "events")}：{term(forecast.data.data_status.event_coverage_status)}；{l("来源", "providers")}：{forecast.data.data_status.provider_chain.join(" → ") || term("unavailable")}。</p>
                {forecast.data.direction_5d ? <p>{l("5日方向", "5-day direction")}：{t("research.up")} {Math.round(forecast.data.direction_5d.up * 100)}%，{t("research.down")} {Math.round(forecast.data.direction_5d.down * 100)}%，{t("research.flat")} {Math.round(forecast.data.direction_5d.flat * 100)}%。</p> : <p className="muted">{l("1日、5日方向和20日收益只有在对应研究清单与全部哈希通过校验后才展示。", "1/5-day direction and 20-day return appear only after roster and hash validation.")}</p>}
                {forecast.data.gating_reasons.length ? <InlineNotice title={l("研究门禁", "Research Gates")} tone="warn" body={forecast.data.gating_reasons.map(term).join("; ")} /> : null}
              </> : <p className="muted">{l("该历史运行暂无冻结的收盘确认预测。", "No frozen close-confirmed forecast is available for this historical run.")}</p>}
            </article>
          ) : null}
          {workspace.selectedRunId ? (
            <article className="story-card" data-testid="directional-research-status">
              <div className="story-card__header"><strong>{l("仅供研究的方向概率", "Research-only Direction Signal")}</strong><span className="tag">{term(direction.data?.status ?? "checking")}</span></div>
              <p className="muted">{l("方向只以上涨、下跌、横盘概率展示。旧的确定性方向状态为", "Direction is shown only as up/down/flat probabilities. The legacy deterministic state is")} {term(direction.data?.status ?? "unavailable")}，{l("不作为研究结论或交易指令。", "and is not a research conclusion or trading instruction.")}</p>
            </article>
          ) : null}
          {workspace.priceChart.length ? (
            <div className="chart-frame" aria-label={l("标的累计收益与回撤图", "Asset cumulative return and drawdown chart")}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={workspace.priceChart} margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" minTickGap={28} />
                  <YAxis unit="%" width={52} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(2)}%`]} />
                  <Legend />
                  <Line type="monotone" dataKey="returnPct" name={l("累计收益", "Cumulative return")} stroke="#2c6e62" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="drawdownPct" name={l("回撤", "Drawdown")} stroke="#a85c35" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <InlineNotice title={l("价格序列不可用", "Price Series Unavailable")} tone="warn" body={l("当前没有可用于绘图的带时间戳真实价格序列。", "No timestamped real price series is available for charting.")} />
          )}
          {workspace.selectedRunId ? (
            <div className="button-row">
              <button
                data-testid="toggle-run-scoped-research"
                className="ghost-button"
                type="button"
                onClick={workspace.toggleRunScopedResearch}
              >
                {workspace.onlySelectedRunResearch ? l("显示该标的全部研究", "Show All Asset Research") : l("仅查看所选运行", "Scope Research To Selected Run")}
              </button>
            </div>
          ) : null}
          {workspace.assetId && !workspace.hasRuns ? (
            <InlineNotice
              title={l("尚无历史运行", "No Historical Run")}
              body={l("研究数据可以浏览，但只有生成不可变分析运行后，报告和证据范围才可回放。", "Research data can be browsed, but reports and evidence scope become replayable only after an immutable analysis run is generated.")}
            />
          ) : null}
          {workspace.hasQueryFailure ? (
            <InlineNotice
              title={l("研究数据加载失败", "Research Data Failed To Load")}
              tone="block"
              body={workspace.failureMessage}
            />
          ) : null}
          {workspace.selectedRunMissingSource ? (
            <InlineNotice
              title={l("所选运行来源缺失", "Selected Run Source Missing")}
              tone="block"
              body={l("所选运行缺少模式、数据源或数据截至时间。记录保留用于审计，但使用报告前必须重新生成。", "This selected run is missing mode, provider, or as-of metadata. Keep it visible for audit, but regenerate before using the report.")}
            />
          ) : null}
          {workspace.selectedRunStaleSource ? (
            <InlineNotice
              title={l("所选运行来源已过期", "Selected Run Source Is Stale")}
              tone="warn"
              body={l("所选报告仍固定绑定原始运行，但来源时间已超出新鲜度窗口。", "The selected report remains fixed to its original run, but its source timestamp is outside the freshness window.")}
            />
          ) : null}
          {workspace.dossier ? <SelectedRunDossierCard dossier={workspace.dossier} showMetrics /> : null}
          <div className="stack-list">
            {workspace.evidenceView.focusedEvidence ? (
              <article className="story-card story-card--focused">
                <div className="story-card__header">
                  <strong>{l("来自运行血缘的聚焦证据", "Focused From Run Lineage")}</strong>
                  <button className="ghost-button" type="button" onClick={workspace.clearFocusedEvidence}>
                    {l("取消聚焦", "Clear Focus")}
                  </button>
                </div>
                <p className="muted">
                  {l("正在查看所选运行时间线条目关联的证据。", "Reviewing the evidence currently linked from the selected run timeline entry.")}
                </p>
              </article>
            ) : null}
            {workspace.onlySelectedRunResearch && workspace.selectedRunId ? (
              <article className="story-card">
                <div className="story-card__header">
                  <strong>{l("运行范围研究", "Run-Scoped Research")}</strong>
                  <span className="tag">
                    {workspace.runScopeSummary?.evidence_count ?? 0} {l("条证据", "evidence")} / {workspace.runScopeSummary?.report_count ?? 0} {l("份报告", "reports")}
                  </span>
                </div>
                <p className="muted">
                  {l("证据和报告已限定为所选分析运行冻结时捕获的不可变集合。", "Evidence and reports are filtered to the immutable set captured on the selected analysis run.")}
                </p>
              </article>
            ) : null}
            {workspace.evidenceView.orderedEvidence.map((entry) => (
              <article
                className={`story-card ${workspace.selectedEvidenceId === entry.id ? "story-card--focused" : ""}`}
                key={entry.id}
              >
                <div className="story-card__header">
                  <strong>{term(entry.title)}</strong>
                  <SourceBadge provenance={entry.provenance} />
                </div>
                <p>{term(entry.summary)}</p>
              </article>
            ))}
            {workspace.onlySelectedRunResearch && workspace.evidenceView.orderedEvidence.length === 0 ? (
              <p className="muted">{l("所选运行尚未关联持久化证据。", "The selected run has no persisted evidence linked yet.")}</p>
            ) : null}
          </div>
          <div className="stack-list">
            {workspace.filteredReports.map((report) => (
              <article
                className={`story-card ${workspace.selectedRunId && report.analysis_run_id === workspace.selectedRunId ? "story-card--focused" : ""}`}
                key={report.id}
              >
                <div className="story-card__header">
                  <strong>{term(report.title)}</strong>
                  <span className="tag">{report.report_version}</span>
                </div>
                <p>{term(report.thesis)}</p>
              </article>
            ))}
            {workspace.onlySelectedRunResearch && workspace.filteredReports.length === 0 ? (
              <p className="muted">{l("所选运行尚无生成报告。", "The selected run has no generated reports yet.")}</p>
            ) : null}
          </div>
          </details>
        </>
      ) : (
        <p className="muted">{l("请选择研究对象，以查看证据、价格分层和生成报告。", "Select an asset to inspect evidence, price layering, and generated reports.")}</p>
      )}
    </Panel>
  );
}
