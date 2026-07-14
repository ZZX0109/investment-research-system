import { ApiError } from "../../api/client";

export function formatQueryFailure(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.kind === "auth") {
      return "Session expired. Please sign in again.";
    }
    if (error.kind === "csrf") {
      return "Security check failed. Refresh the page and retry so the CSRF token can be renewed.";
    }
    if (error.kind === "not_found") {
      return "The selected analysis run or report snapshot is no longer available.";
    }
    return error.detail || error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

export function hasMissingSourceMetadata(source: {
  provider?: string | null;
  mode?: string | null;
  as_of?: string | null;
}): boolean {
  return !source.provider || !source.mode || !source.as_of;
}

export function isStaleAsOf(asOf?: string | null, maxAgeDays = 7): boolean {
  if (!asOf) {
    return false;
  }
  const asOfTime = new Date(asOf).getTime();
  if (Number.isNaN(asOfTime)) {
    return false;
  }
  const now = Date.now();
  return now - asOfTime > maxAgeDays * 24 * 60 * 60 * 1000;
}
