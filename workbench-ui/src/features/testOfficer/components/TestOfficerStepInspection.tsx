import { prioritizeArtifacts, toneForRunStatus, type TestOfficerStepInspection as TestOfficerStepInspectionModel, type TestOfficerTimelineSelectionDetail } from "../model";
import type { TestOfficerUiState } from "../useTestOfficerWorkspace";
import { ArtifactPreview, Detail } from "./primitives";

interface TestOfficerStepInspectionProps {
  inspection?: TestOfficerStepInspectionModel;
  timelineDetail?: TestOfficerTimelineSelectionDetail;
  selectedCheckId: TestOfficerUiState["selectedCheckId"];
  setSelectedCheckId: TestOfficerUiState["setSelectedCheckId"];
  selectedTimelineNodeKey: TestOfficerUiState["selectedTimelineNodeKey"];
  selectTimelineNode: (nodeKey: string, relatedStepId?: string) => void;
  selectedArtifactId: TestOfficerUiState["selectedArtifactId"];
  setSelectedArtifactId: TestOfficerUiState["setSelectedArtifactId"];
}

export function TestOfficerStepInspection({
  inspection,
  timelineDetail,
  selectedCheckId,
  setSelectedCheckId,
  selectedTimelineNodeKey,
  selectTimelineNode,
  selectedArtifactId,
  setSelectedArtifactId
}: TestOfficerStepInspectionProps) {
  if (!inspection) {
    return null;
  }

  return (
            <article className="story-card">
              <div className="story-card__header">
                <strong>{inspection.step.title}</strong>
                <span className={`tag tag--${toneForRunStatus(inspection.step.status)}`}>{inspection.durationLabel}</span>
              </div>
              <div className="test-officer-detail-grid">
                <div>
                  {timelineDetail ? (
                    <div className="notice-card">
                      <strong>{timelineDetail.phase}</strong>
                      <p>{timelineDetail.summary}</p>
                      <dl className="detail-list">
                        {timelineDetail.details.map((detail) => (
                          <Detail
                            key={`${timelineDetail.phase}-${detail.label}`}
                            label={detail.label}
                            value={detail.value}
                            mono={detail.mono}
                          />
                        ))}
                      </dl>
                      {timelineDetail.checkResults.length ? (
                        <div>
                          <strong>Checks</strong>
                          <ul className="flat-list">
                            {timelineDetail.checkResults.map((check) => (
                              <li key={check.checkId}>
                                <button
                                  className={`ghost-button ${selectedCheckId === check.checkId ? "ghost-button--active" : ""}`}
                                  type="button"
                                  onClick={() =>
                                    setSelectedCheckId((current) => current === check.checkId ? null : check.checkId)
                                  }
                                >
                                  {check.name}
                                </button>
                                {" "}· {check.result} · {check.kind}
                                {check.requiredEvidence.length ? ` [${check.requiredEvidence.join(", ")}]` : ""}
                                {check.summary ? ` · ${check.summary}` : ""}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {timelineDetail.linkedEvidence.length ? (
                        <div>
                          <strong>Linked Evidence</strong>
                          <ul className="flat-list">
                            {timelineDetail.linkedEvidence.map((evidence) => (
                              <li key={evidence.id}>
                                <button
                                  className={`ghost-button ${selectedTimelineNodeKey === `evidence:${evidence.id}` ? "ghost-button--active" : ""}`}
                                  type="button"
                                  onClick={() => selectTimelineNode(`evidence:${evidence.id}`, evidence.stepId)}
                                >
                                  {evidence.id}
                                </button>
                                {" "}· {evidence.kind} · {evidence.summary}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {timelineDetail.artifacts.length ? (
                        <div className="test-officer-grid">
                          {prioritizeArtifacts(timelineDetail.artifacts, selectedArtifactId).map((artifact) => (
                            <ArtifactPreview
                              artifact={artifact}
                              key={`timeline-${artifact.id}`}
                              onSelect={setSelectedArtifactId}
                              selected={selectedArtifactId === artifact.id}
                            />
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  <p>{inspection.step.intent}</p>
                  <dl className="detail-list">
                    <Detail label="Scenario" value={inspection.scenario?.name ?? inspection.step.scenarioId} />
                    <Detail label="Plan Status" value={inspection.planRecord?.status ?? "n/a"} />
                    <Detail label="Action" value={inspection.step.action} />
                    <Detail label="Selector" value={inspection.step.selectorRef ?? "n/a"} mono />
                    <Detail label="Expected" value={inspection.step.expectedOutcome ?? "n/a"} />
                  </dl>
                  {inspection.planRecord?.rationale ? (
                    <p className="muted">{inspection.planRecord.rationale}</p>
                  ) : null}
                  {inspection.scenarioContract ? (
                    <div className="notice-card">
                      <strong>Scenario Contract</strong>
                      <p className="muted">{inspection.scenarioContract.goal}</p>
                      <dl className="detail-list">
                        <Detail
                          label="Evidence"
                          value={inspection.scenarioContract.evidenceRequirements.join(" · ") || "n/a"}
                        />
                        <Detail
                          label="Failure Class"
                          value={inspection.scenarioContract.failureClasses.join(" · ") || "n/a"}
                        />
                        <Detail
                          label="Target Page"
                          value={inspection.scenarioContract.targetPageId}
                          mono
                        />
                      </dl>
                    </div>
                  ) : null}
                  {inspection.selectorContract ? (
                    <div className="notice-card">
                      <strong>Selector Contract</strong>
                      <dl className="detail-list">
                        <Detail label="Selector ID" value={inspection.selectorContract.id} mono />
                        <Detail label="Map" value={inspection.selectorContract.mapId} mono />
                        <Detail
                          label="Priority"
                          value={inspection.selectorContract.preferredStrategies.join(" → ")}
                        />
                      </dl>
                      {inspection.selectorContract.description ? (
                        <p className="muted">{inspection.selectorContract.description}</p>
                      ) : null}
                      <ul className="flat-list">
                        {inspection.selectorContract.queries.map((query) => (
                          <li key={query}>
                            <span className="mono">{query}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {inspection.fixtureContracts.length ? (
                    <div className="notice-card">
                      <strong>Fixture Baseline</strong>
                      <ul className="flat-list">
                        {inspection.fixtureContracts.map((fixture) => (
                          <li key={fixture.id}>
                            <span className="mono">{fixture.id}</span> · {fixture.kind} · {fixture.manifestRef}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
                <div>
                  <div className="story-card__header">
                    <strong>Evidence IDs</strong>
                    <span className="tag">{inspection.evidence.length}</span>
                  </div>
                  <ul className="flat-list">
                    {inspection.evidence.map((evidence) => (
                      <li key={evidence.id}>
                        <span className="mono">{evidence.id}</span> · {evidence.summary}
                      </li>
                    ))}
                  </ul>
                  {inspection.findings.map((finding) => (
                    <div className="test-officer-finding" key={finding.id}>
                      <strong>{finding.title}</strong>
                      <p className="muted">{finding.summary}</p>
                    </div>
                  ))}
                  {inspection.oracleEvaluations.map((evaluation) => (
                    <div className="test-officer-finding" key={evaluation.id}>
                      <strong>{evaluation.oracleId} · {evaluation.result}</strong>
                      <p className="muted">{evaluation.summary}</p>
                    </div>
                  ))}
                  {inspection.oracleContracts.length ? (
                    <div className="notice-card">
                      <strong>Oracle Contract</strong>
                      <ul className="flat-list">
                        {inspection.oracleContracts.map((oracle) => (
                          <li key={oracle.id}>
                            <strong>{oracle.name}</strong> · {oracle.passPolicy}
                            {oracle.checks.map((check) => (
                              <span key={check.id}>
                                {" "}· {check.name} ({check.kind}) [{check.requiredEvidence.join(", ")}]
                              </span>
                            ))}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              </div>
              {inspection.artifacts.length > 0 ? (
                <div className="test-officer-grid">
                  {prioritizeArtifacts(inspection.artifacts, selectedArtifactId).map((artifact) => (
                    <ArtifactPreview
                      artifact={artifact}
                      key={artifact.id}
                      onSelect={setSelectedArtifactId}
                      selected={selectedArtifactId === artifact.id}
                    />
                  ))}
                </div>
              ) : null}
            </article>
  );
}
