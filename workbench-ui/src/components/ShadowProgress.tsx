import { StatusBadge } from "./StatusBadge";
import { useI18n } from "../i18n";

export function ShadowProgress({ sessionCount, validCount, abstainCount, completed, forwardStatus, primaryStatus }: {
  sessionCount: number;
  validCount: number;
  abstainCount: number;
  completed: Record<string, number>;
  forwardStatus: string;
  primaryStatus: string;
}) {
  const { t } = useI18n();
  return (
    <div className="shadow-progress">
      <div className="shadow-progress__header"><strong>{t("research.shadow")}</strong><StatusBadge status={validCount > 0 ? "partial" : "abstain"} /></div>
      <div className="shadow-progress__metrics">
        <span><b>{sessionCount}</b><small>{t("shadow.frozen")}</small></span>
        <span><b>{validCount}</b><small>{t("shadow.valid")}</small></span>
        <span><b>{abstainCount}</b><small>{t("shadow.abstain")}</small></span>
      </div>
      <div className="shadow-progress__milestones">
        {[1, 5, 20, 60].map((horizon) => <span key={horizon}><b>{completed[String(horizon)] ?? 0}</b><small>T+{horizon}</small></span>)}
      </div>
      <p className="muted">{t("shadow.forward")}: {forwardStatus} · {t("shadow.primary")}: {primaryStatus} · {t("shadow.threshold")}</p>
    </div>
  );
}
