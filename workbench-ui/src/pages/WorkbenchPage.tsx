import { ModeSwitch } from "../components/ModeSwitch";
import { Activity, Database, ShieldCheck } from "lucide-react";
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
  return (
    <div className="workbench-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <Activity size={22} aria-hidden="true" />
          <div><h1>WorkBuddy Research Workbench</h1><span>Point-in-time investment risk console</span></div>
        </div>
        <div className="app-header__status">
          <span className="system-status"><Database size={15} aria-hidden="true" /> {mode} data</span>
          <span className="system-status"><ShieldCheck size={15} aria-hidden="true" /> strict gate</span>
          <ModeSwitch mode={mode} onChange={setMode} />
        </div>
      </header>

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
