import React from "react";
import { FileSearch } from "lucide-react";
import type { ResearchPayload } from "./types";
import { formatDateTime } from "./utils";

interface DocumentAnalysisPanelProps {
  research: ResearchPayload;
}

export default function DocumentAnalysisPanel({ research }: DocumentAnalysisPanelProps) {
  return (
    <div className="document-analysis">
      <article className="document-summary">
        <h3>
          <FileSearch size={18} />
          {research.documentAnalysis.filename}
        </h3>
        <p>{research.documentAnalysis.summary}</p>
        <small>{formatDateTime(research.documentAnalysis.uploadedAt)} · {research.documentAnalysis.sourceType}</small>
      </article>
      <div className="block-grid">
        {research.documentAnalysis.blocks.map((block) => (
          <article className="block-card" key={block.type}>
            <strong>{block.count}</strong>
            <span>{block.label}</span>
            <small>{block.status}</small>
          </article>
        ))}
      </div>
      <div className="metric-table">
        {research.documentAnalysis.metrics.map((metric) => (
          <div key={`${metric.metric_name}-${metric.source_block}`}>
            <span>{metric.metric_name}</span>
            <strong>{metric.metric_value}</strong>
            <small>{metric.period} · {metric.source_block}</small>
          </div>
        ))}
      </div>
      <p className="chart-summary">{research.documentAnalysis.chartSummary}</p>
      <div className="block-preview-list">
        {research.documentAnalysis.blockPreviews.slice(0, 6).map((block) => (
          <article className="block-preview" key={`${block.locator}-${block.label}`}>
            <strong>{block.label}</strong>
            <span>{block.block_type} · {block.locator}</span>
            <p>{block.content_preview}</p>
          </article>
        ))}
      </div>
    </div>
  );
}
