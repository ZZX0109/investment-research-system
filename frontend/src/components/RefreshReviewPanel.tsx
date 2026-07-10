import React, { useState } from "react";
import { RefreshCw } from "lucide-react";
import { fetchJson } from "./fetchJson";
import type { RefreshReviewPayload } from "./types";

interface RefreshReviewPanelProps {
  review?: RefreshReviewPayload | null;
  symbols?: string[];
  token?: string | null;
}

export default function RefreshReviewPanel({ review = null, symbols = [], token = null }: RefreshReviewPanelProps) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RefreshReviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const displayed = review ?? result;

  async function refresh() {
    if (!token) return;
    setRunning(true);
    setError(null);
    try {
      const payload = await fetchJson<RefreshReviewPayload>("/api/refresh-reviews", token, {
        method: "POST",
        body: JSON.stringify({ symbols })
      });
      setResult(payload);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="refresh-review-panel">
      <div className="panel-head">
        <h2>全面刷新报告评审</h2>
        <button className="primary-button" disabled={running} onClick={refresh} type="button">
          <RefreshCw size={16} />
          {running ? "正在刷新..." : "刷新评审"}
        </button>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      {displayed ? (
        <div className="refresh-results">
          <p>{displayed.summary}</p>
          <div className="metric-table">
            {displayed.items.map((item) => (
              <div key={item.symbol}>
                <span>{item.symbol}</span>
                <strong>{item.beforeScore} → {item.afterScore} (Δ{item.riskScoreDelta})</strong>
                <small>
                  新增证据 {item.evidenceChanges.newEvidenceIds.length} · 归档 {item.evidenceChanges.archivedCount}
                </small>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
