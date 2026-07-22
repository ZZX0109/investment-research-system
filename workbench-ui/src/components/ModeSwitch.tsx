import type { WorkbenchMode } from "../api/types";
import { useI18n } from "../i18n";

interface ModeSwitchProps {
  mode: WorkbenchMode;
  onChange(mode: WorkbenchMode): void;
}

export function ModeSwitch({ mode, onChange }: ModeSwitchProps) {
  const { t } = useI18n();
  const labels: Record<WorkbenchMode, string> = {
    demo: t("mode.demo"),
    sandbox: t("mode.sandbox"),
    research: t("mode.research"),
    real: t("mode.real")
  };

  return (
    <div className="mode-switch" role="tablist" aria-label={t("header.context")}>
      {(["research", "demo", "sandbox", "real"] as WorkbenchMode[]).map((entry) => (
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
