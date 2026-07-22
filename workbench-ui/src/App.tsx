import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "./i18n";
import { WorkbenchPage } from "./pages/WorkbenchPage";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <WorkbenchPage />
      </I18nProvider>
    </QueryClientProvider>
  );
}
