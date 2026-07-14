import type { WorkbenchMode } from "../api/types";

interface ModeSwitchProps {
  mode: WorkbenchMode;
  onChange(mode: WorkbenchMode): void;
}

export function ModeSwitch({ mode, onChange }: ModeSwitchProps) {
  const labels: Record<WorkbenchMode, string> = {
    demo: "Demo Mode",
    sandbox: "Sandbox Mode",
    real: "Real Data Mode"
  };

  return (
    <div className="mode-switch" role="tablist" aria-label="Workbench mode">
      {(["demo", "sandbox", "real"] as WorkbenchMode[]).map((entry) => (
        <button
          key={entry}
          data-testid={`mode-switch-${entry}`}
          className={`mode-switch__button ${mode === entry ? "mode-switch__button--active" : ""}`}
          type="button"
          onClick={() => onChange(entry)}
        >
          {labels[entry]}
        </button>
      ))}
    </div>
  );
}
