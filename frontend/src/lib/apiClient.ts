import { QueryClient } from "@tanstack/react-query";

export const API_BASE = import.meta.env.VITE_API_BASE ?? `${window.location.protocol}//${window.location.hostname}:8000`;

let accessToken: string | null = null;

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(message: string, status: number, code = "api_error", details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type RequestOptions = RequestInit & {
  retryOn401?: boolean;
  onUnauthorized?: () => void;
  onTokenRefresh?: (token: string) => void;
};

async function parseErrorDetail(response: Response) {
  return response.json().catch(() => null);
}

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function clearAccessToken() {
  accessToken = null;
}

function resolvePayloadToken(payload: { token?: string; accessToken?: string }) {
  return payload.accessToken ?? payload.token ?? null;
}

async function refreshAccessToken(init: RequestOptions = {}) {
  const response = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    clearAccessToken();
    return null;
  }
  const payload = await response.json() as { token?: string; accessToken?: string };
  const nextToken = resolvePayloadToken(payload);
  if (!nextToken) {
    clearAccessToken();
    return null;
  }
  setAccessToken(nextToken);
  init.onTokenRefresh?.(nextToken);
  return nextToken;
}

function shouldRefresh(path: string, init: RequestOptions) {
  return init.retryOn401 !== false && path !== "/api/auth/refresh" && path !== "/api/auth/logout";
}

function handleUnauthorized(init: RequestOptions): never {
  clearAccessToken();
  init.onUnauthorized?.();
  throw new ApiError("登录状态已失效，请重新登录。", 401, "unauthorized");
}

export async function apiRequest<T>(path: string, token: string | null, init: RequestOptions = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const requestToken = token ?? getAccessToken();
  if (requestToken) headers.set("Authorization", `Bearer ${requestToken}`);

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: init.credentials ?? "include" });
  if (response.status === 401) {
    if (shouldRefresh(path, init)) {
      const refreshedToken = await refreshAccessToken(init);
      if (refreshedToken) {
        return apiRequest<T>(path, refreshedToken, { ...init, retryOn401: false });
      }
    }
    handleUnauthorized(init);
  }
  if (response.status === 403) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(detail?.detail ?? "请求被拒绝，请检查 CSRF / 权限状态。", 403, "forbidden", detail);
  }
  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(detail?.detail ?? `${response.status} ${response.statusText}`, response.status, "request_failed", detail);
  }
  return response.json() as Promise<T>;
}

export async function apiTextRequest(path: string, token: string | null, init: RequestOptions = {}): Promise<string> {
  const headers = new Headers(init.headers);
  const requestToken = token ?? getAccessToken();
  if (requestToken) headers.set("Authorization", `Bearer ${requestToken}`);

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: init.credentials ?? "include" });
  if (response.status === 401) {
    if (shouldRefresh(path, init)) {
      const refreshedToken = await refreshAccessToken(init);
      if (refreshedToken) {
        return apiTextRequest(path, refreshedToken, { ...init, retryOn401: false });
      }
    }
    handleUnauthorized(init);
  }
  if (response.status === 403) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(detail?.detail ?? "请求被拒绝，请检查 CSRF / 权限状态。", 403, "forbidden", detail);
  }
  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    throw new ApiError(detail?.detail ?? `${response.status} ${response.statusText}`, response.status, "request_failed", detail);
  }
  return response.text();
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry(failureCount, error) {
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) return false;
          return failureCount < 1;
        },
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
