import React from "react";
import type { ResearchPayload } from "./types";

interface EvidenceGraphPanelProps {
  research: ResearchPayload;
}

export default function EvidenceGraphPanel({ research }: EvidenceGraphPanelProps) {
  const evidenceById = new Map(research.evidence.map((item) => [item.id, item]));
  return (
    <div className="evidence-graph">
      <div className="graph-summary">
        <strong>{research.evidenceGraph.summary}</strong>
        <span>{research.evidenceGraph.edges.length} 条边</span>
      </div>
      <div className="claim-grid">
        {research.evidenceGraph.claims.map((claim) => (
          <article className={`claim-card ${claim.status}`} key={claim.id}>
            <div className="claim-card-head">
              <strong>{claim.title}</strong>
              <span className={`status-badge ${claim.status === "supported" ? "fresh" : claim.status === "contested" ? "inferred" : "expired"}`}>
                {claim.status}
              </span>
            </div>
            <p>{claim.claim}</p>
            <small>{claim.judgeNote}</small>
            <div className="edge-list">
              <span>支持: {claim.supportingEvidenceIds.map((id) => evidenceById.get(id)?.sourceName ?? id).join("、") || "无"}</span>
              <span>反驳: {claim.rebuttingEvidenceIds.map((id) => evidenceById.get(id)?.sourceName ?? id).join("、") || "无"}</span>
              <span>计算: {claim.derivedMetrics.join("、") || "无"}</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
