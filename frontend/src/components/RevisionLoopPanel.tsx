import React from "react";
import { RefreshCcw, ChevronRight } from "lucide-react";
import type { ResearchPayload } from "./types";

interface RevisionLoopPanelProps {
  research: ResearchPayload;
}

export default function RevisionLoopPanel({ research }: RevisionLoopPanelProps) {
  return (
    <div className="revision-flow">
      <article className="document-block">
        <h3>
          <RefreshCcw size={18} />
          报告审计修订 Loop
        </h3>
        <p>{research.reportRevisionLoop.revisedSummary}</p>
        <div className="revision-steps">
          <span>{research.reportRevisionLoop.draftStatus}</span>
          <ChevronRight size={16} />
          <span>{research.reportRevisionLoop.judgeVerdict}</span>
          <ChevronRight size={16} />
          <span>{research.reportRevisionLoop.finalStatus}</span>
        </div>
      </article>
      <article className="document-block">
        <h3>补证据 / 降级动作</h3>
        <ul className="compact-list">
          {research.reportRevisionLoop.toolBackfillActions.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>
    </div>
  );
}
