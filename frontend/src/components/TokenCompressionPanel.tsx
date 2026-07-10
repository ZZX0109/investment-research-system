import React from "react";
import { BarChart3 } from "lucide-react";
import type { ResearchPayload } from "./types";
import { ratioPercent } from "./utils";

interface TokenCompressionPanelProps {
  research: ResearchPayload;
}

export default function TokenCompressionPanel({ research }: TokenCompressionPanelProps) {
  const report = research.tokenCompressionReport;
  return (
    <div className="token-compression-grid">
      <article className="document-block">
        <h3>
          <BarChart3 size={18} />
          压缩摘要
        </h3>
        <p>{report?.summary ?? "尚未生成 token 压缩报告。"}</p>
        <div className="ml-status-row">
          <span>raw: {report?.rawTokenEstimate ?? 0}</span>
          <span>structured: {report?.structuredTokenEstimate ?? 0}</span>
          <span>reduction: {report?.tokenReductionPercent ?? 0}%</span>
          <span>consistency: {ratioPercent(report?.conclusionConsistency)}</span>
        </div>
      </article>
      <div className="metric-table ml-metric-table">
        {Object.entries(report?.rawBreakdown ?? {}).map(([key, value]) => (
          <div key={key}>
            <span>{key}</span>
            <strong>{value}</strong>
            <small>raw tokens</small>
          </div>
        ))}
      </div>
      <article className="document-block">
        <h3>一致性检查</h3>
        <ul className="compact-list">
          {(report?.consistencyChecks ?? []).map((check) => (
            <li key={check.name}>
              <strong>{check.passed ? "pass" : "fail"}</strong>: {check.detail}
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}
