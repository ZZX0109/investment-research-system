import { LockKeyhole, Sparkles } from "lucide-react";
import { StatusBadge } from "./StatusBadge";
import { useI18n } from "../i18n";

export function ResearchHero({ status, asOf, decisionContext }: {
  status: string;
  asOf?: string | null;
  decisionContext?: string | null;
}) {
  const { t, formatDateTime } = useI18n();
  return (
    <section className="research-hero">
      <div className="research-hero__glow" aria-hidden="true" />
      <div className="research-hero__main">
        <div className="research-hero__eyebrow"><Sparkles size={14} /> {t("hero.eyebrow")} · {decisionContext === "pre_open" ? t("hero.preOpen") : t("hero.close")}</div>
        <h3>{t("hero.title")}</h3>
        <p>{t("hero.body")}</p>
      </div>
      <div className="research-hero__meta">
        <StatusBadge status={status} />
        <span className="research-hero__asof"><LockKeyhole size={14} /> {t("hero.asOf")} {formatDateTime(asOf)}</span>
      </div>
    </section>
  );
}
