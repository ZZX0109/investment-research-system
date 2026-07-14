import { useState } from "react";
import { Panel } from "../../components/Panel";
import { useCreateAssetMutation } from "../../hooks/useWorkbenchQueries";
import { useWorkbenchStore } from "../../state/workbenchStore";

export function AssetComposer() {
  const mode = useWorkbenchStore((state) => state.mode);
  const setSelectedAssetId = useWorkbenchStore((state) => state.setSelectedAssetId);
  const mutation = useCreateAssetMutation();
  const [ticker, setTicker] = useState("AMD");
  const [name, setName] = useState("Advanced Micro Devices");
  const modePayload = {
    demo: {
      data_mode: "demo",
      source_type: "synthetic",
      source_name: "demo-ui"
    },
    sandbox: {
      data_mode: "sandbox",
      source_type: "synthetic",
      source_name: "sandbox-ui"
    },
    real: {
      data_mode: "real",
      source_type: "manual_override",
      source_name: "frontend-intake"
    }
  } as const;

  return (
    <Panel eyebrow="Intake" title="Add Asset">
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          void mutation
            .mutateAsync({
              ticker,
              name,
              asset_type: "equity",
              currency: "USD",
              exchange: "NASDAQ",
              ...modePayload[mode],
              observed_at: new Date().toISOString(),
              confidence: 0.95
            })
            .then((asset) => {
              setSelectedAssetId(asset.id);
            });
        }}
      >
        <label>
          <span>Ticker</span>
          <input value={ticker} onChange={(event) => setTicker(event.target.value)} />
        </label>
        <label>
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <button className="primary-button" type="submit">
          {mutation.isPending ? "Saving..." : "Create Asset"}
        </button>
        {mode === "demo" ? <p className="muted">Demo mode reuses the seeded asset to keep the story stable.</p> : null}
        {mode === "sandbox" ? (
          <p className="muted">Sandbox mode keeps inputs synthetic so we can test workflows without pretending they are real-market records.</p>
        ) : null}
        {mutation.error instanceof Error ? <p className="muted">{mutation.error.message}</p> : null}
      </form>
    </Panel>
  );
}
