import type { TestOfficerManifest } from "../../../api/types";
import { toneForRunStatus, type TestOfficerSummary } from "../model";
import { Metric } from "./primitives";

interface TestOfficerRunSummaryProps {
  manifest: TestOfficerManifest;
  summary?: TestOfficerSummary;
}

export function TestOfficerRunSummary({ manifest, summary }: TestOfficerRunSummaryProps) {
  return (
    <article className="story-card story-card--focused">
      <div className="story-card__header">
        <strong>{manifest.mission.name}</strong>
        <span className={`tag tag--${toneForRunStatus(manifest.run.reviewStatus)}`}>
          {manifest.run.reviewStatus}
        </span>
      </div>
      <p className="muted">{manifest.mission.objective}</p>
      <div className="metric-strip">
        <Metric label="Scenarios" value={String(manifest.scenarios.length)} />
        <Metric label="Steps" value={`${summary?.failingSteps ?? 0}/${summary?.stepCount ?? 0} failing`} />
        <Metric label="Evidence" value={String(manifest.evidence.length)} />
        <Metric label="Findings" value={String(summary?.findingCount ?? 0)} tone={toneForRunStatus(manifest.run.status)} />
      </div>
    </article>
  );
}
