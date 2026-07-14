import { afterEach, describe, expect, it } from "vitest";
import { useAuthSessionStore } from "../workbench-ui/src/state/authSessionStore";
import { useWorkbenchStore } from "../workbench-ui/src/state/workbenchStore";

function resetAuthSessionState() {
  useAuthSessionStore.getState().resetForm();
}

function resetWorkbenchState() {
  useWorkbenchStore.setState({
    mode: "demo",
    selectedAssetId: null,
    selectedRunId: null,
    selectedEvidenceId: null,
    onlySelectedRunResearch: false,
    assetSearch: ""
  });
}

describe("auth session store", () => {
  afterEach(() => {
    resetAuthSessionState();
    resetWorkbenchState();
  });

  it("switches form mode and clears stale auth errors", () => {
    useAuthSessionStore.getState().setLastError("Invalid credentials");
    useAuthSessionStore.getState().setFormMode("register");

    expect(useAuthSessionStore.getState().formMode).toBe("register");
    expect(useAuthSessionStore.getState().lastError).toBeNull();
  });

  it("never seeds credentials into the real login form", () => {
    useAuthSessionStore.getState().setEmail("investor@example.com");
    useAuthSessionStore.getState().setPassword("temporary-secret");

    useAuthSessionStore.getState().resetForm();

    expect(useAuthSessionStore.getState().email).toBe("");
    expect(useAuthSessionStore.getState().displayName).toBe("");
    expect(useAuthSessionStore.getState().password).toBe("");
  });

  it("resets the workspace selection in one step", () => {
    useWorkbenchStore.getState().setSelectedAssetId("asset-1");
    useWorkbenchStore.getState().focusRunWorkspace("run-1");
    useWorkbenchStore.getState().setSelectedEvidenceId("evidence-1");
    useWorkbenchStore.getState().setAssetSearch("NVDA");

    useWorkbenchStore.getState().resetWorkspace();

    expect(useWorkbenchStore.getState().selectedAssetId).toBeNull();
    expect(useWorkbenchStore.getState().selectedRunId).toBeNull();
    expect(useWorkbenchStore.getState().selectedEvidenceId).toBeNull();
    expect(useWorkbenchStore.getState().onlySelectedRunResearch).toBe(false);
    expect(useWorkbenchStore.getState().assetSearch).toBe("");
  });
});
