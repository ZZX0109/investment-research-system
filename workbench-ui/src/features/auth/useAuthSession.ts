import { useQueryClient } from "@tanstack/react-query";
import { resolveWorkbenchDataSource } from "../../api/client";
import { useLoginMutation, useLogoutMutation, useRegisterMutation, useSessionQuery } from "../../hooks/useWorkbenchQueries";
import { useAuthSessionStore } from "../../state/authSessionStore";
import { useWorkbenchStore } from "../../state/workbenchStore";

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "unknown error";
}

function clearRealModeQueries(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.removeQueries({
    predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[1] === "real"
  });
}

async function resetRealModeQueries(queryClient: ReturnType<typeof useQueryClient>) {
  await queryClient.resetQueries({
    predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[1] === "real"
  });
}

export function useAuthSession() {
  const queryClient = useQueryClient();
  const mode = useWorkbenchStore((state) => state.mode);
  const resetWorkspace = useWorkbenchStore((state) => state.resetWorkspace);
  const sessionQuery = useSessionQuery();
  const loginMutation = useLoginMutation();
  const registerMutation = useRegisterMutation();
  const logoutMutation = useLogoutMutation();
  const email = useAuthSessionStore((state) => state.email);
  const displayName = useAuthSessionStore((state) => state.displayName);
  const password = useAuthSessionStore((state) => state.password);
  const formMode = useAuthSessionStore((state) => state.formMode);
  const lastError = useAuthSessionStore((state) => state.lastError);
  const setEmail = useAuthSessionStore((state) => state.setEmail);
  const setDisplayName = useAuthSessionStore((state) => state.setDisplayName);
  const setPassword = useAuthSessionStore((state) => state.setPassword);
  const setFormMode = useAuthSessionStore((state) => state.setFormMode);
  const setLastError = useAuthSessionStore((state) => state.setLastError);
  const clearLastError = useAuthSessionStore((state) => state.clearLastError);
  const resetForm = useAuthSessionStore((state) => state.resetForm);

  const usesSeededSession = resolveWorkbenchDataSource(mode) !== "api";

  async function submitLogin() {
    clearLastError();
    try {
      await loginMutation.mutateAsync({ email, password });
      resetWorkspace();
      await resetRealModeQueries(queryClient);
    } catch (error) {
      setLastError(getErrorMessage(error));
      throw error;
    }
  }

  async function submitRegister() {
    clearLastError();
    try {
      await registerMutation.mutateAsync({ email, display_name: displayName, password });
      resetWorkspace();
      await resetRealModeQueries(queryClient);
    } catch (error) {
      setLastError(getErrorMessage(error));
      throw error;
    }
  }

  async function submitLogout() {
    clearLastError();
    try {
      await logoutMutation.mutateAsync();
      resetWorkspace();
      resetForm();
      clearRealModeQueries(queryClient);
    } catch (error) {
      setLastError(getErrorMessage(error));
      throw error;
    }
  }

  const isSubmitting = loginMutation.isPending || registerMutation.isPending || logoutMutation.isPending;
  const status =
    usesSeededSession
      ? "seeded"
      : sessionQuery.isLoading
        ? "loading"
        : sessionQuery.data?.user
          ? "authenticated"
          : sessionQuery.isError
            ? "error"
            : "anonymous";

  return {
    usesSeededSession,
    session: sessionQuery.data,
    sessionError: sessionQuery.error instanceof Error ? sessionQuery.error.message : null,
    status,
    isSubmitting,
    isLoggingIn: loginMutation.isPending,
    isRegistering: registerMutation.isPending,
    isLoggingOut: logoutMutation.isPending,
    form: {
      email,
      displayName,
      password,
      formMode,
      lastError
    },
    setEmail,
    setDisplayName,
    setPassword,
    setFormMode,
    submitLogin,
    submitRegister,
    submitLogout
  };
}
