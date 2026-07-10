import { useEffect, useState } from "react";
import type { HoldingInput, PreferenceKey } from "../../components/types";
import { useDashboardState } from "../../hooks/useDashboardState";
import { useWorkbenchData } from "../../hooks/useWorkbenchData";

export function useWorkbenchController() {
  const [preference, setPreference] = useState<PreferenceKey>("balanced");
  const dashboard = useDashboardState();
  const data = useWorkbenchData(preference, dashboard.selectedSymbol, () => dashboard.setError("登录状态已失效，请重新登录。"));

  const portfolio = data.portfolioQuery.data ?? null;
  const research = data.researchQuery.data ?? null;
  const refreshReview = data.refreshMutation.data ?? null;
  const booting = data.sessionQuery.isLoading;

  useEffect(() => {
    if (data.profile?.preference) setPreference(data.profile.preference);
  }, [data.profile?.preference]);

  useEffect(() => {
    if (portfolio?.holdings.length && !dashboard.selectedSymbol) {
      dashboard.setSelectedSymbol(portfolio.holdings[0].symbol);
    }
  }, [portfolio?.holdings, dashboard.selectedSymbol, dashboard.setSelectedSymbol]);

  useEffect(() => {
    if (data.sessionQuery.isLoading || data.portfolioQuery.isLoading || data.researchQuery.isLoading || data.refreshMutation.isPending) {
      dashboard.setApiState("loading");
      return;
    }
    if (data.sessionQuery.isError || data.portfolioQuery.isError || data.researchQuery.isError || data.refreshMutation.isError) {
      dashboard.setApiState("fallback");
      return;
    }
    if (portfolio || research) dashboard.setApiState("live");
  }, [
    data.sessionQuery.isLoading,
    data.portfolioQuery.isLoading,
    data.researchQuery.isLoading,
    data.refreshMutation.isPending,
    data.sessionQuery.isError,
    data.portfolioQuery.isError,
    data.researchQuery.isError,
    data.refreshMutation.isError,
    portfolio,
    research,
    dashboard.setApiState,
  ]);

  useEffect(() => {
    const nextError =
      (data.authMutation.error as Error | null)?.message
      ?? (data.onboardingMutation.error as Error | null)?.message
      ?? (data.portfolioQuery.error as Error | null)?.message
      ?? (data.researchQuery.error as Error | null)?.message
      ?? (data.refreshMutation.error as Error | null)?.message
      ?? null;
    if (nextError) dashboard.setError(nextError);
  }, [
    data.authMutation.error,
    data.onboardingMutation.error,
    data.portfolioQuery.error,
    data.researchQuery.error,
    data.refreshMutation.error,
    dashboard.setError,
  ]);

  async function handleAuth(mode: "login" | "register", email: string, password: string) {
    const payload = await data.authMutation.mutateAsync({ mode, email, password });
    setPreference(payload.profile.preference);
    dashboard.setError(null);
  }

  async function handleOnboarding(preferenceValue: PreferenceKey, riskAnswers: Record<string, unknown>, holdings: HoldingInput[]) {
    await data.onboardingMutation.mutateAsync({ preferenceValue, riskAnswers, holdings });
    setPreference(preferenceValue);
    dashboard.setError(null);
  }

  async function refreshApiKeys() {
    await data.apiKeysMutation.mutateAsync();
  }

  async function handleDocumentUpload(file: File | null) {
    if (!file || !data.activeSymbol) return;
    dashboard.setUploadState(`正在解析 ${file.name}`);
    try {
      await data.uploadDocument(file, data.activeSymbol);
      dashboard.setUploadState(`${file.name} 已完成多模态解析`);
      dashboard.setApiState("live");
    } catch (err) {
      dashboard.setUploadState(`解析失败: ${(err as Error).message}`);
      dashboard.setApiState("fallback");
    }
  }

  async function updateReportFrequency(frequency: string) {
    if (!data.activeSymbol) return;
    try {
      await data.updateReportFrequency(data.activeSymbol, frequency);
      dashboard.setApiState("live");
    } catch (err) {
      dashboard.setError(`报告频率设置失败: ${(err as Error).message}`);
    }
  }

  async function handleRefreshDaily() {
    try {
      dashboard.setApiState("loading");
      await data.refreshMutation.mutateAsync();
      dashboard.setError(null);
    } catch (err) {
      dashboard.setApiState("fallback");
      dashboard.setError(`刷新失败: ${(err as Error).message}`);
    }
  }

  return {
    preference,
    setPreference,
    ...dashboard,
    ...data,
    portfolio,
    research,
    refreshReview,
    booting,
    handleAuth,
    handleOnboarding,
    refreshApiKeys,
    handleDocumentUpload,
    updateReportFrequency,
    handleRefreshDaily,
  };
}
