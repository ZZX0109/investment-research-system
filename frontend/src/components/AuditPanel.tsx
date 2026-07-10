import React from "react";
import { ShieldCheck } from "lucide-react";
import type { ResearchPayload } from "./types";

interface AuditPanelProps {
  research: ResearchPayload;
}

export default function AuditPanel({ research }: AuditPanelProps) {
  return (
    <div className="audit-grid">
      <article className="document-block">
        <h3>
          <ShieldCheck size={18} />
          {research.evidenceAudit.verdict}
        </h3>
        <p>{research.evidenceAudit.scope} {research.evidenceAudit.judgeVersion ? `版本 ${research.evidenceAudit.judgeVersion}` : ""}</p>
        <div className="check-list">
          {research.evidenceAudit.dimensions.map((dimension) => (
            <span className={dimension.passed ? "check-pass" : "check-fail"} key={dimension.key}>{dimension.label}</span>
          ))}
        </div>
      </article>
      <article className="document-block">
        <h3>研究质量维度</h3>
        <ul className="compact-list">
          {research.evidenceAudit.dimensions.map((dimension) => (
            <li key={dimension.key}>
              <strong>{dimension.label}</strong>: {dimension.detail}
            </li>
          ))}
        </ul>
      </article>
      <article className="document-block">
        <h3>审计发现</h3>
        <ul className="compact-list">
          {research.evidenceAudit.findings.map((finding) => (
            <li key={finding.title}><strong>{finding.title}</strong>: {finding.detail}</li>
          ))}
        </ul>
      </article>
      <article className="document-block authority-block">
        <h3>权威来源检索助理</h3>
        <ul className="compact-list">
          {research.evidenceAudit.authoritySources.map((source) => (
            <li key={source.name}>
              <a href={source.url} target="_blank" rel="noreferrer">{source.name}</a>
              <small>{source.authority} · {source.status}</small>
            </li>
          ))}
        </ul>
      </article>
      <article className="document-block">
        <h3>Judge v2 Gate</h3>
        <ul className="compact-list">
          {Object.entries(research.evidenceAudit.v2Checks ?? {}).map(([key, passed]) => (
            <li key={key}>
              <strong>{passed ? "pass" : "fail"}</strong>: {key}
            </li>
          ))}
        </ul>
      </article>
    </div>
  );
}
