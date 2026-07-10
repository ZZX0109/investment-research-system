import React from "react";
import { Scale } from "lucide-react";
import type { ResearchPayload } from "./types";

interface DebatePanelProps {
  research: ResearchPayload;
}

export default function DebatePanel({ research }: DebatePanelProps) {
  return (
    <div className="debate-grid">
      <article className="document-block">
        <h3>支持观点</h3>
        <ul className="compact-list">{research.debate.bull.map((item) => <li key={item}>{item}</li>)}</ul>
      </article>
      <article className="document-block">
        <h3>反方观点</h3>
        <ul className="compact-list">{research.debate.bear.map((item) => <li key={item}>{item}</li>)}</ul>
      </article>
      <article className="document-block">
        <h3>中立裁判</h3>
        <p>{research.debate.judge.detail}</p>
        <ul className="compact-list">{research.debate.invalidators.map((item) => <li key={item}>{item}</li>)}</ul>
      </article>
    </div>
  );
}
