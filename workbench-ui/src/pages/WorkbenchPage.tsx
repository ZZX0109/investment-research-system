import { ModeSwitch } from "../components/ModeSwitch";
import { LanguageSwitch } from "../components/LanguageSwitch";
import { useI18n } from "../i18n";
import { Activity, Clock3, Database, Globe2, LockKeyhole, ShieldCheck } from "lucide-react";
import { AnalysisPanel } from "../features/analysis/AnalysisPanel";
import { ResearchAuditPanel } from "../features/audit/ResearchAuditPanel";
import { AuthCard } from "../features/auth/AuthCard";
import { AuditPanel } from "../features/governance/AuditPanel";
import { ProvenancePanel } from "../features/governance/ProvenancePanel";
import { RunLineagePanel } from "../features/governance/RunLineagePanel";
import { SelectedRunContextBar } from "../features/governance/SelectedRunContextBar";
import { AssetComposer } from "../features/overview/AssetComposer";
import { PortfolioPanel } from "../features/overview/PortfolioPanel";
import { ResearchPanel } from "../features/research/ResearchPanel";
import { HistoricalAnalogyPanel } from "../features/history/HistoricalAnalogyPanel";
import { ResearchOperationsPanel } from "../features/operations/ResearchOperationsPanel";
import { PortfolioRiskPanel } from "../features/risk/PortfolioRiskPanel";
import { useWorkbenchStore } from "../state/workbenchStore";
import { AgentExecutionPanel } from "../features/agent/AgentExecutionPanel";

export function WorkbenchPage() {
  const mode = useWorkbenchStore((state) => state.mode);
  const setMode = useWorkbenchStore((state) => state.setMode);
  const { t } = useI18n();
  return (
    <div className="workbench-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <Activity size={22} aria-hidden="true" />
          <div><h1>{t("brand.name")}</h1><span>{t("brand.tagline")}</span></div>
        </div>
        <div className="app-header__context" aria-label={t("header.context")}>
          <span><Globe2 size={14} /> {t("header.market")}</span>
          <span><Clock3 size={14} /> {t("header.closeConfirmed")}</span>
        </div>
        <div className="app-header__status">
          <span className="system-status"><Database size={15} aria-hidden="true" /> {mode === "research" ? "research_pit" : mode} data</span>
          <span className="system-status"><ShieldCheck size={15} aria-hidden="true" /> {t("header.strictGate")}</span>
          {mode === "real" ? <span className="system-status system-status--blocked"><LockKeyhole size={14} /> blocked</span> : null}
          <LanguageSwitch />
          <ModeSwitch mode={mode} onChange={setMode} />
        </div>
      </header>

      {mode === "research" ? (
        <div className="research-mode-banner" role="status">
          {t("banner.research")}
        </div>
      ) : mode === "real" ? (
        <div className="research-mode-banner research-mode-banner--formal" role="status">
          {t("banner.formal")}
        </div>
      ) : null}

      <SelectedRunContextBar />

      <main className="workspace-grid">
        <div className="workspace-column">
          <AuthCard />
          <PortfolioPanel />
          <AssetComposer />
        </div>
        <div className="workspace-column workspace-column--wide">
          <AgentExecutionPanel />
          <AnalysisPanel />
          <HistoricalAnalogyPanel />
          <ResearchPanel />
        </div>
        <div className="workspace-column">
          <PortfolioRiskPanel />
          <ResearchAuditPanel />
          <ResearchOperationsPanel />
          <ProvenancePanel />
          <RunLineagePanel />
          <AuditPanel />
        </div>
      </main>
    </div>
  );
}
