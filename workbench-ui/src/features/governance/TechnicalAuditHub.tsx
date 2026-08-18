import { Database, FileText, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../i18n";
import { AnalysisPanel } from "../analysis/AnalysisPanel";
import { ResearchAuditPanel } from "../audit/ResearchAuditPanel";
import { AuditPanel } from "./AuditPanel";
import { ProvenancePanel } from "./ProvenancePanel";
import { RunLineagePanel } from "./RunLineagePanel";
import { ResearchOperationsPanel } from "../operations/ResearchOperationsPanel";
import { PortfolioRiskPanel } from "../risk/PortfolioRiskPanel";

type TechnicalSection = "data" | "runs" | "audit";

export function TechnicalAuditHub() {
  const { l } = useI18n();
  const [section, setSection] = useState<TechnicalSection>("data");

  const sections = [
    {
      id: "data" as const,
      icon: Database,
      label: l("数据与模型", "Data & models"),
      description: l("检查数据质量、模型清单、研究任务和前向验证状态。", "Inspect data quality, model rosters, research tasks and forward validation."),
    },
    {
      id: "runs" as const,
      icon: FileText,
      label: l("运行与报告", "Runs & reports"),
      description: l("管理分析运行、固定报告和后台更新任务。", "Manage analysis runs, fixed reports and background update jobs."),
    },
    {
      id: "audit" as const,
      icon: ShieldCheck,
      label: l("证据与审计", "Evidence & audit"),
      description: l("追溯数据来源、证据记录、运行血缘和审计结论。", "Trace provenance, evidence records, run lineage and audit conclusions."),
    },
  ];
  const active = sections.find((item) => item.id === section) ?? sections[0];

  return (
    <div className="technical-hub">
      <nav className="technical-hub__tabs" role="tablist" aria-label={l("技术详情分类", "Technical detail categories")}>
        {sections.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={section === item.id}
              className={section === item.id ? "is-active" : ""}
              onClick={() => setSection(item.id)}
            >
              <Icon size={16} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="technical-hub__intro">
        <strong>{active.label}</strong>
        <p>{active.description}</p>
      </div>

      <section className={`technical-hub__content technical-hub__content--${section}`} role="tabpanel">
        {section === "data" ? (
          <div className="technical-hub__grid technical-hub__grid--data">
            <PortfolioRiskPanel />
          </div>
        ) : null}
        {section === "runs" ? (
          <div className="technical-hub__grid technical-hub__grid--runs">
            <AnalysisPanel />
            <ResearchOperationsPanel />
          </div>
        ) : null}
        {section === "audit" ? (
          <div className="technical-hub__grid technical-hub__grid--audit">
            <ResearchAuditPanel />
            <ProvenancePanel />
            <RunLineagePanel />
            <AuditPanel />
          </div>
        ) : null}
      </section>
    </div>
  );
}
