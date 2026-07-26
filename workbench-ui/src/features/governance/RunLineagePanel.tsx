import { startTransition, useEffect, useState } from "react";
import { Panel } from "../../components/Panel";
import { SourceBadge } from "../../components/SourceBadge";
import {
  useAnalysisRunsQuery,
  useAuditRecordsQuery,
  useDomainCatalogQuery,
  useRunComparisonQuery,
  useRunLineageDetailSummaryQuery,
  useRunLineageQuery
} from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "./runStatus";

export function RunLineagePanel() {
  const { l, term } = useI18n();
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const setSelectedRunId = useWorkbenchStore((state) => state.setSelectedRunId);
  const focusRunWorkspace = useWorkbenchStore((state) => state.focusRunWorkspace);
  const setSelectedEvidenceId = useWorkbenchStore((state) => state.setSelectedEvidenceId);
  const catalogQuery = useDomainCatalogQuery();
  const runsQuery = useAnalysisRunsQuery(selectedAssetId);
  const timelineQuery = useRunLineageQuery(selectedAssetId);
  const detailSummaryQuery = useRunLineageDetailSummaryQuery(selectedRunId, selectedAssetId);
  const auditQuery = useAuditRecordsQuery();

  const runs = runsQuery.data ?? [];
  const comparisonRunId =
    selectedRunId && runs.length > 0 ? runs[runs.findIndex((run) => run.id === selectedRunId) + 1]?.id ?? null : null;
  const detailSummary = detailSummaryQuery.data;
  const timeline = timelineQuery.data;
  const providerConfig = catalogQuery.data?.analysis_provider_config;
  const providers = catalogQuery.data?.analysis_providers ?? [];
  const comparisonQuery = useRunComparisonQuery(selectedRunId, comparisonRunId, selectedAssetId);
  const comparisonSummary = comparisonQuery.data ?? null;
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const detailFailure = formatQueryFailure(detailSummaryQuery.error, l("无法加载运行血缘详情。", "Unable to load run lineage detail."));
  const timelineFailure = formatQueryFailure(timelineQuery.error, l("无法加载运行血缘时间线。", "Unable to load run lineage timeline."));

  useEffect(() => {
    if (runs.length === 0) {
      return;
    }
    if (selectedRunId && runs.some((run) => run.id === selectedRunId)) {
      return;
    }
    startTransition(() => {
      setSelectedRunId(runs[0]?.id ?? null);
    });
  }, [runs, selectedRunId, setSelectedRunId]);

  useEffect(() => {
    if (!timeline?.entries.length) {
      setExpandedRunId(null);
      return;
    }
    if (expandedRunId && timeline.entries.some((entry) => entry.run_id === expandedRunId)) {
      return;
    }
    setExpandedRunId(timeline.entries[0]?.run_id ?? null);
  }, [timeline, expandedRunId]);

  const lineageAudit = (auditQuery.data ?? []).filter((record) => {
    if (!selectedRunId || !selectedAssetId) {
      return false;
    }
    return (
      record.target_id === selectedRunId ||
      record.details.analysis_run_id === selectedRunId ||
      record.details.asset_id === selectedAssetId
    );
  });

  return (
    <Panel eyebrow={l("血缘", "Lineage")} title={l("运行血缘", "Run Lineage")}>
      {selectedAssetId ? (
        <article className="story-card">
          <div className="story-card__header">
            <strong>{l("运行历史", "Run History")}</strong>
            <span className="tag">{runs.length}</span>
          </div>
          {runs.length > 0 ? (
            <div className="asset-list">
              {runs.map((run) => (
                <button
                  key={run.id}
                  data-testid={`run-history-${run.id}`}
                  className={`asset-card ${selectedRunId === run.id ? "asset-card--active" : ""}`}
                  type="button"
                  onClick={() => focusRunWorkspace(run.id)}
                >
                  <div>
                    <strong>{run.created_at.slice(0, 10)}</strong>
                    <div className="muted mono">{run.id.slice(0, 8)}</div>
                  </div>
                  <span className="tag">{term(run.provenance.data_mode)}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted">{l("该研究对象尚无分析运行。请启动分析以创建可复现快照。", "No analysis runs yet for this asset. Trigger one to create a reproducible snapshot.")}</p>
          )}
        </article>
      ) : null}
      {detailSummary ? (
        <div className="stack-list">
          {hasMissingSourceMetadata(detailSummary) ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{l("血缘元数据缺失", "Lineage Metadata Missing")}</strong>
                <span className="tag">{l("阻断", "BLOCK")}</span>
              </div>
              <p>{l("所选运行缺少必要的来源元数据。记录保留用于审计，但不得作为可信研究结论展示。", "The selected run is missing required source metadata. Keep the record visible for audit, but do not surface it as a trustworthy recommendation.")}</p>
            </article>
          ) : null}
          {isStaleAsOf(detailSummary.as_of) ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{l("血缘快照已过期", "Lineage Snapshot Is Stale")}</strong>
                <span className="tag">{l("暂缓", "HOLD")}</span>
              </div>
              <p>{l("已保存运行仍可回放，但来源时间已超过新鲜度窗口，应重新分析。", "The stored run remains replayable, but the source timestamp is older than the freshness window and should be re-analyzed.")}</p>
            </article>
          ) : null}
          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("1. 数据快照", "1. Snapshot")}</strong>
              <span className="tag">{detailSummary.intake_strategy}</span>
            </div>
            <p className="muted mono">{detailSummary.input_snapshot_ref}</p>
            <ul className="flat-list">
              <li>{l("冻结时间", "Captured at")}: {detailSummary.captured_at}</li>
              <li>{l("模式", "Mode")}: {term(detailSummary.mode)}</li>
              <li>{l("数据源", "Provider")}: {detailSummary.provider}</li>
              <li>{l("数据截至", "As of")}: {detailSummary.as_of ?? l("暂无", "n/a")}</li>
              <li>{l("覆盖设置", "Overrides")}: {detailSummary.overrides.map(term).join(", ") || l("无", "None")}</li>
              <li>{l("数据模式", "Data modes")}: {detailSummary.data_modes.map(term).join(", ") || l("暂无", "n/a")}</li>
              <li>{l("来源类型", "Source types")}: {detailSummary.source_types.map(term).join(", ") || l("暂无", "n/a")}</li>
              <li>{l("最新收盘价", "Latest close")}: {detailSummary.latest_close ?? l("暂无", "n/a")}</li>
            </ul>
          </article>

          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("2. 数据源栈", "2. Provider Stack")}</strong>
              <span className="tag">{providers.length} {l("个已配置", "configured")}</span>
            </div>
            <ul className="flat-list">
              <li>{l("市场数据源配置", "Configured market provider")}: {providerConfig?.market_data_provider ?? l("暂无", "n/a")}</li>
              <li>{l("证据数据源配置", "Configured evidence provider")}: {providerConfig?.evidence_provider ?? l("暂无", "n/a")}</li>
              <li>
                {l("价格采集", "Price intake")}: {detailSummary.price_provider_name}@{detailSummary.price_provider_version} (
                {term(detailSummary.price_provider_status)})
              </li>
              <li>
                {l("证据采集", "Evidence intake")}: {detailSummary.evidence_provider_name}@{detailSummary.evidence_provider_version} (
                {term(detailSummary.evidence_provider_status)})
              </li>
            </ul>
          </article>

          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("3. 评审与观察立场", "3. Judge & Observation Stance")}</strong>
              <span className="tag">{term(detailSummary.judge_verdict)}</span>
            </div>
            <ul className="flat-list">
              <li>{l("评审得分", "Judge score")}: {Math.round(detailSummary.judge_score * 100)}%</li>
              <li>{l("观察立场", "Observation stance")}: {term(detailSummary.recommendation_action)}</li>
              <li>{l("模型置信度", "Model confidence")}: {Math.round(detailSummary.model_confidence * 100)}%</li>
              <li>{l("模型", "Model")}: {detailSummary.model_name}@{detailSummary.model_version}</li>
              <li>{l("模型状态", "Model status")}: {term(detailSummary.model_status)}</li>
              <li>{l("已批准", "Approved")}: {detailSummary.deployment_approved ? l("是", "yes") : l("否", "no")}</li>
              <li>
                {l("风险概率", "Risk probability")}:{" "}
                {detailSummary.risk_probability == null
                  ? "n/a"
                  : `${Math.round(detailSummary.risk_probability * 100)}%`}
              </li>
              <li>{l("特征覆盖率", "Feature coverage")}: {Math.round(detailSummary.feature_coverage * 100)}%</li>
            </ul>
            {detailSummary.missing_features.length > 0 ? (
              <p className="muted">{l("缺失模型特征", "Missing model features")}: {detailSummary.missing_features.join(", ")}</p>
            ) : null}
            {detailSummary.inference_warnings.length > 0 ? (
              <ul className="flat-list">
                {detailSummary.inference_warnings.map((warning) => (
                  <li key={warning}>{term(warning)}</li>
                ))}
              </ul>
            ) : null}
            <p className="muted">{term(detailSummary.recommendation_reasoning)}</p>
          </article>

          <article className="story-card">
            <div className="story-card__header">
              <strong>{l("4. 降级与报告", "4. Fallback & Report")}</strong>
              <span className="tag">{detailSummary.report_version}</span>
            </div>
            <ul className="flat-list">
              {(detailSummary.fallback_reasons.length > 0
                ? detailSummary.fallback_reasons
                : [l("本次运行未记录数据源降级。", "No provider fallback recorded for this run.")]).map((reason) => (
                <li key={reason}>{term(reason)}</li>
              ))}
            </ul>
            {detailSummary.report_title ? <p className="muted">{l("最新报告", "Latest report")}: {term(detailSummary.report_title)}</p> : null}
          </article>

          {comparisonSummary ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{l("5. 与上次运行的变化", "5. Delta vs Prior Run")}</strong>
                <span className="tag">{comparisonSummary.baseline_report_version}</span>
              </div>
              <ul className="flat-list">
                <li>
                  {l("评审变化", "Judge delta")}: {comparisonSummary.judge_score_delta >= 0 ? "+" : ""}
                  {Math.round(comparisonSummary.judge_score_delta * 100)} {l("点", "pts")}
                </li>
                <li>
                  {l("置信度变化", "Confidence delta")}: {comparisonSummary.confidence_delta >= 0 ? "+" : ""}
                  {Math.round(comparisonSummary.confidence_delta * 100)} {l("点", "pts")}
                </li>
                <li>
                  {l("最新收盘价变化", "Latest close delta")}:{" "}
                  {comparisonSummary.latest_close_delta == null
                    ? "n/a"
                    : `${comparisonSummary.latest_close_delta >= 0 ? "+" : ""}${comparisonSummary.latest_close_delta.toFixed(2)}`}
                </li>
                <li>
                  {l("模型版本", "Model version")}: {comparisonSummary.baseline_model_version} {"->"} {comparisonSummary.current_model_version}
                </li>
                <li>
                  {l("报告版本", "Report version")}: {comparisonSummary.baseline_report_version} {"->"} {comparisonSummary.current_report_version}
                </li>
                <li>{l("报告论点是否变化", "Report thesis changed")}: {comparisonSummary.thesis_changed ? l("是", "yes") : l("否", "no")}</li>
              </ul>
              {(comparisonSummary.added_gates.length > 0 ||
                comparisonSummary.removed_gates.length > 0 ||
                comparisonSummary.added_fallbacks.length > 0 ||
                comparisonSummary.removed_fallbacks.length > 0) ? (
                <ul className="flat-list">
                  {comparisonSummary.added_gates.map((reason) => (
                    <li key={`gate-add-${reason}`}>{l("新增门禁", "Gate added")}: {term(reason)}</li>
                  ))}
                  {comparisonSummary.removed_gates.map((reason) => (
                    <li key={`gate-remove-${reason}`}>{l("移除门禁", "Gate removed")}: {term(reason)}</li>
                  ))}
                  {comparisonSummary.added_fallbacks.map((reason) => (
                    <li key={`fallback-add-${reason}`}>{l("新增降级原因", "Fallback added")}: {term(reason)}</li>
                  ))}
                  {comparisonSummary.removed_fallbacks.map((reason) => (
                    <li key={`fallback-remove-${reason}`}>{l("移除降级原因", "Fallback removed")}: {term(reason)}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted">{l("与上次冻结运行相比，门禁和降级原因没有变化。", "No gate or fallback drift versus the prior frozen run.")}</p>
              )}
            </article>
          ) : null}

          {timeline ? (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{comparisonSummary ? l("6. 报告时间线", "6. Report Timeline") : l("5. 报告时间线", "5. Report Timeline")}</strong>
                <span className="tag">{timeline.entries.length}</span>
              </div>
              <div className="stack-list">
                {timeline.entries.map((entry) => {
                  const isExpanded = expandedRunId === entry.run_id;
                  return (
                    <article className="story-card" key={entry.run_id}>
                      <button
                        className={`asset-card ${isExpanded ? "asset-card--active" : ""}`}
                        type="button"
                        onClick={() => {
                          setExpandedRunId(isExpanded ? null : entry.run_id);
                          if (!isExpanded) {
                            focusRunWorkspace(entry.run_id);
                          }
                        }}
                      >
                        <div>
                          <strong>
                            {entry.created_at.slice(0, 10)} | {entry.report_version ?? l("等待中", "pending")}
                          </strong>
                          <div className="muted">
                            {term(entry.judge_verdict)} | {term(entry.price_provider_status)}/{term(entry.evidence_provider_status)}
                          </div>
                        </div>
                        <span className="tag">{entry.audit_actions.length} {l("项事件", "events")}</span>
                      </button>
                      {isExpanded ? (
                        <div className="stack-list">
                          <div className="button-row">
                            <button
                              className="ghost-button"
                              type="button"
                              onClick={() => focusRunWorkspace(entry.run_id)}
                            >
                              {l("在工作台打开本次运行", "Open Run In Workspace")}
                            </button>
                          </div>
                          <p className="muted mono">{entry.input_snapshot_ref}</p>
                          <ul className="flat-list">
                            <li>{l("证据数量", "Evidence count")}: {entry.evidence_count}</li>
                            <li>{l("模型版本", "Model version")}: {entry.model_version ?? l("暂无", "n/a")}</li>
                            <li>{l("观察立场", "Observation stance")}: {term(entry.recommendation_action)}</li>
                            <li>
                              {l("数据构成", "Data mix")}: {l("合成", "synthetic")} {Math.round(entry.synthetic_share * 100)}% / {l("真实", "real")}{" "}
                              {Math.round(entry.real_share * 100)}%
                            </li>
                            <li>{l("模式 / 数据源", "Mode/provider")}: {term(entry.mode)} / {entry.provider}</li>
                            <li>{l("数据截至", "As of")}: {entry.as_of ?? l("暂无", "n/a")}</li>
                            <li>{l("报告生成时间", "Report generated at")}: {entry.report_generated_at ?? l("等待中", "pending")}</li>
                          </ul>
                          {entry.report_title || entry.report_thesis ? (
                            <div>
                              <strong>{entry.report_title ? term(entry.report_title) : l("报告", "Report")}</strong>
                              <p className="muted">{entry.report_thesis ? term(entry.report_thesis) : l("尚未记录报告论点。", "No thesis captured.")}</p>
                            </div>
                          ) : null}
                          {entry.recommendation_reasoning ? (
                            <p className="muted">{entry.recommendation_reasoning}</p>
                          ) : null}
                          {entry.evidence_items.length > 0 ? (
                            <div className="stack-list">
                              {entry.evidence_items.map((evidence) => (
                                <button
                                  className="asset-card"
                                  key={evidence.id}
                                  type="button"
                                  onClick={() => {
                                    focusRunWorkspace(entry.run_id);
                                    setSelectedEvidenceId(evidence.id);
                                  }}
                                >
                                  <div className="story-card__header">
                                    <strong>{term(evidence.title)}</strong>
                                    <SourceBadge
                                      provenance={{
                                        data_mode: evidence.data_mode as "demo" | "sandbox" | "real",
                                        source_type: evidence.source_type as "real" | "synthetic" | "backfilled" | "manual_override",
                                        source_name: "lineage-evidence",
                                        observed_at: entry.created_at,
                                        confidence: 1
                                      }}
                                    />
                                  </div>
                                  <p>{term(evidence.summary)}</p>
                                </button>
                              ))}
                            </div>
                          ) : null}
                          {(entry.gating_reasons.length > 0 || entry.fallback_reasons.length > 0) ? (
                            <ul className="flat-list">
                              {entry.gating_reasons.map((reason) => (
                                <li key={`gate-${entry.run_id}-${reason}`}>{l("门禁", "Gate")}: {term(reason)}</li>
                              ))}
                              {entry.fallback_reasons.map((reason) => (
                                <li key={`fallback-${entry.run_id}-${reason}`}>{l("降级", "Fallback")}: {term(reason)}</li>
                              ))}
                            </ul>
                          ) : null}
                          {entry.audit_actions.length > 0 ? (
                            <p className="muted">{l("审计操作", "Audit actions")}: {entry.audit_actions.map(term).join(", ")}</p>
                          ) : null}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            </article>
          ) : null}

          <article className="story-card">
            <div className="story-card__header">
              <strong>{timeline
                ? (comparisonSummary ? l("7. 审计记录", "7. Audit Trail") : l("6. 审计记录", "6. Audit Trail"))
                : comparisonSummary ? l("6. 审计记录", "6. Audit Trail") : l("5. 审计记录", "5. Audit Trail")}</strong>
              <span className="tag">{lineageAudit.length}</span>
            </div>
            <ul className="flat-list">
              {lineageAudit.length > 0 ? (
                lineageAudit.slice(0, 5).map((record) => (
                  <li key={record.id}>
                    {term(record.action)} [{term(record.provenance.data_mode)}/{term(record.provenance.source_type)}]
                  </li>
                ))
              ) : (
                <li>{l("尚无与本次血缘直接相关的审计事件。", "No lineage-specific audit events yet.")}</li>
              )}
            </ul>
          </article>
        </div>
      ) : (
        <div>
          <p className="muted">{l("加载分析运行后，可查看其快照、数据源栈、评审结果、报告版本和审计血缘。", "Load an analysis run to inspect its snapshot, provider stack, judge result, report version, and audit lineage.")}</p>
          {selectedRunId ? <p className="muted">{detailSummaryQuery.isError ? detailFailure : timelineQuery.isError ? timelineFailure : l("尚未加载运行详情。", "No run details loaded yet.")}</p> : null}
        </div>
      )}
    </Panel>
  );
}
