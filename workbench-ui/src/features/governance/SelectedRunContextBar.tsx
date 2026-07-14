import { SourceBadge } from "../../components/SourceBadge";
import { useRunReplaySummaryQuery } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";
import { buildSelectedRunContext } from "./runContextModel";
import { formatQueryFailure, hasMissingSourceMetadata, isStaleAsOf } from "./runStatus";

export function SelectedRunContextBar() {
  const selectedAssetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const onlySelectedRunResearch = useWorkbenchStore((state) => state.onlySelectedRunResearch);
  const focusRunWorkspace = useWorkbenchStore((state) => state.focusRunWorkspace);
  const replaySummaryQuery = useRunReplaySummaryQuery(selectedRunId, selectedAssetId);
  const context = buildSelectedRunContext(replaySummaryQuery.data, onlySelectedRunResearch);
  const failureMessage = formatQueryFailure(replaySummaryQuery.error, "Unable to load the selected run context.");

  if (!selectedAssetId || !selectedRunId) {
    return null;
  }

  if (!context) {
    return (
      <section className="run-context-bar">
        <div className="run-context-bar__copy">
          <div className="eyebrow">Selected Run</div>
          <strong>{replaySummaryQuery.isError ? "Run context unavailable" : "Loading immutable analysis snapshot..."}</strong>
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
              <div className="eyebrow">Selected Run</div>
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
            Replaying {context.assetName} from the frozen analysis snapshot captured on{" "}
            {context.capturedAt.slice(0, 10)}. Report title: {context.reportTitle}
          </p>
          {missingSourceMetadata ? <p className="muted">Source metadata is incomplete for this run. Treat conclusions as blocked until rerun.</p> : null}
          {staleSource ? <p className="muted">Run snapshot is stale relative to current time. Review for replay, not for fresh action.</p> : null}
        </div>
      </div>
      <div className="run-context-bar__metrics">
        <div className="metric-card">
          <div className="eyebrow">Judge</div>
          <div className="metric-card__value">{context.judgeVerdict}</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">Action</div>
          <div className="metric-card__value">{context.recommendationAction}</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">Evidence / Reports</div>
          <div className="metric-card__value">
            {context.evidenceCount} / {context.reportCount}
          </div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">Synthetic Share</div>
          <div className="metric-card__value">{Math.round(context.syntheticShare * 100)}%</div>
        </div>
        <div className="metric-card">
          <div className="eyebrow">Research Scope</div>
          <div className="metric-card__value">
            {context.onlySelectedRunResearch ? "Selected run" : "Asset-wide"}
          </div>
        </div>
      </div>
      <div className="run-context-bar__meta">
        <span className="tag">Created {context.createdAt.slice(0, 10)}</span>
        <span className="tag">{context.gateCount} gates</span>
        <span className="tag">{context.fallbackCount} fallbacks</span>
        <button className="ghost-button" type="button" onClick={() => focusRunWorkspace(null)}>
          Exit Run Replay
        </button>
      </div>
    </section>
  );
}
