import React from "react";
import { CheckSquare } from "lucide-react";
import type { ResearchPayload } from "./types";

interface ChecklistPanelProps {
  research: ResearchPayload;
}

export default function ChecklistPanel({ research }: ChecklistPanelProps) {
  return (
    <div className="checklist-panel">
      <article className="document-block">
        <h3>
          <CheckSquare size={18} />
          观察清单
        </h3>
        <ul className="compact-list">
          {research.observationChecklist.map((item) => (
            <li key={item.item}>
              <strong>{item.trigger}</strong>: {item.item}（{item.frequency}）
              <span className={item.status === "ok" ? "positive" : "warn"}>{item.status}</span>
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}
