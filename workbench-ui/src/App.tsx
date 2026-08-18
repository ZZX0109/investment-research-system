import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { I18nProvider } from "./i18n";
import { CompetitionHome } from "./pages/CompetitionHome";
import { StockWorkspacePage } from "./pages/StockWorkspacePage";
import { WorkbenchPage } from "./pages/WorkbenchPage";

const queryClient = new QueryClient();

type View = "home" | "workspace" | "workbench";

export function App() {
  // The competition homepage is the default view judges and retail investors
  // see.  The stock workspace (选股 → 仪表盘 snapshot tiles → AI multi-turn)
  // is one toggle away; the full professional workbench (technical audit, run
  // lineage, shadow progress, governance) remains reachable for reviewers.
  const [view, setView] = useState<View>("home");
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ViewToggle view={view} setView={setView} />
        {view === "home" ? <CompetitionHome /> : view === "workspace" ? <StockWorkspacePage /> : <WorkbenchPage />}
      </I18nProvider>
    </QueryClientProvider>
  );
}

function ViewToggle({ view, setView }: { view: View; setView: (view: View) => void }) {
  return (
    <div className="view-toggle" role="tablist" aria-label="切换视图">
      <button type="button" role="tab" aria-selected={view === "home"} className={view === "home" ? "is-active" : ""} onClick={() => setView("home")}>长期投资助手</button>
      <button type="button" role="tab" aria-selected={view === "workspace"} className={view === "workspace" ? "is-active" : ""} onClick={() => setView("workspace")}>选股·仪表盘·AI</button>
      <button type="button" role="tab" aria-selected={view === "workbench"} className={view === "workbench" ? "is-active" : ""} onClick={() => setView("workbench")}>专业研究台</button>
    </div>
  );
}
