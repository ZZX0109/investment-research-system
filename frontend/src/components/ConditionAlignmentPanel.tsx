import React from "react";
import type { ResearchPayload } from "./types";

interface ConditionAlignmentPanelProps {
  research: ResearchPayload;
}

export default function ConditionAlignmentPanel({ research }: ConditionAlignmentPanelProps) {
  return (
    <div className="alignment-list">
      {research.conditionAlignment.factors.map((factor) => (
        <article className="alignment-row" key={factor.factor}>
          <strong>{factor.factor}</strong>
          <span>{factor.current}</span>
          <span>{factor.historical}</span>
          <small className={factor.matched ? "positive" : "warn"}>{factor.matched ? "匹配" : "不完全匹配"}</small>
        </article>
      ))}
    </div>
  );
}
