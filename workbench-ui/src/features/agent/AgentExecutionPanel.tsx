import { Ban, BrainCircuit, CheckCircle2, Play, ShieldAlert } from "lucide-react";
import { InlineNotice } from "../../components/InlineNotice";
import { Panel } from "../../components/Panel";
import { useCreateAgentRunMutation } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

const nodes = [
  "task_intake", "task_classification", "plan_generation", "tool_selection",
  "evidence_collection", "structured_feature_build", "model_inference",
  "counter_evidence_search", "self_audit", "repair_or_abstain", "report_generation"
];

export function AgentExecutionPanel() {
  const assetId = useWorkbenchStore((state) => state.selectedAssetId);
  const mode = useWorkbenchStore((state) => state.mode);
  const run = useCreateAgentRunMutation();
  const result = run.data;
  const activeIndex = result?.current_node ? nodes.indexOf(result.current_node) : -1;

  return (
    <Panel
      eyebrow="Evidence-bound Agent"
      title="Single-asset risk research"
      actions={
        <button
          className="icon-button icon-button--primary"
          type="button"
          disabled={!assetId || run.isPending}
          onClick={() => assetId && run.mutate({
            asset_id: assetId,
            task_text: "Evaluate 20-trading-day drawdown risk using point-in-time evidence and abstain when trust gates fail.",
            as_of: new Date().toISOString(),
            user_preference: "conservative"
          })}
        >
          <Play size={16} aria-hidden="true" />
          <span>{run.isPending ? "Running" : "Run Agent"}</span>
        </button>
      }
    >
      {mode !== "real" ? <InlineNotice tone="warn" title="Non-authoritative mode" body="This run will abstain because formal Agent research requires real data." /> : null}
      {run.error ? <InlineNotice tone="error" title="Agent failed" body={run.error.message} /> : null}
      {result ? (
        <>
          <div className="metric-strip">
            <Metric label="State" value={result.state} />
            <Metric label="Gate" value={result.verdict ?? "pending"} />
            <Metric label="LLM" value={`${result.budget.llm_calls_used}/${result.budget.max_llm_calls}`} />
            <Metric label="Tools" value={`${result.budget.tool_calls_used}/${result.budget.max_tool_calls}`} />
          </div>
          <div className="agent-node-grid" aria-label="Agent execution nodes">
            {nodes.map((node, index) => {
              const completed = result.state === "completed" || result.state === "abstained" || index < activeIndex;
              const stopped = result.state === "abstained" && index > activeIndex;
              return (
                <div className={`agent-node agent-node--${stopped ? "stopped" : completed ? "complete" : index === activeIndex ? "active" : "pending"}`} key={node}>
                  {stopped ? <Ban size={14} /> : completed ? <CheckCircle2 size={14} /> : index === activeIndex ? <BrainCircuit size={14} /> : <span className="status-dot" />}
                  <span>{node.replaceAll("_", " ")}</span>
                </div>
              );
            })}
          </div>
          {result.abstain_reason ? (
            <InlineNotice tone="warn" title="Abstained" body={result.abstain_reason} />
          ) : result.report_id ? (
            <InlineNotice tone="info" title="Fixed report created" body={`Report ${result.report_id} is bound to research run ${result.research_run_id}.`} />
          ) : null}
          <div className="agent-run-footer"><ShieldAlert size={14} /> Correlation {result.correlation_id}</div>
        </>
      ) : <p className="muted">No Agent run selected.</p>}
    </Panel>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric-card"><div className="eyebrow">{label}</div><div className="metric-card__value">{value}</div></div>;
}
