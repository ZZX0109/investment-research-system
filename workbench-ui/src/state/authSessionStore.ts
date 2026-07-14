import { create } from "zustand";

type AuthFormMode = "login" | "register";

interface AuthSessionState {
  email: string;
  displayName: string;
  password: string;
  formMode: AuthFormMode;
  lastError: string | null;
  setEmail(value: string): void;
  setDisplayName(value: string): void;
  setPassword(value: string): void;
  setFormMode(value: AuthFormMode): void;
  setLastError(value: string | null): void;
  clearLastError(): void;
  resetForm(): void;
}

const DEFAULT_EMAIL = "";
const DEFAULT_DISPLAY_NAME = "";
const DEFAULT_PASSWORD = "";

export const useAuthSessionStore = create<AuthSessionState>((set) => ({
  email: DEFAULT_EMAIL,
  displayName: DEFAULT_DISPLAY_NAME,
  password: DEFAULT_PASSWORD,
  formMode: "login",
  lastError: null,
  setEmail: (email) => set({ email }),
  setDisplayName: (displayName) => set({ displayName }),
  setPassword: (password) => set({ password }),
  setFormMode: (formMode) => set({ formMode, lastError: null }),
  setLastError: (lastError) => set({ lastError }),
  clearLastError: () => set({ lastError: null }),
  resetForm: () =>
    set({
      email: DEFAULT_EMAIL,
      displayName: DEFAULT_DISPLAY_NAME,
      password: DEFAULT_PASSWORD,
      formMode: "login",
      lastError: null
    })
}));
