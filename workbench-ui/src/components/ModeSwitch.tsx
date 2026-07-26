import type { WorkbenchMode } from "../api/types";
import { useI18n } from "../i18n";

interface ModeSwitchProps {
  mode: WorkbenchMode;
  onChange(mode: WorkbenchMode): void;
}

export function ModeSwitch({ mode, onChange }: ModeSwitchProps) {
  const { t } = useI18n();

  return (
    <div className="mode-switch" aria-label={t("header.context")}>
      <button
        data-testid="mode-switch-research"
        className={`mode-switch__button mode-switch__button--primary ${mode === "research" ? "mode-switch__button--active" : ""}`}
        type="button"
        onClick={() => onChange("research")}
      >
        {t("mode.research")}
      </button>
    </div>
  );
}
