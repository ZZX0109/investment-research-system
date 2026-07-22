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
import { useDeploymentStatusQuery, useDirectionalForecastQuery, useMarketObservationQuery, useRefreshMarketObservationMutation, useResearchAcceptanceQuery, useResearchForecastQuery, useResearchModelRostersQuery, useResearchShadowSessionsQuery, useResearchShadowSummaryQuery } from "../../hooks/useWorkbenchQueries";

export function ResearchPanel() {
  const { t, language } = useI18n();
  const workspace = useResearchWorkspace();
  const deployment = useDeploymentStatusQuery();
  const acceptance = useResearchAcceptanceQuery();
  const trustedCard = deployment.data?.trusted_risk_gate;
  const publicExperiment = deployment.data?.public_experiment;
  const marketObservation = useMarketObservationQuery(workspace.assetId);
  const outcome = marketObservation.data?.outcomes.find((item) => item.run_id === workspace.selectedRunId) ?? marketObservation.data?.outcomes[0];
  const direction = useDirectionalForecastQuery(workspace.selectedRunId);
  const forecast = useResearchForecastQuery(workspace.selectedRunId);
  const refreshObservation = useRefreshMarketObservationMutation(workspace.assetId);
  const shadow = useResearchShadowSessionsQuery(workspace.assetTicker);
  const shadowSummary = useResearchShadowSummaryQuery(workspace.assetTicker);
  const rosters = useResearchModelRostersQuery();
  const taskStatus = (task: string) => forecast.data?.tasks.find((item) => item.task === task)?.status ?? acceptance.data?.tasks?.[task]?.status ?? "unavailable";
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
              <StatusBadge status={forecast.data?.data_status.quality_status ?? "unavailable"} />
            </div>
            <p className="muted">
              {language === "zh-CN"
                ? <>免费公开数据固定为 research_pit；历史可见时间未完全证明，永不自动提升为正式 PIT。数据覆盖 {forecast.data ? `${Math.round(forecast.data.data_status.coverage_ratio * 100)}%` : t("hero.waiting")}，缓存 {forecast.data?.data_status.cache_state ?? "unavailable"}，事件 {forecast.data?.data_status.event_coverage_status ?? "unsupported"}。</>
                : <>Public data remains research_pit. Historical visibility is not fully proven and is never promoted to formal PIT. Coverage: {forecast.data ? `${Math.round(forecast.data.data_status.coverage_ratio * 100)}%` : t("hero.waiting")}; cache: {forecast.data?.data_status.cache_state ?? "unavailable"}; events: {forecast.data?.data_status.event_coverage_status ?? "unsupported"}.</>}
            </p>
            {forecast.data?.data_status.reasons.length ? <InlineNotice title={language === "zh-CN" ? "数据降级原因" : "Data degradation reasons"} tone="warn" body={forecast.data.data_status.reasons.join("；")} /> : null}
          </article>
          <article className="story-card" data-testid="cn-research-backend-status">
            <div className="story-card__header">
              <strong>{t("research.backendStatus")}</strong>
              <span className="tag">{acceptance.data?.status ?? "blocked"}</span>
            </div>
            <div className="metric-strip">
              <MetricCard label={t("research.data")} value={forecast.data?.data_status.quality_status ?? "unavailable"} tone={forecast.data?.data_status.quality_status === "passed" ? "good" : "warn"} />
              <MetricCard label={t("research.training")} value={forecast.data?.training_status ?? "unavailable"} />
              <MetricCard label={t("research.prediction")} value={forecast.data?.prediction_status ?? "unavailable"} tone={forecast.data?.prediction_status === "research_only" ? "good" : "warn"} />
              <MetricCard label={t("research.evidence")} value={forecast.data?.evidence_status ?? "missing"} />
            </div>
            <p className="muted">{language === "zh-CN" ? "模型" : "Model"}: {forecast.data?.model_status ?? "unavailable"}; deployment_ready: false; {language === "zh-CN" ? "研究级公开数据，不构成投资建议。" : "public research data, not investment advice."}</p>
            <p className="muted">{t("research.provider")}: AKShare {t("research.success")} {acceptance.data?.data?.akshare_success_count ?? "n/a"}, Baostock {t("research.success")} {acceptance.data?.data?.baostock_success_count ?? "n/a"}, {t("research.failures")} {acceptance.data?.data?.failed_count ?? "n/a"}, {t("research.fallbacks")} {acceptance.data?.data?.fallback_count ?? "n/a"}.</p>
            {(forecast.data?.blocking_reasons ?? acceptance.data?.blocking_reasons ?? []).length ? <InlineNotice title={t("research.blockingReasons")} tone="warn" body={(forecast.data?.blocking_reasons ?? acceptance.data?.blocking_reasons ?? []).join("；")} /> : null}
            {(forecast.data?.abstain_reasons ?? []).length ? <InlineNotice title={t("research.abstainReasons")} tone="warn" body={forecast.data?.abstain_reasons.join("；") ?? ""} /> : null}
          </article>
          <article className="story-card" data-testid="cn-research-roster">
            <div className="story-card__header">
              <strong>{t("research.roster")}</strong>
              <span className="tag">{rosters.data?.length ?? 0} scopes</span>
            </div>
            {(rosters.data ?? []).length ? (
              <div className="stack-list">
                {rosters.data?.map((roster) => (
                  <p key={roster.roster_hash}>
                    {roster.cohort} · {roster.task}：primary {roster.primary.candidate_name} / fallback {roster.fallback.candidate_name} · research_only · deployment_ready=false · roster hash {roster.roster_hash.slice(0, 12)}
                  </p>
                ))}
              </div>
            ) : <EmptyState title={t("research.rosterEmpty")} body={t("research.rosterEmptyBody")} />}
          </article>
          <article className="story-card" data-testid="cn-research-task-results">
            <div className="story-card__header"><strong>{t("research.tasks")}</strong><span className="tag">{t("research.notSignal")}</span></div>
            {forecast.data && ["research_only", "approved", "fallback"].includes(forecast.data.prediction_status) && !forecast.data.abstained ? (
              <div className="task-forecast-grid">
                <TaskForecastCard task="01D" title={t("research.direction")} status={taskStatus("direction_1d")} model={forecast.data.tasks.find((item) => item.task === "direction_1d")?.model_version} value={forecast.data.direction_1d ? `${t("research.up")} ${Math.round(forecast.data.direction_1d.up * 100)}%` : "unavailable"} detail={forecast.data.direction_1d ? <span>{t("research.down")} {Math.round(forecast.data.direction_1d.down * 100)}% · {t("research.flat")} {Math.round(forecast.data.direction_1d.flat * 100)}%</span> : null} />
                <TaskForecastCard task="05D" title={t("research.direction")} status={taskStatus("direction_5d")} model={forecast.data.tasks.find((item) => item.task === "direction_5d")?.model_version} value={forecast.data.direction_5d ? `${t("research.up")} ${Math.round(forecast.data.direction_5d.up * 100)}%` : "unavailable"} detail={forecast.data.direction_5d ? <span>{t("research.down")} {Math.round(forecast.data.direction_5d.down * 100)}% · {t("research.flat")} {Math.round(forecast.data.direction_5d.flat * 100)}%</span> : null} />
                <TaskForecastCard task="20D" title={t("research.return")} status={taskStatus("return_20d")} model={forecast.data.tasks.find((item) => item.task === "return_20d")?.model_version} value={forecast.data.return_20d ? [forecast.data.return_20d.p10, forecast.data.return_20d.p50, forecast.data.return_20d.p90].map((value) => `${(value * 100).toFixed(1)}%`).join(" / ") : "unavailable"} detail={<EvidenceHash label="snapshot" value={forecast.data.market_snapshot_hash} />} />
                <TaskForecastCard task="DD20" title={t("research.drawdown")} status={taskStatus("drawdown_20d")} model={forecast.data.tasks.find((item) => item.task === "drawdown_20d")?.model_version} value={forecast.data.drawdown_20d ? `${Math.round(forecast.data.drawdown_20d.threshold_probability * 100)}%` : "unavailable"} detail={<EvidenceHash label="snapshot" value={forecast.data.market_snapshot_hash} />} />
              </div>
            ) : <InlineNotice title={forecast.data?.prediction_status === "unavailable" ? t("research.taskUnavailable") : t("research.insufficientEvidence")} tone="warn" body={forecast.data?.abstain_reasons.join("；") || forecast.data?.gating_reasons.join("；") || t("research.waitingEvidence")} />}
            {forecast.data?.influence_facts.length ? <p className="muted">{t("research.influence")}: {forecast.data.influence_facts.join("；")}。{t("research.nonCausal")}</p> : null}
            <div className="stack-list">
              {(["direction_1d", "direction_5d", "return_20d", "drawdown_20d"] as const).map((task) => (
                <p key={task}>{task}：{taskStatus(task)}{taskReasons(task).length ? ` · ${taskReasons(task).join("；")}` : ""}</p>
              ))}
            </div>
          </article>
          <article className="story-card" data-testid="research-shadow-summary">
            <div className="story-card__header"><strong>{t("research.shadow")}</strong><StatusBadge status={shadowSummary.data?.valid_session_count ? "partial" : "abstain"} /></div>
            {(shadow.data ?? []).length ? (
              <>
                <ShadowProgress sessionCount={shadowSummary.data?.session_count ?? shadow.data?.length ?? 0} validCount={shadowSummary.data?.valid_session_count ?? 0} abstainCount={shadowSummary.data?.abstained_count ?? 0} completed={shadowSummary.data?.completed_outcomes ?? {}} forwardStatus={shadowSummary.data?.forward_report_20_status ?? "pending"} primaryStatus={shadowSummary.data?.primary_change_60_status ?? "blocked"} />
                {(shadow.data ?? []).slice(0, 3).map((item) => (
                  <p key={item.id}>{item.trade_date} · {item.decision_context} · {item.task} · {item.abstained ? `abstain: ${item.abstain_reasons.join(", ")}` : "frozen"}</p>
                ))}
              </>
            ) : <EmptyState title={t("research.noShadow")} body={t("research.noShadowBody")} />}
          </article>
          <div className="metric-strip">
            <div className="metric-card">
              <div className="eyebrow">Latest Close</div>
              <div className="metric-card__value">{workspace.latestCloseLabel}</div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">Evidence</div>
              <div className="metric-card__value">
                {workspace.evidenceCount} / {workspace.totalEvidenceCount}
              </div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">Runs / Reports</div>
              <div className="metric-card__value">
                {workspace.runCount} / {workspace.filteredReportsCount}
              </div>
            </div>
            <div className="metric-card">
              <div className="eyebrow">Configured Providers</div>
              <div className="metric-card__value">{workspace.providerNamesLabel}</div>
            </div>
          </div>
          {trustedCard ? (
            <article className="story-card" data-testid="trusted-risk-gate-card">
              <div className="story-card__header">
                <strong>Research Governance Gate</strong>
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
                <strong>Experiment Provenance</strong>
                <span className="tag">{String(publicExperiment.schema_version ?? "unavailable")}</span>
              </div>
              <p className="muted">
                Training run {String((publicExperiment.identity as Record<string, unknown> | undefined)?.training_run_id ?? "n/a")};
                &nbsp; markets: {Array.isArray(publicExperiment.included_markets) ? publicExperiment.included_markets.join(", ") : "n/a"}.
              </p>
            </article>
          ) : null}
          {marketObservation.data ? (
            <article className="story-card" data-testid="market-observation-panel">
              <div className="story-card__header"><strong>研究风险与后续价格</strong><span className="tag">{marketObservation.data.market_status}</span></div>
              <div className="metric-strip">
                <div className="metric-card"><div className="eyebrow">Risk Forecast</div><div className="metric-card__value">{outcome?.predicted_risk == null ? "n/a" : `${Math.round(outcome.predicted_risk * 100)}%`}</div></div>
                <div className="metric-card"><div className="eyebrow">Predicted At</div><div className="metric-card__value">{outcome?.prediction_price?.toFixed(2) ?? "n/a"}</div></div>
                <div className="metric-card"><div className="eyebrow">Latest Real</div><div className="metric-card__value">{marketObservation.data.latest_price?.toFixed(2) ?? "n/a"}</div></div>
                <div className="metric-card"><div className="eyebrow">Return</div><div className="metric-card__value">{outcome?.cumulative_return == null ? "n/a" : `${(outcome.cumulative_return * 100).toFixed(2)}%`}</div></div>
              </div>
              <p className="muted">Delayed provider: {marketObservation.data.provider}. {marketObservation.data.market_status === "closed" || marketObservation.data.market_status === "holiday" ? "Market is not open; latest displayed value is the most recent authoritative value." : "Quote refreshes no more than once every five minutes during the session."}</p>
              <p className="muted">Provider status: {marketObservation.data.provider_status}; last success: {marketObservation.data.last_success_at ?? "none"}; consecutive failures: {marketObservation.data.consecutive_failures}.</p>
              {outcome ? <p className="muted">Outcome: {outcome.outcome}; observed {outcome.observed_trading_days}/60 trading days; classification: {outcome.error_category ?? "pending"}; Judge: {outcome.judge_verdict ?? "n/a"}; realized drawdown: {outcome.realized_max_drawdown == null ? "pending" : `${(outcome.realized_max_drawdown * 100).toFixed(2)}%`}.</p> : <InlineNotice title="No Prediction Observation" body="Generate a real analysis run before comparing its risk forecast with real prices." />}
              {marketObservation.data.degraded_reasons.length ? <InlineNotice title="Market Data Degraded" tone="warn" body={marketObservation.data.degraded_reasons.join(", ")} /> : null}
              <div className="button-row"><button className="ghost-button" type="button" disabled={refreshObservation.isPending} onClick={() => refreshObservation.mutate()}>{refreshObservation.isPending ? "Refreshing..." : "Refresh delayed quote"}</button></div>
            </article>
          ) : null}
          {workspace.selectedRunId ? (
            <article className="story-card" data-testid="trusted-close-research">
              <div className="story-card__header"><strong>{forecast.data?.decision_context === "pre_open" ? "A股盘前研究" : "A股收盘确认研究"}</strong><span className="tag">{forecast.data?.data_status.quality_status ?? "checking"}</span></div>
              {forecast.data ? <>
                <div className="metric-strip">
                  <div className="metric-card"><div className="eyebrow">Data As Of</div><div className="metric-card__value">{new Date(forecast.data.data_status.as_of).toLocaleString()}</div></div>
                  <div className="metric-card"><div className="eyebrow">Data Coverage</div><div className="metric-card__value">{Math.round(forecast.data.data_status.coverage_ratio * 100)}%</div></div>
                  <div className="metric-card"><div className="eyebrow">Evidence Coverage</div><div className="metric-card__value">{Math.round(forecast.data.evidence_coverage * 100)}%</div></div>
                  <div className="metric-card"><div className="eyebrow">20D &gt;8% Drawdown</div><div className="metric-card__value">{forecast.data.drawdown_20d ? `${Math.round(forecast.data.drawdown_20d.threshold_probability * 100)}%` : "abstain"}</div></div>
                </div>
                <p className="muted">数据等级：{forecast.data.data_tier}；模型状态：research_only；{forecast.data.decision_context === "pre_open" ? "下一交易日盘前" : "收盘确认"}研究，不是盘中交易信号。决策时间：{forecast.data.decision_time ? new Date(forecast.data.decision_time).toLocaleString() : "unavailable"}；缓存：{forecast.data.data_status.cache_state}；事件：{forecast.data.data_status.event_coverage_status}；来源：{forecast.data.data_status.provider_chain.join(" → ") || "unavailable"}。</p>
                {forecast.data.direction_5d ? <p>5-day direction: up {Math.round(forecast.data.direction_5d.up * 100)}%, down {Math.round(forecast.data.direction_5d.down * 100)}%, flat {Math.round(forecast.data.direction_5d.flat * 100)}%.</p> : <p className="muted">1/5 日方向和 20 日收益只有在对应研究 roster 与全部哈希通过校验后才展示。</p>}
                {forecast.data.gating_reasons.length ? <InlineNotice title="Research Gates" tone="warn" body={forecast.data.gating_reasons.join("; ")} /> : null}
              </> : <p className="muted">No frozen trusted-close forecast is available for this historical run.</p>}
            </article>
          ) : null}
          {workspace.selectedRunId ? (
            <article className="story-card" data-testid="directional-research-status">
              <div className="story-card__header"><strong>Research-only Direction Signal</strong><span className="tag">{direction.data?.status ?? "checking"}</span></div>
              <p className="muted">方向只以 up/down/flat 概率展示。旧的确定性方向状态为 {direction.data?.status ?? "unavailable"}，不作为研究结论或交易指令。</p>
            </article>
          ) : null}
          {workspace.priceChart.length ? (
            <div className="chart-frame" aria-label="Asset cumulative return and drawdown chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={workspace.priceChart} margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" minTickGap={28} />
                  <YAxis unit="%" width={52} />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(2)}%`]} />
                  <Legend />
                  <Line type="monotone" dataKey="returnPct" name="Cumulative return" stroke="#2c6e62" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="drawdownPct" name="Drawdown" stroke="#a85c35" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <InlineNotice title="Price Series Unavailable" tone="warn" body="No timestamped real price series is available for charting." />
          )}
          {workspace.selectedRunId ? (
            <div className="button-row">
              <button
                data-testid="toggle-run-scoped-research"
                className="ghost-button"
                type="button"
                onClick={workspace.toggleRunScopedResearch}
              >
                {workspace.onlySelectedRunResearch ? "Show All Asset Research" : "Scope Research To Selected Run"}
              </button>
            </div>
          ) : null}
          {workspace.assetId && !workspace.hasRuns ? (
            <InlineNotice
              title="No Historical Run"
              body="Research data can be browsed, but reports and evidence scope become replayable only after an immutable analysis run is generated."
            />
          ) : null}
          {workspace.hasQueryFailure ? (
            <InlineNotice
              title="Research Data Failed To Load"
              tone="block"
              body={workspace.failureMessage}
            />
          ) : null}
          {workspace.selectedRunMissingSource ? (
            <InlineNotice
              title="Selected Run Source Missing"
              tone="block"
              body="This selected run is missing mode, provider, or as-of metadata. Keep it visible for audit, but regenerate before using the report."
            />
          ) : null}
          {workspace.selectedRunStaleSource ? (
            <InlineNotice
              title="Selected Run Source Is Stale"
              tone="warn"
              body="The selected report remains fixed to its original run, but its source timestamp is outside the freshness window."
            />
          ) : null}
          {workspace.dossier ? <SelectedRunDossierCard dossier={workspace.dossier} showMetrics /> : null}
          <div className="stack-list">
            {workspace.evidenceView.focusedEvidence ? (
              <article className="story-card story-card--focused">
                <div className="story-card__header">
                  <strong>Focused From Run Lineage</strong>
                  <button className="ghost-button" type="button" onClick={workspace.clearFocusedEvidence}>
                    Clear Focus
                  </button>
                </div>
                <p className="muted">
                  Reviewing the evidence currently linked from the selected run timeline entry.
                </p>
              </article>
            ) : null}
            {workspace.onlySelectedRunResearch && workspace.selectedRunId ? (
              <article className="story-card">
                <div className="story-card__header">
                  <strong>Run-Scoped Research</strong>
                  <span className="tag">
                    {workspace.runScopeSummary?.evidence_count ?? 0} evidence / {workspace.runScopeSummary?.report_count ?? 0} reports
                  </span>
                </div>
                <p className="muted">
                  Evidence and reports are filtered to the immutable set captured on the selected analysis run.
                </p>
              </article>
            ) : null}
            {workspace.evidenceView.orderedEvidence.map((entry) => (
              <article
                className={`story-card ${workspace.selectedEvidenceId === entry.id ? "story-card--focused" : ""}`}
                key={entry.id}
              >
                <div className="story-card__header">
                  <strong>{entry.title}</strong>
                  <SourceBadge provenance={entry.provenance} />
                </div>
                <p>{entry.summary}</p>
              </article>
            ))}
            {workspace.onlySelectedRunResearch && workspace.evidenceView.orderedEvidence.length === 0 ? (
              <p className="muted">The selected run has no persisted evidence linked yet.</p>
            ) : null}
          </div>
          <div className="stack-list">
            {workspace.filteredReports.map((report) => (
              <article
                className={`story-card ${workspace.selectedRunId && report.analysis_run_id === workspace.selectedRunId ? "story-card--focused" : ""}`}
                key={report.id}
              >
                <div className="story-card__header">
                  <strong>{report.title}</strong>
                  <span className="tag">{report.report_version}</span>
                </div>
                <p>{report.thesis}</p>
              </article>
            ))}
            {workspace.onlySelectedRunResearch && workspace.filteredReports.length === 0 ? (
              <p className="muted">The selected run has no generated reports yet.</p>
            ) : null}
          </div>
        </>
      ) : (
        <p className="muted">Select an asset to inspect evidence, price layering, and generated reports.</p>
      )}
    </Panel>
  );
}
