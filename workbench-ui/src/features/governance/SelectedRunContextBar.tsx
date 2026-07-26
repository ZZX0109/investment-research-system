import { SourceBadge } from "../../components/SourceBadge";
import { useRunReplaySummaryQuery } from "../../hooks/useWorkbenchQueries";
import { useI18n } from "../../i18n";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { buildSelectedRunContext } from "./runContextModel";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "./runStatus";

export function SelectedRunContextBar() {
  const { l, term } = useI18n();
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const mode = useWorkbenchStore((state) => state.mode);
  const onlySelectedRunResearch = useWorkbenchStore((state) => state.onlySelectedRunResearch);
  const focusRunWorkspace = useWorkbenchStore((state) => state.focusRunWorkspace);
  const replaySummaryQuery = useRunReplaySummaryQuery(selectedRunId, selectedAssetId);
  const context = buildSelectedRunContext(replaySummaryQuery.data, onlySelectedRunResearch);
  const failureMessage = formatQueryFailure(replaySummaryQuery.error, l("无法加载所选运行上下文。", "Unable to load the selected run context."));

  // Research mode has its own frozen Research PIT dashboard. Showing the
  // legacy run-replay bar here makes a user think the current result is still
  // a pending historical report.
  if (mode === "research" || !selectedAssetId || !selectedRunId) {
    return null;
  }

  if (!context) {
    return (
      <section className="run-context-bar">
        <div className="run-context-bar__copy">
          <div className="eyebrow">{l("所选运行", "Selected Run")}</div>
          <strong>{replaySummaryQuery.isError ? l("运行上下文不可用", "Run context unavailable") : l("正在加载不可变分析快照…", "Loading immutable analysis snapshot...")}</strong>
          <p className="muted mono">{selectedRunId}</p>
          {replaySummaryQuery.isError ? <p className="muted">{failureMessage}</p> : null}
        </div>
      </section>
    );
  }

  const missingSourceMetadata = hasMissingSourceMetadata({
    mode: context.mode,
    provider: context.provider,
    as_of: context.asOf
  });
  const staleSource = isStaleAsOf(context.asOf);

  return (
    <section className="run-context-bar" data-testid="selected-run-context">
      <div className="run-context-bar__copy">
        <div>
          <div className="story-card__header">
            <div>
              <div className="eyebrow">{l("所选运行", "Selected Run")}</div>
              <strong>
                {context.assetTicker} | {context.reportVersion} | {context.runLabel}
              </strong>
            </div>
            <SourceBadge
              provenance={{
                data_mode: context.dataMode as "demo" | "sandbox" | "real",
                source_type: context.sourceType as "real" | "synthetic" | "backfilled" | "manual_override",
                source_name: context.sourceName,
                observed_at: context.observedAt,
                confidence: context.confidence
              }}
            />
          </div>
          <p className="muted">
            {l(
              `正在回放 ${context.capturedAt.slice(0, 10)} 冻结的 ${context.assetName} 分析快照。报告：${term(context.reportTitle)}`,
              `Replaying ${context.assetName} from the frozen analysis snapshot captured on ${context.capturedAt.slice(0, 10)}. Report title: ${context.reportTitle}`
            )}
          </p>
          {missingSourceMetadata ? <p className="muted">{l("本次运行的来源元数据不完整；重新运行前，结论视为已阻断。", "Source metadata is incomplete for this run. Treat conclusions as blocked until rerun.")}</p> : null}
          {staleSource ? <p className="muted">{l("运行快照相对当前时间已过期，仅供回放复核，不用于最新判断。", "Run snapshot is stale relative to current time. Review for replay, not for fresh action.")}</p> : null}
        </div>
      </div>
      <div className="run-context-bar__metrics">
        <div className="metric-card">
          <div className="eyebrow">{l("评审", "Judge")}</div>
          <div className="metric-card__value">{term(context.judgeVerdict)}</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">{l("观察立场", "Action")}</div>
          <div className="metric-card__value">{term(context.recommendationAction)}</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">{l("证据 / 报告", "Evidence / Reports")}</div>
          <div className="metric-card__value">
            {context.evidenceCount} / {context.reportCount}
          </div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">{l("合成数据占比", "Synthetic Share")}</div>
          <div className="metric-card__value">{Math.round(context.syntheticShare * 100)}%</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">{l("研究范围", "Research Scope")}</div>
          <div className="metric-card__value">
            {context.onlySelectedRunResearch ? l("仅所选运行", "Selected run") : l("整个研究对象", "Asset-wide")}
          </div>
        </div>
      </div>
      <div className="run-context-bar__meta">
        <span className="tag">{l("创建于", "Created")} {context.createdAt.slice(0, 10)}</span>
        <span className="tag">{context.gateCount} {l("项门禁", "gates")}</span>
        <span className="tag">{context.fallbackCount} {l("次降级", "fallbacks")}</span>
        <button className="ghost-button" type="button" onClick={() => focusRunWorkspace(null)}>
          {l("退出运行回放", "Exit Run Replay")}
        </button>
      </div>
    </section>
  );
}
