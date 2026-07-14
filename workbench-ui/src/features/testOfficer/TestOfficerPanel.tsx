import { useMemo } from "react";
import { Panel } from "../../components/Panel";
import {
  buildOnboardingPreview,
  clearTimelineDebugSelection,
  buildTimelineDebugContext,
  buildRunTimeline,
  buildTimelineSelectionDetail,
  buildStepInspection,
  buildTestOfficerSummary,
  createDefaultOnboardingDraft,
  sanitizeOnboardingDraftForRequest
} from "./model";
import { formatAuditArtifactSignalSummary, formatAuditSignalSummary } from "./formatters";
import { TestOfficerEvidenceVerdict } from "./components/TestOfficerEvidenceVerdict";
import { TestOfficerInputContext } from "./components/TestOfficerInputContext";
import { TestOfficerPlanExecution } from "./components/TestOfficerPlanExecution";
import { TestOfficerRecentRuns } from "./components/TestOfficerRecentRuns";
import { TestOfficerRunSummary } from "./components/TestOfficerRunSummary";
import { TestOfficerStepInspection } from "./components/TestOfficerStepInspection";
import { useTestOfficerData, useTestOfficerUiState, type TestOfficerRuntimeConfig } from "./useTestOfficerWorkspace";

export function TestOfficerPanel() {
  const {
    manifest,
    manifestQuery,
    createRunMutation,
    missionPreviewMutation,
    historyQuery,
    comparisonQuery,
    registryManifestQuery,
    onboardingProtocolQuery,
    missionPackageQuery,
    selectorMapsQuery,
    fixturesQuery,
    scenariosQuery,
    oraclesQuery,
    auditRunsQuery,
    auditRunDetailQuery,
    credentialsQuery,
    upsertCredentialMutation
  } = useTestOfficerData();
  const {
    selectedStepId,
    setSelectedStepId,
    selectedTimelineNodeKey,
    setSelectedTimelineNodeKey,
    selectedArtifactId,
    setSelectedArtifactId,
    selectedCheckId,
    setSelectedCheckId,
    draftOverrides,
    setDraftOverrides,
    selectedExecutor,
    setSelectedExecutor,
    headless,
    setHeadless,
    traceEnabled,
    setTraceEnabled,
    videoEnabled,
    setVideoEnabled,
    credentialDraft,
    setCredentialDraft
  } = useTestOfficerUiState(manifest?.run.id);

  const summary = useMemo(
    () =>
      manifest
        ? buildTestOfficerSummary(
            manifest,
            historyQuery.data,
            comparisonQuery.data,
            registryManifestQuery.data,
            onboardingProtocolQuery.data,
            missionPackageQuery.data
          )
        : undefined,
    [
      comparisonQuery.data,
      historyQuery.data,
      manifest,
      missionPackageQuery.data,
      onboardingProtocolQuery.data,
      registryManifestQuery.data
    ]
  );
  const inspection = useMemo(
    () =>
      manifest
        ? buildStepInspection(manifest, selectedStepId, {
            selectorMaps: selectorMapsQuery.data,
            fixtures: fixturesQuery.data,
            scenarios: scenariosQuery.data,
            oracles: oraclesQuery.data
          })
        : undefined,
    [
      fixturesQuery.data,
      manifest,
      oraclesQuery.data,
      scenariosQuery.data,
      selectedStepId,
      selectorMapsQuery.data
    ]
  );
  const timeline = useMemo(
    () =>
      manifest
        ? buildRunTimeline(manifest, {
            stepId: selectedStepId,
            nodeKey: selectedTimelineNodeKey,
            checkId: selectedCheckId
          })
        : undefined,
    [manifest, selectedCheckId, selectedStepId, selectedTimelineNodeKey]
  );
  const timelineDetail = useMemo(
    () => manifest ? buildTimelineSelectionDetail(manifest, timeline, selectedTimelineNodeKey, inspection, selectedCheckId) : undefined,
    [inspection, manifest, selectedCheckId, selectedTimelineNodeKey, timeline]
  );
  const debugContext = useMemo(
    () => buildTimelineDebugContext({
      selectedNodeKey: selectedTimelineNodeKey,
      selectedCheckId,
      selectedArtifactId
    }),
    [selectedArtifactId, selectedCheckId, selectedTimelineNodeKey]
  );
  const onboardingDraftBase = useMemo(() => createDefaultOnboardingDraft(manifest), [manifest]);
  const onboardingDraft = useMemo(
    () => ({
      ...onboardingDraftBase,
      ...draftOverrides,
      keyPages: draftOverrides.keyPages ?? onboardingDraftBase.keyPages,
      selectorHints: draftOverrides.selectorHints ?? onboardingDraftBase.selectorHints,
      scenarioRequests: draftOverrides.scenarioRequests ?? onboardingDraftBase.scenarioRequests
    }),
    [draftOverrides, onboardingDraftBase]
  );
  const onboardingPreview = useMemo(
    () => buildOnboardingPreview(onboardingDraft),
    [onboardingDraft]
  );
  const topAuditAttribution = auditRunDetailQuery.data?.failureAttributions[0];
  const topAuditSignals = formatAuditSignalSummary(topAuditAttribution?.signals);
  const topAuditArtifactSignals = formatAuditArtifactSignalSummary(auditRunDetailQuery.data?.artifacts ?? []);
  const latestAuditGate = auditRunDetailQuery.data?.gateResults[0];
  const requestDraft = useMemo(
    () => sanitizeOnboardingDraftForRequest(onboardingDraft),
    [onboardingDraft]
  );
  const platformPreview = missionPreviewMutation.data;

  function updateRuntimeDraft(nextRuntime: TestOfficerRuntimeConfig) {
    setDraftOverrides((current) => ({
      ...current,
      runtime: {
        ...(onboardingDraft.runtime ?? {}),
        ...nextRuntime
      }
    }));
  }

  function selectTimelineNode(nodeKey: string, relatedStepId?: string) {
    setSelectedTimelineNodeKey(nodeKey);
    setSelectedCheckId(null);
    if (relatedStepId) {
      setSelectedStepId(relatedStepId);
    }
  }

  function clearDebugContext(tokenId: "node" | "check" | "artifact" | "all") {
    const nextSelection = clearTimelineDebugSelection({
      selectedNodeKey: selectedTimelineNodeKey,
      selectedCheckId,
      selectedArtifactId
    }, tokenId);
    setSelectedTimelineNodeKey(nextSelection.selectedNodeKey ?? null);
    setSelectedCheckId(nextSelection.selectedCheckId ?? null);
    setSelectedArtifactId(nextSelection.selectedArtifactId ?? null);
  }

  return (
    <Panel eyebrow="AI Test Officer" title="Evidence-Grounded Quality Gate">
      {manifestQuery.isLoading ? (
        <p className="muted">Loading quality gate bundle...</p>
      ) : manifestQuery.isError || !manifest ? (
        <p className="muted">No Test Officer run bundle is available.</p>
      ) : (
        <>
          <TestOfficerRunSummary manifest={manifest} summary={summary} />

          <div className="test-officer-run-layout">
            <TestOfficerInputContext
              manifest={manifest}
              onboardingDraft={onboardingDraft}
              onboardingPreview={onboardingPreview}
              requestDraft={requestDraft}
              selectedExecutor={selectedExecutor}
              setSelectedExecutor={setSelectedExecutor}
              headless={headless}
              setHeadless={setHeadless}
              traceEnabled={traceEnabled}
              setTraceEnabled={setTraceEnabled}
              videoEnabled={videoEnabled}
              setVideoEnabled={setVideoEnabled}
              setDraftOverrides={setDraftOverrides}
              updateRuntimeDraft={updateRuntimeDraft}
              summary={summary}
              missionPreviewMutation={missionPreviewMutation}
              createRunMutation={createRunMutation}
            />
            <TestOfficerPlanExecution
              manifest={manifest}
              summary={summary}
              debugContext={debugContext}
              timeline={timeline}
              selectTimelineNode={selectTimelineNode}
              clearDebugContext={clearDebugContext}
              onboardingProtocolQuery={onboardingProtocolQuery}
              missionPackageQuery={missionPackageQuery}
              registryManifestQuery={registryManifestQuery}
              platformPreview={platformPreview}
            />
            <TestOfficerEvidenceVerdict
              manifest={manifest}
              summary={summary}
              auditRunsQuery={auditRunsQuery}
              auditRunDetailQuery={auditRunDetailQuery}
              latestAuditGate={latestAuditGate}
              topAuditAttribution={topAuditAttribution}
              topAuditSignals={topAuditSignals}
              topAuditArtifactSignals={topAuditArtifactSignals}
              credentialsQuery={credentialsQuery}
              credentialDraft={credentialDraft}
              setCredentialDraft={setCredentialDraft}
              upsertCredentialMutation={upsertCredentialMutation}
              inspection={inspection}
            />
          </div>

          <TestOfficerStepInspection
            inspection={inspection}
            timelineDetail={timelineDetail}
            selectedCheckId={selectedCheckId}
            setSelectedCheckId={setSelectedCheckId}
            selectedTimelineNodeKey={selectedTimelineNodeKey}
            selectTimelineNode={selectTimelineNode}
            selectedArtifactId={selectedArtifactId}
            setSelectedArtifactId={setSelectedArtifactId}
          />

          <TestOfficerRecentRuns runs={historyQuery.data?.runs} />
        </>
      )}
    </Panel>
  );
}