import { LockKeyhole, Sparkles } from "lucide-react";
import { StatusBadge } from "./StatusBadge";

export function ResearchHero({ status, asOf, decisionContext }: {
  status: string;
  asOf?: string | null;
  decisionContext?: string | null;
}) {
  return (
    <section className="research-hero">
      <div className="research-hero__glow" aria-hidden="true" />
      <div className="research-hero__main">
        <div className="research-hero__eyebrow"><Sparkles size={14} /> A 股研究工作台 · {decisionContext === "pre_open" ? "盘前研究" : "收盘确认研究"}</div>
        <h3>让每一个判断，都有数据边界。</h3>
        <p>免费公开数据驱动的研究概率、风险区间和可复核证据。研究结果不构成投资建议，也不直接用于交易。</p>
      </div>
      <div className="research-hero__meta">
        <StatusBadge status={status} />
        <span className="research-hero__asof"><LockKeyhole size={14} /> 数据截至 {asOf ? new Date(asOf).toLocaleString() : "等待快照"}</span>
      </div>
    </section>
  );
}
