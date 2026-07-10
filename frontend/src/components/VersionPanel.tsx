import React, { useState } from "react";
import { History } from "lucide-react";
import type { ResearchPayload } from "./types";
import SourceMetaBadge from "./SourceMetaBadge";
import { formatDateTime } from "./utils";
import { apiTextRequest } from "../lib/apiClient";

interface VersionPanelProps {
  research: ResearchPayload;
  token: string | null;
}

export default function VersionPanel({ research, token }: VersionPanelProps) {
  const [activeReport, setActiveReport] = useState<{ runId: string; markdown: string } | null>(null);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function openReport(run: { runId: string; reportPath?: string }) {
    if (!run.reportPath) {
      setError("该 run 没有关联报告快照。");
      return;
    }
    setLoadingRunId(run.runId);
    setError(null);
    try {
      const markdown = await apiTextRequest(run.reportPath, token);
      setActiveReport({ runId: run.runId, markdown });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingRunId(null);
    }
  }

  return (
    <div className="version-panel">
      <article className="document-block">
        <h3>
          <History size={18} />
          版本对比
        </h3>
        <p>{research.reportVersions.delta.summary}</p>
        <small>上次 {research.reportVersions.delta.previousRunId ?? "none"} · 风险 score delta: {research.reportVersions.delta.riskScoreDelta}</small>
      </article>
      <div className="metric-table">
        {research.reportVersions.recentRuns.slice(0, 5).map((run) => (
          <div key={run.runId}>
            <span>{formatDateTime(run.startedAt)}</span>
            <strong>{run.riskScore}</strong>
            <small>{run.summary}</small>
            {run.qualityGateStatus ? <small>Gate: {run.qualityGateStatus}</small> : null}
            <SourceMetaBadge meta={run.sourceMeta} compact />
            <button className="ghost-button" onClick={() => void openReport(run)} disabled={loadingRunId === run.runId} type="button">
              {loadingRunId === run.runId ? "读取中" : "回看报告"}
            </button>
          </div>
        ))}
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {activeReport ? (
        <article className="report-snapshot-viewer">
          <strong>Run {activeReport.runId} 固定报告快照</strong>
          <pre>{activeReport.markdown}</pre>
        </article>
      ) : null}
    </div>
  );
}
