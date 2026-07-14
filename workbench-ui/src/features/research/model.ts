import type { Evidence, ResearchReport } from "../../api/types";

export function buildFocusedEvidenceList(
  evidence: Evidence[],
  selectedEvidenceId?: string | null
) {
  if (!selectedEvidenceId) {
    return {
      focusedEvidence: undefined,
      orderedEvidence: evidence
    };
  }

  const focusedEvidence = evidence.find((entry) => entry.id === selectedEvidenceId);
  if (!focusedEvidence) {
    return {
      focusedEvidence: undefined,
      orderedEvidence: evidence
    };
  }

  return {
    focusedEvidence,
    orderedEvidence: [focusedEvidence, ...evidence.filter((entry) => entry.id !== selectedEvidenceId)]
  };
}

export function filterEvidenceForSelectedRun(
  evidence: Evidence[],
  selectedRunEvidenceIds?: string[] | null,
  onlySelectedRun?: boolean
) {
  if (!onlySelectedRun || !selectedRunEvidenceIds?.length) {
    return evidence;
  }

  const allowed = new Set(selectedRunEvidenceIds);
  return evidence.filter((entry) => allowed.has(entry.id));
}

export function filterReportsForSelectedRun(
  reports: ResearchReport[],
  selectedRunId?: string | null,
  selectedRunReportIds?: string[] | null,
  onlySelectedRun?: boolean
) {
  if (!onlySelectedRun || !selectedRunId) {
    return reports;
  }

  if (selectedRunReportIds?.length) {
    const allowed = new Set(selectedRunReportIds);
    return reports.filter((report) => allowed.has(report.id));
  }

  return reports.filter((report) => report.analysis_run_id === selectedRunId);
}
