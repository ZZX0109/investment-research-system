import React from "react";
import type { ResearchPayload } from "./types";

interface ToolCallPanelProps {
  research: ResearchPayload;
}

export default function ToolCallPanel({ research }: ToolCallPanelProps) {
  return (
    <div className="tool-call-grid">
      {research.toolCalls.map((call) => (
        <article className={`tool-call ${call.status}`} key={call.id}>
          <div className="tool-call-head">
            <div>
              <strong>{call.name}</strong>
              <small>{call.toolId} · {call.category}</small>
            </div>
            <span className={`status-badge ${call.status === "success" ? "fresh" : call.status === "degraded" ? "inferred" : "expired"}`}>
              {call.status}
            </span>
          </div>
          <p>{call.outputSummary}</p>
          <div className="tool-call-meta">
            <span>source: {call.sourceName}</span>
            <span>freshness: {call.freshnessRule}</span>
            <span>evidence: {call.evidenceId ?? "none"}</span>
          </div>
          {call.failureReason ? <p className="tool-failure">{call.failureReason}</p> : null}
        </article>
      ))}
    </div>
  );
}
