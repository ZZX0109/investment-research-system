import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ApiKeySummary,
  AuthPayload,
  HoldingInput,
  PortfolioPayload,
  PreferenceKey,
  RefreshReviewPayload,
  ResearchPayload,
  UserProfile,
  UserProfileState,
} from "../components/types";
import { apiRequest, clearAccessToken, getAccessToken, setAccessToken } from "../lib/apiClient";

export function useWorkbenchData(preference: PreferenceKey, selectedSymbol: string, onUnauthorized: () => void) {
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState<string | null>(() => getAccessToken());

  function syncToken(nextToken: string | null) {
    setAccessToken(nextToken);
    setTokenState(nextToken);
  }

  function handleUnauthorized() {
    clearAccessToken();
    setTokenState(null);
    onUnauthorized();
  }

  const authRequestOptions = {
    onUnauthorized: handleUnauthorized,
    onTokenRefresh: syncToken,
  };

  const sessionQuery = useQuery({
    queryKey: ["session", token],
    enabled: Boolean(token),
    queryFn: () => apiRequest<{ user: UserProfile; profile: UserProfileState; apiKeys: ApiKeySummary[] }>("/api/auth/me", token, authRequestOptions),
  });

  const profile = sessionQuery.data?.profile ?? null;
  const user = sessionQuery.data?.user ?? null;
  const apiKeys = sessionQuery.data?.apiKeys ?? [];

  const portfolioQuery = useQuery({
    queryKey: ["portfolio", token, preference],
    enabled: Boolean(token && profile?.onboardingCompleted),
    queryFn: () => apiRequest<PortfolioPayload>(`/api/portfolio?preference=${preference}`, token, authRequestOptions),
  });

  const activeSymbol = useMemo(() => {
    if (selectedSymbol) return selectedSymbol;
    return portfolioQuery.data?.holdings[0]?.symbol ?? "";
  }, [portfolioQuery.data?.holdings, selectedSymbol]);

  const researchQuery = useQuery({
    queryKey: ["research", token, activeSymbol, preference],
    enabled: Boolean(token && profile?.onboardingCompleted && activeSymbol),
    queryFn: () => apiRequest<ResearchPayload>(`/api/research/${activeSymbol}?preference=${preference}`, token, authRequestOptions),
  });

  const refreshMutation = useMutation({
    mutationFn: () => apiRequest<RefreshReviewPayload>("/api/refresh/daily", token, { method: "POST", ...authRequestOptions }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      await queryClient.invalidateQueries({ queryKey: ["research"] });
    },
  });

  const authMutation = useMutation({
    mutationFn: ({ mode, email, password }: { mode: "login" | "register"; email: string; password: string }) =>
      apiRequest<AuthPayload>(`/api/auth/${mode}`, null, { method: "POST", body: JSON.stringify({ email, password }) }),
    onSuccess: (payload) => {
      const nextToken = payload.accessToken ?? payload.token;
      syncToken(nextToken);
      queryClient.setQueryData(["session", nextToken], payload);
    },
  });

  const onboardingMutation = useMutation({
    mutationFn: ({ preferenceValue, riskAnswers, holdings }: { preferenceValue: PreferenceKey; riskAnswers: Record<string, unknown>; holdings: HoldingInput[] }) =>
      apiRequest<{ user: UserProfile; profile: UserProfileState; portfolio: PortfolioPayload }>(
        "/api/onboarding",
        token,
        { method: "POST", body: JSON.stringify({ preference: preferenceValue, riskAnswers, holdings }), ...authRequestOptions }
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["session"] });
      await queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });

  const apiKeysMutation = useMutation({
    mutationFn: () => apiRequest<{ apiKeys: ApiKeySummary[] }>("/api/api-keys", token, authRequestOptions),
    onSuccess: (payload) => {
      if (!token) return;
      queryClient.setQueryData<{ user: UserProfile; profile: UserProfileState; apiKeys: ApiKeySummary[] } | undefined>(["session", token], (prev) =>
        prev ? { ...prev, apiKeys: payload.apiKeys } : prev
      );
    },
  });

  async function uploadDocument(file: File, symbol: string) {
    const formData = new FormData();
    formData.append("file", file);
    await apiRequest(`/api/documents/${symbol}/analyze`, token, { method: "POST", body: formData, ...authRequestOptions });
    await queryClient.invalidateQueries({ queryKey: ["research", token, symbol, preference] });
  }

  async function updateReportFrequency(symbol: string, frequency: string) {
    await apiRequest("/api/settings/report", token, {
      method: "POST",
      body: JSON.stringify({ frequency }),
      ...authRequestOptions,
    });
    await queryClient.invalidateQueries({ queryKey: ["research", token, symbol, preference] });
  }

  function logout() {
    void apiRequest("/api/auth/logout", token, { method: "POST", retryOn401: false }).catch(() => undefined);
    syncToken(null);
    queryClient.clear();
  }

  useEffect(() => {
    if (!token) queryClient.removeQueries({ queryKey: ["session"] });
  }, [queryClient, token]);

  useEffect(() => {
    let cancelled = false;
    if (token) return;
    apiRequest<AuthPayload>("/api/auth/refresh", null, { method: "POST", retryOn401: false })
      .then((payload) => {
        if (cancelled) return;
        const nextToken = payload.accessToken ?? payload.token;
        if (!nextToken) return;
        syncToken(nextToken);
        queryClient.setQueryData(["session", nextToken], payload);
      })
      .catch(() => {
        if (!cancelled) clearAccessToken();
      });
    return () => {
      cancelled = true;
    };
  }, [queryClient, token]);

  return {
    token,
    setToken: syncToken,
    user,
    profile,
    apiKeys,
    sessionQuery,
    portfolioQuery,
    researchQuery,
    refreshMutation,
    authMutation,
    onboardingMutation,
    apiKeysMutation,
    uploadDocument,
    updateReportFrequency,
    logout,
    activeSymbol,
  };
}
