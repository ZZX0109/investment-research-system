import type { ReactNode } from "react";

export function MetricCard({ label, value, hint, tone = "neutral" }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "accent";
}) {
  return (
    <div className={`metric-card metric-card--${tone}`}>
      <div className="eyebrow">{label}</div>
      <div className="metric-card__value">{value}</div>
      {hint ? <div className="metric-card__hint">{hint}</div> : null}
    </div>
  );
}
