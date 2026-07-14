import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkbenchPage } from "./pages/WorkbenchPage";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WorkbenchPage />
    </QueryClientProvider>
  );
}
