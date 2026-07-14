import { RefreshCw, ShieldCheck } from "lucide-react";
import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import {
  useCreateResearchAuditMutation,
  useRefreshAssetMutation,
  useResearchCardQuery
} from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function ResearchAuditPanel() {
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const selectedRunId = useWorkbenchStore((state) => state.selectedRunId);
  const mode = useWorkbenchStore((state) => state.mode);
  const card = useResearchCardQuery(assetId);
  const refresh = useRefreshAssetMutation();
  const audit = useCreateResearchAuditMutation();
  const result = card.data?.audit;

  return (
    <Panel
      eyebrow="Research Audit"
      title="Evidence & Decision Gate"
      actions={
        <div className="button-row">
          <button
            className="icon-button"
            type="button"
            title="Refresh real data"
            disabled={!assetId || refresh.isPending}
            onClick={() => assetId && refresh.mutate({ assetId })}
          >
            <RefreshCw size={16} aria-hidden="true" />
            <span>{refresh.isPending ? "Refreshing" : "Refresh"}</span>
          </button>
          <button
            className="icon-button icon-button--primary"
            type="button"
            title="Run research audit"
            disabled={mode !== "real" || !selectedRunId || audit.isPending}
            onClick={() => selectedRunId && audit.mutate(selectedRunId)}
          >
            <ShieldCheck size={16} aria-hidden="true" />
            <span>{audit.isPending ? "Auditing" : "Audit"}</span>
          </button>
        </div>
      }
    >
      {refresh.data ? (
        <InlineNotice
          tone={refresh.data.refresh_run.state === "succeeded" ? "info" : "warn"}
          title={`Refresh ${refresh.data.refresh_run.state}`}
          body={`${refresh.data.refresh_run.price_count} price rows, ${refresh.data.refresh_run.evidence_count} evidence items${refresh.data.refresh_run.cache_hit ? "; timestamped real cache used" : ""}.`}
        />
      ) : null}
      {result ? (
        <>
          <div className="metric-strip">
            <Metric label="Verdict" value={result.verdict.toUpperCase()} tone={result.verdict} />
            <Metric label="Score" value={`${Math.round(result.score * 100)}%`} />
            <Metric label="Evidence budget" value={`${result.evidence_budget}`} />
            <Metric label="Token estimate" value={`${result.token_estimate}`} />
          </div>
          <div className="audit-checks">
            {result.checks.map((check) => (
              <div className="audit-check" key={check.name}>
                <span className={`status-dot status-dot--${check.passed ? "pass" : check.severity}`} />
                <div>
                  <strong>{check.name.replaceAll("_", " ")}</strong>
                  <div className="muted">{check.reason}</div>
                </div>
              </div>
            ))}
          </div>
          <article className="research-note">
            <strong>Contrary view</strong>
            <p>{card.data?.contrary_view}</p>
          </article>
        </>
      ) : (
        <p className="muted">Select an analyzed asset to inspect its evidence and audit gate.</p>
      )}
    </Panel>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric-card">
      <div className="eyebrow">{label}</div>
      <div className={`metric-card__value ${tone ? `metric-card__value--${tone}` : ""}`}>{value}</div>
    </div>
  );
}
