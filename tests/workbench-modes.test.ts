import { describe, expect, it } from "vitest";
import { createWorkbenchClient, resolveWorkbenchDataSource } from "../workbench-ui/src/api/client";
import { getSandboxBundle, getSandboxSession } from "../workbench-ui/src/api/demoData";

describe("workbench modes", () => {
  it("exposes a dedicated sandbox seed with explicit synthetic provenance", () => {
    const session = getSandboxSession();
    const bundle = getSandboxBundle();

    expect(session.user.display_name).toBe("Sandbox Analyst");
    expect(session.user.provenance.data_mode).toBe("sandbox");
    expect(bundle.asset.ticker).toBe("AMD");
    expect(bundle.snapshot.data_modes).toEqual(["sandbox"]);
    expect(bundle.judge_scores[0]?.gating_reasons[0]).toContain("Sandbox mode");
  });

  it("routes sandbox mode through seeded data instead of real backend calls", async () => {
    const client = createWorkbenchClient("sandbox");
    const [session, assets, bundle] = await Promise.all([
      client.getSession(),
      client.getAssets(),
      client.triggerAnalysis("c2d1e17b-fb31-4f4f-b5fa-c72dbcf93001")
    ]);

    expect(client.mode).toBe("sandbox");
    expect(client.dataSource).toBe("seeded-sandbox");
    expect(session.user.provenance.data_mode).toBe("sandbox");
    expect(assets[0]?.provenance.data_mode).toBe("sandbox");
    expect(bundle.run.provenance.data_mode).toBe("sandbox");
  });

  it("resolves workbench data sources explicitly for each mode", () => {
    expect(resolveWorkbenchDataSource("demo")).toBe("seeded-demo");
    expect(resolveWorkbenchDataSource("sandbox")).toBe("seeded-sandbox");
    expect(resolveWorkbenchDataSource("research")).toBe("api");
    expect(resolveWorkbenchDataSource("real")).toBe("api");
  });
});
