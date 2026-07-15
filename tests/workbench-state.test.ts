import { afterEach, describe, expect, it } from "vitest";
import { useWorkbenchStore } from "../workbench-ui/src/state/workbenchStore";

function resetWorkbenchState() {
  useWorkbenchStore.setState({
    mode: "research",
    selectedAssetId: null,
    selectedRunId: null,
    selectedEvidenceId: null,
    onlySelectedRunResearch: false,
    assetSearch: ""
  });
}

describe("workbench store", () => {
  afterEach(() => {
    resetWorkbenchState();
  });

  it("uses the fail-closed A-share research workbench by default", () => {
    expect(useWorkbenchStore.getState().mode).toBe("research");
  });

  it("resets run-scoped research state when the asset changes", () => {
    useWorkbenchStore.getState().setSelectedAssetId("asset-1");
    useWorkbenchStore.getState().focusRunWorkspace("run-1");
    useWorkbenchStore.getState().setSelectedEvidenceId("evidence-1");

    useWorkbenchStore.getState().setSelectedAssetId("asset-2");

    expect(useWorkbenchStore.getState().selectedAssetId).toBe("asset-2");
    expect(useWorkbenchStore.getState().selectedRunId).toBeNull();
    expect(useWorkbenchStore.getState().selectedEvidenceId).toBeNull();
    expect(useWorkbenchStore.getState().onlySelectedRunResearch).toBe(false);
  });

  it("focuses the workspace on a single immutable run", () => {
    useWorkbenchStore.getState().setSelectedAssetId("asset-1");
    useWorkbenchStore.getState().setSelectedEvidenceId("evidence-1");

    useWorkbenchStore.getState().focusRunWorkspace("run-1");

    expect(useWorkbenchStore.getState().selectedRunId).toBe("run-1");
    expect(useWorkbenchStore.getState().selectedEvidenceId).toBeNull();
    expect(useWorkbenchStore.getState().onlySelectedRunResearch).toBe(true);
  });

  it("can clear run workspace focus without leaving stale evidence scope behind", () => {
    useWorkbenchStore.getState().focusRunWorkspace("run-1");
    useWorkbenchStore.getState().setSelectedEvidenceId("evidence-1");

    useWorkbenchStore.getState().focusRunWorkspace(null);

    expect(useWorkbenchStore.getState().selectedRunId).toBeNull();
    expect(useWorkbenchStore.getState().selectedEvidenceId).toBeNull();
    expect(useWorkbenchStore.getState().onlySelectedRunResearch).toBe(false);
  });
});
