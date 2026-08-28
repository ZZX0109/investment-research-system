import { create } from "zustand";
import type { WorkbenchMode } from "../api/types";

const RESEARCH_SCOPE_STORAGE_KEY = "investment-research.research-scope.v1";

function readResearchAssetIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RESEARCH_SCOPE_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === "string") : [];
  } catch {
    return [];
  }
}

function persistResearchAssetIds(ids: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(RESEARCH_SCOPE_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // A private browsing context may deny storage. The in-memory scope still works.
  }
}

function initialMode(): WorkbenchMode {
  // This workbench has one user-facing product: the A-share research view.
  // Legacy URLs may still contain ?mode=real/demo/sandbox, but must not turn
  // a visitor's interface into a misleading "formal" or seeded workspace.
  return "research";
}

interface WorkbenchState {
  mode: WorkbenchMode;
  /** IDs explicitly added to this browser's research workspace. */
  researchAssetIds: string[];
  selectedAssetId: string | null;
  selectedRunId: string | null;
  selectedEvidenceId: string | null;
  onlySelectedRunResearch: boolean;
  assetSearch: string;
  setMode(mode: WorkbenchMode): void;
  addResearchAsset(assetId: string): void;
  removeResearchAssets(assetIds: string[]): void;
  setResearchAssetIds(assetIds: string[]): void;
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
  researchAssetIds: readResearchAssetIds(),
  selectedAssetId: null,
  selectedRunId: null,
  selectedEvidenceId: null,
  onlySelectedRunResearch: false,
  assetSearch: "",
  setMode: (mode) => set({ mode }),
  addResearchAsset: (assetId) => set((state) => {
    if (state.researchAssetIds.includes(assetId)) return state;
    const researchAssetIds = [...state.researchAssetIds, assetId];
    persistResearchAssetIds(researchAssetIds);
    return { researchAssetIds };
  }),
  removeResearchAssets: (assetIds) => set((state) => {
    const removed = new Set(assetIds);
    const researchAssetIds = state.researchAssetIds.filter((id) => !removed.has(id));
    persistResearchAssetIds(researchAssetIds);
    return { researchAssetIds };
  }),
  setResearchAssetIds: (assetIds) => set(() => {
    const researchAssetIds = [...new Set(assetIds)];
    persistResearchAssetIds(researchAssetIds);
    return { researchAssetIds };
  }),
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
