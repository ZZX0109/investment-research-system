import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "./i18n";
import { StockWorkspacePage } from "./pages/StockWorkspacePage";

const queryClient = new QueryClient();

export function App() {
  // One merged screen: 选股 → 仪表盘 (snapshot tiles) → AI 多轮, with the
  // example questions, the five-section plain-answer structure and the
  // professional workbench (audit / lineage / shadow / governance) folded in
  // as a collapsed region.  No view tabs.
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <StockWorkspacePage />
      </I18nProvider>
    </QueryClientProvider>
  );
}
