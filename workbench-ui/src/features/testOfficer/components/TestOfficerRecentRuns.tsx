import type { TestOfficerHistoryEntry } from "../../../api/types";

interface TestOfficerRecentRunsProps {
  runs?: TestOfficerHistoryEntry[];
}

export function TestOfficerRecentRuns({ runs }: TestOfficerRecentRunsProps) {
  if (!runs?.length) {
    return null;
  }

  return (
    <article className="story-card">
      <div className="story-card__header">
        <strong>Recent Runs</strong>
        <span className="tag">{runs.length}</span>
      </div>
      <ul className="flat-list">
        {runs.slice(0, 4).map((run) => (
          <li key={run.runId}>
            <span className="mono">{run.runId}</span> · {run.status} · {run.findingCount} findings
          </li>
        ))}
      </ul>
    </article>
  );
}
