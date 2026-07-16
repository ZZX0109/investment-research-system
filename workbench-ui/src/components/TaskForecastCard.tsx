import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

export function TaskForecastCard({ task, title, status, value, model, detail }: {
  task: string;
  title: string;
  status: string;
  value: ReactNode;
  model?: string | null;
  detail?: ReactNode;
}) {
  return (
    <details className="task-forecast-card">
      <summary>
        <div className="task-forecast-card__title"><span className="task-forecast-card__index">{task}</span><strong>{title}</strong></div>
        <StatusBadge status={status} />
      </summary>
      <div className="task-forecast-card__body">
        <div className="task-forecast-card__value">{value}</div>
        {model ? <div className="muted">模型 {model}</div> : null}
        {detail ? <div className="task-forecast-card__detail">{detail}</div> : null}
      </div>
      <ChevronDown className="task-forecast-card__chevron" size={16} aria-hidden="true" />
    </details>
  );
}
