import { useEffect, useState } from "react";
import type {
  TestOfficerCredentialKind,
  TestOfficerOnboardingDraft,
  TestOfficerRuntimeConfig
} from "../../api/types";
import {
  useCreateTestOfficerRunMutation,
  usePreviewTestOfficerMissionMutation,
  useTestOfficerAuditRunDetailQuery,
  useTestOfficerAuditRunsQuery,
  useTestOfficerComparisonQuery,
  useTestOfficerCredentialsQuery,
  useTestOfficerFixturesQuery,
  useTestOfficerHistoryQuery,
  useTestOfficerManifestQuery,
  useTestOfficerMissionPackageQuery,
  useTestOfficerOnboardingProtocolQuery,
  useTestOfficerOraclesQuery,
  useTestOfficerRegistryManifestQuery,
  useTestOfficerScenariosQuery,
  useTestOfficerSelectorMapsQuery,
  useUpsertTestOfficerCredentialMutation
} from "../../hooks/useWorkbenchQueries";

export function useTestOfficerData() {
  const manifestQuery = useTestOfficerManifestQuery();
  const manifest = manifestQuery.data;

  return {
    manifest,
    manifestQuery,
    createRunMutation: useCreateTestOfficerRunMutation(),
    missionPreviewMutation: usePreviewTestOfficerMissionMutation(),
    historyQuery: useTestOfficerHistoryQuery(manifest?.mission.id ?? null),
    comparisonQuery: useTestOfficerComparisonQuery(manifest?.run.id ?? null),
    registryManifestQuery: useTestOfficerRegistryManifestQuery(manifest?.run.id ?? null),
    onboardingProtocolQuery: useTestOfficerOnboardingProtocolQuery(manifest?.run.id ?? null),
    missionPackageQuery: useTestOfficerMissionPackageQuery(manifest?.run.id ?? null),
    selectorMapsQuery: useTestOfficerSelectorMapsQuery(manifest?.run.id ?? null),
    fixturesQuery: useTestOfficerFixturesQuery(manifest?.run.id ?? null),
    scenariosQuery: useTestOfficerScenariosQuery(manifest?.run.id ?? null),
    oraclesQuery: useTestOfficerOraclesQuery(manifest?.run.id ?? null),
    auditRunsQuery: useTestOfficerAuditRunsQuery(),
    auditRunDetailQuery: useTestOfficerAuditRunDetailQuery(manifest?.run.id ?? null),
    credentialsQuery: useTestOfficerCredentialsQuery(),
    upsertCredentialMutation: useUpsertTestOfficerCredentialMutation()
  };
}

export function useTestOfficerUiState(runId?: string) {
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selectedTimelineNodeKey, setSelectedTimelineNodeKey] = useState<string | null>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [selectedCheckId, setSelectedCheckId] = useState<string | null>(null);
  const [draftOverrides, setDraftOverrides] = useState<Partial<TestOfficerOnboardingDraft>>({});
  const [selectedExecutor, setSelectedExecutor] = useState<"memory" | "playwright">("memory");
  const [headless, setHeadless] = useState(true);
  const [traceEnabled, setTraceEnabled] = useState(false);
  const [videoEnabled, setVideoEnabled] = useState(false);
  const [credentialDraft, setCredentialDraft] = useState({
    id: "openai-default",
    label: "Default LLM judge key",
    kind: "api-key" as TestOfficerCredentialKind,
    secret: "",
    provider: "openai"
  });

  useEffect(() => {
    setSelectedStepId(null);
    setSelectedTimelineNodeKey(null);
    setSelectedArtifactId(null);
    setSelectedCheckId(null);
    setDraftOverrides({});
    setSelectedExecutor("memory");
    setHeadless(true);
    setTraceEnabled(false);
    setVideoEnabled(false);
  }, [runId]);

  return {
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
  };
}

export type { TestOfficerRuntimeConfig };

export type TestOfficerDataState = ReturnType<typeof useTestOfficerData>;
export type TestOfficerUiState = ReturnType<typeof useTestOfficerUiState>;
