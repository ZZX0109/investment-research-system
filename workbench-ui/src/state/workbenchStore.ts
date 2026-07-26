import { create } from "zustand";
import type { WorkbenchMode } from "../api/types";

function initialMode(): WorkbenchMode {
  if (typeof window === "undefined") return "research";
  const requested = new URLSearchParams(window.location.search).get("mode");
  return requested === "demo" || requested === "sandbox" || requested === "real" ? requested : "research";
}

interface WorkbenchState {
  mode: WorkbenchMode;
  selectedAssetId: string | null;
  selectedRunId: string | null;
  selectedEvidenceId: string | null;
  onlySelectedRunResearch: boolean;
  assetSearch: string;
  setMode(mode: WorkbenchMode): void;
  setSelectedAssetId(assetId: string | null): void;
  setSelectedRunId(runId: string | null): void;
  focusRunWorkspace(runId: string | null): void;
  setSelectedEvidenceId(evidenceId: string | null): void;
  setOnlySelectedRunResearch(value: boolean): void;
  setAssetSearch(value: string): void;
  resetWorkspace(): void;
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  mode: initialMode(),
  selectedAssetId: null,
  selectedRunId: null,
  selectedEvidenceId: null,
  onlySelectedRunResearch: false,
  assetSearch: "",
  setMode: (mode) => set({ mode }),
  setSelectedAssetId: (selectedAssetId) =>
    set({ selectedAssetId, selectedRunId: null, selectedEvidenceId: null, onlySelectedRunResearch: false }),
  setSelectedRunId: (selectedRunId) => set({ selectedRunId, selectedEvidenceId: null }),
  focusRunWorkspace: (selectedRunId) =>
    set({ selectedRunId, selectedEvidenceId: null, onlySelectedRunResearch: selectedRunId !== null }),
  setSelectedEvidenceId: (selectedEvidenceId) => set({ selectedEvidenceId }),
  setOnlySelectedRunResearch: (onlySelectedRunResearch) => set({ onlySelectedRunResearch }),
  setAssetSearch: (assetSearch) => set({ assetSearch }),
  resetWorkspace: () =>
    set({
      selectedAssetId: null,
      selectedRunId: null,
      selectedEvidenceId: null,
      onlySelectedRunResearch: false,
      assetSearch: ""
    })
}));
